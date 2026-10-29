"""Deadline outcomes through authenticated HTTP and a real loopback supplier."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from tests import test_ai_budget as budget


class AIDeadlineTests(unittest.TestCase):
    setUp = budget.AIBudgetTests.setUp
    login = budget.AIBudgetTests.login
    call = budget.AIBudgetTests.call
    get = budget.AIBudgetTests.get
    record = budget.AIBudgetTests.record
    detail = budget.AIBudgetTests.detail
    synthetic = budget.AIBudgetTests.synthetic
    run_job = budget.AIBudgetTests.run_job

    def test_slow_drip_expires_retains_hold_and_never_settles_late(self):
        self.synthetic()
        stopped = threading.Event()

        class Drip(BaseHTTPRequestHandler):
            received = 0

            def log_message(self, *args):
                pass

            def do_POST(self):
                type(self).received += 1
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.end_headers()
                try:
                    while not stopped.wait(.03):
                        self.wfile.write(b' ')
                        self.wfile.flush()
                except OSError:
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Drip)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(stopped.set)
        rid = self.record(title='Deadline synthetic original')
        started = time.monotonic()
        with patch.dict('os.environ', {'DEEPSEEK_BASE_URL': f'https://127.0.0.1:{server.server_port}'}), patch('platform_app.ai_gateway.MAX_SECONDS', .25, create=True):
            # The fallback stop lets the red test finish on the unfixed gateway.
            timer = threading.Timer(1.5, stopped.set)
            timer.start()
            try:
                result = self.run_job(rid)
            finally:
                timer.cancel()
                timer.join()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertEqual(result.json['status'], 'failed')
        state = self.get('/api/admin/ai', 'admin').json
        self.assertEqual(state['attempts'][0]['status'], 'unknown')
        self.assertGreater(state['held_units'], 0)
        held = state['held_units']
        time.sleep(.1)
        self.assertEqual(self.run_job(rid, 'deadline-no-resend').json['status'], 'failed')
        state = self.get('/api/admin/ai', 'admin').json
        self.assertEqual(state['held_units'], held)
        self.assertEqual(state['attempts'][0]['status'], 'unknown')
        self.assertEqual(Drip.received, 1)

    def test_delayed_headers_late_success_and_oversize_stay_unknown(self):
        self.synthetic()
        release = threading.Event()

        class Supplier(BaseHTTPRequestHandler):
            mode = 'headers'

            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                raw = json.dumps({'model': 'deepseek-flash', 'usage': {'prompt_tokens': 23, 'completion_tokens': 7, 'total_tokens': 30}, 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"title":"valid late result","abstract":""}'}}]}).encode()
                try:
                    if self.mode == 'headers':
                        release.wait(2)
                    if self.mode == 'size':
                        raw += b' ' * (256 * 1024)
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    if self.mode == 'late':
                        self.wfile.write(raw[:1])
                        self.wfile.flush()
                        release.wait(2)
                        raw = raw[1:]
                    self.wfile.write(raw)
                except OSError:
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Supplier)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)
        for mode in ('headers', 'late', 'size'):
            Supplier.mode = mode
            release.clear()
            rid = self.record(title='Synthetic ' + mode)
            start = time.monotonic()
            with patch.dict('os.environ', {'DEEPSEEK_BASE_URL': f'https://127.0.0.1:{server.server_port}'}), patch('platform_app.ai_gateway.MAX_SECONDS', .25):
                result = self.run_job(rid, 'deadline-' + mode)
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(result.json['status'], 'failed')
            state = self.get('/api/admin/ai', 'admin').json
            self.assertEqual(state['attempts'][0]['status'], 'unknown')
            self.assertEqual(state['charged_units'], 0)
            self.assertGreater(state['held_units'], 0)
            release.set()
            # A late valid body cannot turn this completed failure into success.
            time.sleep(.05)
            self.assertEqual(self.get('/api/admin/ai', 'admin').json['attempts'][0]['status'], 'unknown')
            self.call('/api/admin/ai/attempts/' + state['attempts'][0]['id'] + '/resolve', {'charged': '0', 'basis': 'Synthetic supplier invoice confirms zero'}, user='admin')

    def test_expired_dns_lookup_cannot_send_late_or_spawn_unbounded_resolvers(self):
        self.synthetic()
        import socket
        import ssl
        # This case measures blocked DNS, not platform certificate-store loading.
        # Keep the short transport deadline, with HTTPS setup ready beforehand.
        context = ssl._create_default_https_context()
        release = threading.Event()
        lookups = threading.Condition()
        real_lookup = socket.getaddrinfo
        entered = []
        resolvers = []

        def delayed(*args, **kwargs):
            with lookups:
                entered.append(args)
                resolvers.append(threading.current_thread())
                lookups.notify_all()
            release.wait()
            return real_lookup(*args, **kwargs)

        try:
            with patch('ssl._create_default_https_context', return_value=context), patch('socket.getaddrinfo', side_effect=delayed), patch('platform_app.ai_gateway.MAX_SECONDS', .1):
                for index in range(3):
                    result = self.run_job(self.record(title='DNS synthetic ' + str(index)), 'dns-' + str(index))
                    self.assertEqual(result.json['status'], 'failed')
                    if index < 2:
                        with lookups:
                            self.assertTrue(lookups.wait_for(lambda: len(entered) == index + 1, timeout=2), 'Request must reach the blocked DNS fixture')
                    state = self.get('/api/admin/ai', 'admin').json
                    self.assertEqual(state['attempts'][0]['status'], 'unknown')
                    self.call('/api/admin/ai/attempts/' + state['attempts'][0]['id'] + '/resolve', {'charged': '0', 'basis': 'Synthetic DNS fixture confirms no supplier request'}, user='admin')
                self.assertEqual(len(entered), 2)
                self.assertEqual(budget.Provider.requests, [])
        finally:
            release.set()
            for thread in resolvers:
                thread.join(2)
        for thread in resolvers:
            self.assertFalse(thread.is_alive(), 'Released resolver must return its slot')
        self.assertEqual(budget.Provider.requests, [])
        self.assertEqual(self.run_job(self.record(title='DNS recovered'), 'dns-recovered').json['status'], 'succeeded')

    def test_tls_handshake_wait_is_inside_deadline(self):
        import socketserver
        release, accepted = threading.Event(), threading.Event()

        class WaitingTLS(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(65536)  # Real ClientHello, deliberately no ServerHello.
                accepted.set()
                release.wait(2)

        server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), WaitingTLS)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)
        self.call('/api/admin/ai/config', {'cap': '1', 'currency': 'USD'}, user='admin')
        rid = self.record(title='Waiting TLS synthetic')
        env = {'DEEPSEEK_API_KEY': 'synthetic-only', 'DEEPSEEK_BASE_URL': f'https://127.0.0.1:{server.server_address[1]}', 'DEEPSEEK_MODEL': 'deepseek-flash', 'DEEPSEEK_PRICING_JSON': json.dumps(budget.PRICE)}
        started = time.monotonic()
        with patch.dict('os.environ', env), patch('platform_app.ai_gateway.MAX_SECONDS', .25):
            result = self.run_job(rid)
        self.assertTrue(accepted.is_set())
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(result.json['status'], 'failed')
        state = self.get('/api/admin/ai', 'admin').json
        self.assertEqual(state['attempts'][0]['status'], 'unknown')
        self.assertGreater(state['held_units'], 0)
