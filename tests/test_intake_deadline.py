"""Whole-acquisition deadlines through authenticated HTTP and synthetic sockets."""
import io
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from platform_app.web import create_app


class SlowReader(io.BytesIO):
    def __init__(self, transport):
        super().__init__(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<meta name="citation_title" content="Late">')
        self.transport = transport

    def readline(self, *args):
        self.transport.stage_entered.set()
        # Keep each read below the configured inactivity timeout while the
        # complete header exceeds the acquisition budget. shutdown interrupts
        # this makefile even after HTTPConnection has closed its own reference.
        for _ in range(6):
            if self.transport.interrupted.wait(.025):
                raise OSError('connection shut down')
        return super().readline(*args)


class SlowSocket:
    def __init__(self, peer='93.184.216.34'):
        self.peer = peer
        self.interrupted = threading.Event()
        self.closed = False
        self.reader = None
        self.stage_entered = threading.Event()

    def getpeername(self):
        return (self.peer, 443)

    def settimeout(self, timeout):
        pass

    def setsockopt(self, *args):
        pass

    def sendall(self, data):
        pass

    def makefile(self, *args, **kwargs):
        self.reader = SlowReader(self)
        return self.reader

    def shutdown(self, how):
        self.interrupted.set()

    def close(self):
        self.closed = True


class SlowHandshakeSocket(SlowSocket):
    def do_handshake(self):
        self.stage_entered.set()
        if self.interrupted.wait(.6):
            raise OSError('TLS handshake interrupted')


class SlowBodyReader(io.BytesIO):
    def __init__(self, transport):
        super().__init__(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n')
        self.transport = transport

    def read1(self, *args):
        self.transport.stage_entered.set()
        self.transport.interrupted.wait(.6)
        # A real shutdown can end a read with EOF rather than an exception.
        return b''


class SlowBodySocket(SlowSocket):
    def makefile(self, *args, **kwargs):
        self.reader = SlowBodyReader(self)
        return self.reader


class IntakeDeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Windows loads its system certificate store here. That startup cost
        # is outside the synthetic 100ms network budget under test.
        cls.ssl_context = ssl.create_default_context()
        cls.temp = tempfile.TemporaryDirectory(prefix='intake-deadline-')
        cls.app = create_app(Path(cls.temp.name), testing=True)
        cls.client = cls.app.test_client()
        csrf = cls.client.get('/api/session').json['csrf']
        cls.csrf = cls.client.post('/api/login', json={'username':'researcher', 'password':'LocalDemo2026!'},
                                   headers={'X-CSRF-Token':csrf}).json['csrf']

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def preview(self, value='https://research.example/article'):
        return self.client.post('/api/intake/preview', json={'input':value}, headers={'X-CSRF-Token':self.csrf})

    def test_slow_headers_obey_total_deadline_and_release_request_capacity(self):
        sockets = []
        def connect(*args, **kwargs):
            transport = SlowSocket()
            sockets.append(transport)
            return transport
        with patch('platform_app.intake.MAX_SECONDS', .10), \
             patch('ssl.create_default_context', return_value=self.ssl_context), \
             patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443))]), \
             patch('socket.create_connection', side_effect=connect), \
             patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **kwargs:sock):
            # More than the four request slots also verifies every timeout
            # returns its capacity rather than leaving a hanging request.
            for _ in range(5):
                started = time.monotonic()
                result = self.preview()
                self.assertEqual(result.status_code, 422, result.json)
                self.assertIn('超时', result.json['error'])
                self.assertLess(time.monotonic() - started, .35)
        self.assertEqual(len(sockets), 5)
        for transport in sockets:
            self.assertTrue(transport.stage_entered.is_set(), 'slow response headers were not reached')
            self.assertIsNotNone(transport.reader)
            self.assertTrue(transport.interrupted.is_set() and transport.closed)
            self.assertTrue(transport.reader.closed)

    def test_tls_handshake_and_detached_body_are_interrupted(self):
        for transport_type in (SlowHandshakeSocket, SlowBodySocket):
            with self.subTest(stage=transport_type.__name__):
                transport = transport_type()
                with patch('platform_app.intake.MAX_SECONDS', .10), \
                     patch('ssl.create_default_context', return_value=self.ssl_context), \
                     patch('socket.getaddrinfo', return_value=[(2,1,6,'',('93.184.216.34',443))]), \
                     patch('socket.create_connection', return_value=transport), \
                     patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **kwargs:sock):
                    started = time.monotonic()
                    result = self.preview()
                    self.assertEqual(result.status_code, 422, result.json)
                    self.assertIn('超时', result.json['error'])
                    self.assertLess(time.monotonic() - started, .35)
                self.assertTrue(transport.interrupted.is_set() and transport.closed)
                self.assertTrue(transport.stage_entered.is_set(), 'intended TLS/body stage was not reached')
                if transport_type is SlowBodySocket:
                    self.assertIsNotNone(transport.reader)
                    self.assertTrue(transport.reader.closed)

    def test_proxy_dns_slow_headers_use_the_same_acquisition_deadline(self):
        transport = SlowSocket('1.1.1.1')
        with patch('platform_app.intake.MAX_SECONDS', .10), \
             patch('ssl.create_default_context', return_value=self.ssl_context), \
             patch('socket.getaddrinfo', return_value=[(2,1,6,'',('198.18.1.50',443))]), \
             patch('socket.create_connection', return_value=transport), \
             patch('ssl.SSLContext.wrap_socket', side_effect=lambda sock, **kwargs:sock):
            started = time.monotonic()
            result = self.preview()
            self.assertEqual(result.status_code, 422, result.json)
            self.assertIn('超时', result.json['error'])
            self.assertLess(time.monotonic() - started, .35)
        self.assertTrue(transport.interrupted.is_set() and transport.closed)
        self.assertTrue(transport.stage_entered.is_set(), 'slow DoH response headers were not reached')
        self.assertIsNotNone(transport.reader)
        self.assertTrue(transport.reader.closed)


if __name__ == '__main__':
    unittest.main()
