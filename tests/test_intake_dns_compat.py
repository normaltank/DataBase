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

    def external_network(self, answer='93.184.216.34', question='research.example', system_ip='198.18.1.50'):
        connections=[]
        def connect(address, *args, **kwargs):
            host=address[0]
            connections.append(host)
            if host == '1.1.1.1':
                payload=json.dumps({'Status':0,'Question':[{'name':question,'type':1}],
                                    'Answer':[{'name':question,'type':1,'TTL':60,'data':answer}]}).encode()
                return RemoteSocket(host,payload,'application/dns-json')
            if host == '93.184.216.34':
                return RemoteSocket(host,b'<meta name="citation_title" content="Public article through proxy DNS">','text/html','research.example')
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
