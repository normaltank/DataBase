"""LAN address selection and live refresh at the CLI / actual HTTP boundary."""
import socket
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import http.cookiejar
import unittest
from unittest.mock import patch

from portable import launch


class PortableLANAddressTests(unittest.TestCase):
    def test_share_candidates_keep_private_shared_and_campus_unicast_only(self):
        candidates = ['10.2.3.4', '172.20.1.2', '192.168.50.20', '100.65.1.2',
                      '166.111.1.2', '198.18.0.1', '198.19.255.254', '224.0.0.1',
                      '255.255.255.255', '0.1.2.3', '127.0.0.1', '169.254.10.2',
                      '192.0.2.1', '198.51.100.2', '203.0.113.3', '240.1.2.3']
        entries = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 0)) for ip in candidates]
        with patch('socket.getaddrinfo', return_value=entries), patch('socket.socket'):
            self.assertEqual(launch.lan_addresses(),
                             ['10.2.3.4', '100.65.1.2', '166.111.1.2', '172.20.1.2', '192.168.50.20'])

    def test_hostname_addresses_must_be_currently_assigned(self):
        entries = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.2.3.4', 0))]
        with patch('socket.getaddrinfo', return_value=entries), patch('socket.socket') as connection:
            connection.return_value.__enter__.return_value.bind.side_effect = OSError('not assigned')
            self.assertEqual(launch.lan_addresses(), [])
        with patch('socket.getaddrinfo', side_effect=socket.gaierror('offline')):
            self.assertEqual(launch.lan_addresses(), [])


@unittest.skipUnless(os.name == 'nt', 'The portable launcher owns Windows byte locks')
class PortableLANLiveTests(unittest.TestCase):
    def test_repeated_start_refreshes_live_hosts_without_replacing_instance_or_identity(self):
        from platform_app.web import create_app
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='portable-lan-synthetic-') as temporary:
            root = Path(temporary)
            (root / 'portable').mkdir()
            # Only the OS address-enumeration/bind boundary is synthetic. CLI,
            # own-process locks, Waitress and HTTP routing are the real code.
            launcher = root / 'portable/launch.py'
            launcher.write_text('''
import importlib.util, json, socket, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(%r)
sys.path.extend(%r)
sys.path.insert(0, str(SOURCE))
original_getaddrinfo, original_socket = socket.getaddrinfo, socket.socket
def inventory():
    return json.loads((ROOT / 'interfaces.json').read_text())
def getaddrinfo(host, *args, **kwargs):
    if host == socket.gethostname():
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 0)) for ip in inventory()]
    return original_getaddrinfo(host, *args, **kwargs)
class LocalSocket(original_socket):
    def bind(self, address):
        if address[0] in inventory():
            return None
        return super().bind(address)
socket.getaddrinfo, socket.socket = getaddrinfo, LocalSocket
spec = importlib.util.spec_from_file_location('synthetic_launcher', SOURCE / 'portable/launch.py')
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
launch.__file__ = __file__
launch.ROOT, launch.STATE = ROOT, ROOT / '.portable'
launch.IDENTITY = __import__('hashlib').sha256(str(ROOT).casefold().encode()).hexdigest()
launch.main()
''' % (str(source), sys.path), encoding='utf-8')
            create_app(root / 'data', testing=True, embedded_worker=False, portable_trial=True)
            fixture = root / 'interfaces.json'
            fixture.write_text(json.dumps(['192.168.50.20', '198.18.0.1']))

            def cli(action):
                result = subprocess.run([sys.executable, str(launcher), action, '--no-browser'],
                                        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
                log = root / '.portable/startup.log'
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr +
                                 (log.read_text(encoding='utf-8') if log.exists() else ''))
                return result.stdout

            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                 urllib.request.HTTPCookieProcessor(jar))
            try:
                cli('lan-start')
                state = json.loads((root / '.portable/server.json').read_text())
                base = 'http://127.0.0.1:' + str(state['port'])

                def get(path='/health', host='192.168.50.20', extra=None, method='GET'):
                    headers = {'Host': host, **(extra or {})}
                    request = urllib.request.Request(base + path, headers=headers, method=method)
                    try:
                        with opener.open(request, timeout=3) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as error:
                        return error.code, None

                self.assertEqual(get()[0], 200)
                identity = get('/api/session', host='127.0.0.1')[1]['user']['id']
                fixture.write_text(json.dumps(['192.168.137.1', '198.18.0.1']))
                self.assertEqual(get(host='192.168.137.1')[0], 400)
                output = cli('lan-start')
                self.assertIn('http://192.168.137.1:', output)
                self.assertNotIn('http://198.18.0.1:', output)
                self.assertEqual(get(host='192.168.137.1')[0], 200)
                self.assertEqual(get(host='192.168.50.20')[0], 400)
                refreshed = json.loads((root / '.portable/server.json').read_text())
                self.assertEqual((refreshed['instance'], refreshed['port']), (state['instance'], state['port']))
                self.assertEqual(get('/api/session', host='127.0.0.1')[1]['user']['id'], identity)
                for host in ('evil.invalid', '198.18.0.1', '10.99.1.2'):
                    self.assertEqual(get(host=host)[0], 400)
                for header in ('Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto'):
                    self.assertEqual(get(host='192.168.137.1', extra={header: '127.0.0.1'})[0], 400)
                self.assertEqual(get('/__portable/refresh', host='127.0.0.1', method='POST')[0], 404)
                for action in ('refresh', 'stop'):
                    self.assertEqual(get('/__portable/' + action, host='evil.invalid', method='POST',
                                         extra={'X-Portable-Token': state['token']})[0], 404)
                    self.assertEqual(get('/__portable/' + action, host='127.0.0.1', method='POST',
                                         extra={'X-Portable-Token': state['token'],
                                                'X-Forwarded-For': '127.0.0.1'})[0], 400)
                diagnostic = json.loads(cli('lan-diagnose'))
                self.assertTrue(diagnostic['service']['owned_instance'])
                self.assertEqual(diagnostic['service']['loopback']['status'], 'ok')
                self.assertFalse(diagnostic['phone_verified'])
                self.assertEqual(diagnostic['external_network_cause'], 'undetermined')
                self.assertEqual(json.loads((root / '.portable/server.json').read_text()), refreshed)
                fixture.write_text('[]')
                cli('lan-start')
                self.assertEqual(get(host='192.168.137.1')[0], 400)
                self.assertEqual(get(host='127.0.0.1')[0], 200)
                fixture.write_text(json.dumps(['192.168.137.1']))
                cli('lan-start')
                self.assertEqual(get(host='192.168.137.1')[0], 200)
            finally:
                cli('stop')
