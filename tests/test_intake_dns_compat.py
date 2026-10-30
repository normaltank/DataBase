"""The member intake API can use public DNS behind a local Fake-IP proxy."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_app.web import create_app


class RemoteSocket:
    def __init__(self, peer, payload, content_type, expected_host=''):
        self.peer = peer
        self.expected_host = expected_host
        self.payload = (f'HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n'
                        f'Content-Length: {len(payload)}\r\n\r\n').encode() + payload

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.payload)

    def getpeername(self):
        return (self.peer, 443)

    def sendall(self, data):
        if self.expected_host and data.startswith(b'GET '):
            assert ('\r\nHost: ' + self.expected_host + '\r\n').encode() in data, data

    def setsockopt(self, *args):
        pass

    def settimeout(self, timeout):
        pass

    def close(self):
        pass


class IntakeProxyDnsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='intake-dns-compat-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name), testing=True)
        self.client = self.app.test_client()
        token = self.client.get('/api/session').json['csrf']
        self.token = self.client.post('/api/login', json={'username':'researcher', 'password':'LocalDemo2026!'},
                                      headers={'X-CSRF-Token':token}).json['csrf']

    def preview(self, address):
        return self.client.post('/api/intake/preview', json={'input':address}, headers={'X-CSRF-Token':self.token})

    def external_network(self, answer='93.184.216.34', question='research.example', system_ip='198.18.1.50', dns_result=None,
                         document=b'<meta name="citation_title" content="Public article through proxy DNS">', mime='text/html'):
        connections=[]
        def connect(address, *args, **kwargs):
            host=address[0]
            connections.append(host)
            if host == '1.1.1.1':
                payload=json.dumps(dns_result if dns_result is not None else
                    {'Status':0,'Question':[{'name':question,'type':1}],
                     'Answer':[{'name':question,'type':1,'TTL':60,'data':answer}]}).encode()
                return RemoteSocket(host,payload,'application/dns-json')
            if host == '93.184.216.34':
                return RemoteSocket(host,document,mime,question)
            raise AssertionError('Unexpected connection target: '+host)
        dns=patch('socket.getaddrinfo',return_value=[(2,1,6,'',(system_ip,443))])
        sockets=patch('socket.create_connection',side_effect=connect)
        tls=patch('ssl.SSLContext.wrap_socket',side_effect=lambda sock,**kwargs:sock)
        return connections,dns,sockets,tls

    def test_public_article_is_reachable_without_connecting_to_proxy_alias(self):
        connections,dns,sockets,tls=self.external_network()
        with dns,sockets,tls:
            result=self.preview('https://research.example/article')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['fields']['title'],'Public article through proxy DNS')
        self.assertEqual(connections,['1.1.1.1','93.184.216.34'])
        self.assertEqual(self.client.get('/api/records').json['total'],0)

    def test_paired_candidates_still_reject_private_and_mixed_public_dns_answers(self):
        for answers in [['127.0.0.1'],['93.184.216.34','10.0.0.1'],['198.18.1.50']]:
            with self.subTest(answers=answers):
                reply={'Status':0,'Question':[{'name':'research.example','type':1}],
                       'Answer':[{'name':'research.example','type':1,'data':ip} for ip in answers]}
                connections,dns,sockets,tls=self.external_network(dns_result=reply)
                mixed=[(2,1,6,'',('198.18.1.50',443)),(23,1,6,'',('2001:2::50',443,0,0))]
                with dns,sockets,tls,patch('socket.getaddrinfo',return_value=mixed):
                    result=self.preview('https://research.example/article')
                self.assertEqual(result.status_code,422,result.json)
                self.assertEqual(connections,['1.1.1.1'])

    def test_unrecognized_alias_combinations_and_ip_literals_never_use_public_dns(self):
        cases=[('https://research.example/', ['2001:2::50'])]
        for other in ['10.0.0.1','127.0.0.1','169.254.1.1','::1','fc00::1','fe80::1',
                      '2001:db8::1','2001:2:1::1','::ffff:198.18.1.50','93.184.216.34']:
            cases.append(('https://research.example/',['198.18.1.50',other]))
        cases += [('https://198.18.1.50/',['198.18.1.50']),
                  ('https://[2001:2::50]/',['2001:2::50'])]
        for url,ips in cases:
            with self.subTest(url=url,ips=ips):
                connections,dns,sockets,tls=self.external_network()
                rows=[(2,1,6,'',(ip,443)) for ip in ips]
                with dns,sockets,tls,patch('socket.getaddrinfo',return_value=rows):
                    result=self.preview(url)
                self.assertEqual(result.status_code,422,result.json)
                self.assertEqual(connections,[])

    def test_paired_benchmark_addresses_retry_public_dns_without_connecting_to_aliases(self):
        connections,dns,sockets,tls=self.external_network()
        mixed=[(2,1,6,'',('198.18.1.50',443)),(23,1,6,'',('2001:2::50',443,0,0))]
        with dns,sockets,tls,patch('socket.getaddrinfo',return_value=mixed):
            result=self.preview('https://research.example/article')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['fields']['title'],'Public article through proxy DNS')
        self.assertEqual(connections,['1.1.1.1','93.184.216.34'])
        self.assertEqual(self.client.get('/api/records').json['total'],0)

    def test_fixed_rss_discovery_uses_the_same_dual_stack_boundary(self):
        from tests.test_discovery import FEED
        token=self.client.post('/api/login',json={'username':'admin','password':'LocalDemo2026!'},
                               headers={'X-CSRF-Token':self.token}).json['csrf']
        source=self.client.post('/api/sources',json={'name':'Synthetic LIIA','kind':'think_tank','website':'https://liia.lv/en/'},
                                headers={'X-CSRF-Token':token}).json['id']
        connections,dns,sockets,tls=self.external_network(question='liia.lv',document=FEED.encode(),mime='application/xml')
        mixed=[(2,1,6,'',('198.18.1.50',443)),(23,1,6,'',('2001:2::50',443,0,0))]
        with dns,sockets,tls,patch('socket.getaddrinfo',return_value=mixed), \
             patch('platform_app.store.now',return_value='2026-10-27T12:00:00+00:00'):
            result=self.client.post('/api/sources/'+source+'/discovery',json={},headers={'X-CSRF-Token':token})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['returned'],2)
        self.assertEqual(connections,['1.1.1.1','93.184.216.34'])
        self.assertEqual(self.client.get('/api/records').json['total'],0)

    def test_private_answers_and_unrelated_dns_replies_never_become_fetch_targets(self):
        for answer,question in [('127.0.0.1','research.example'),('93.184.216.34','unrelated.example')]:
            with self.subTest(answer=answer,question=question):
                connections,dns,sockets,tls=self.external_network(answer,question)
                with dns,sockets,tls:
                    result=self.preview('https://research.example/article')
                self.assertEqual(result.status_code,422,result.json)
                self.assertIn('非公开地址' if answer == '127.0.0.1' else '未能确认',result.json['error'])
                self.assertEqual(connections,['1.1.1.1'])

    def test_explicit_private_addresses_do_not_trigger_external_dns_fallback(self):
        for address,system_ip in [('https://198.18.1.50/','198.18.1.50'),('http://127.0.0.1/','127.0.0.1'),
                                  ('https://research.example/','10.1.2.3')]:
            with self.subTest(address=address,system_ip=system_ip):
                connections,dns,sockets,tls=self.external_network(system_ip=system_ip)
                with dns,sockets,tls:
                    result=self.preview(address)
                self.assertEqual(result.status_code,422,result.json)
                self.assertEqual(connections,[])


if __name__ == '__main__':
    unittest.main()
