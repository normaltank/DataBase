"""One deadline for urllib DNS, proxy tunnel, TLS, headers and response body.

Keep urllib's proxy selection, certificate context and HTTP error handling.
Only connection creation/handshake are adapted so the deadline can interrupt
the actual socket even when HTTPResponse's makefile still owns it.
"""
import http.client
import queue
import socket
import threading
import time
import urllib.request


# getaddrinfo has no cancellation API. Expired lookups keep their slot until
# they exit; no late lookup may connect, and repeated failures cannot leak
# an unbounded number of resolver threads.
_dns_slots = threading.BoundedSemaphore(2)


class Deadline:
    def __init__(self, seconds):
        self.until = time.monotonic() + seconds
        self.expired = threading.Event()
        self.lock = threading.Lock()
        self.sockets = []
        self.timer = threading.Timer(seconds, self.interrupt)
        self.timer.daemon = True

    def remaining(self):
        left = self.until - time.monotonic()
        if left <= 0 or self.expired.is_set():
            raise TimeoutError('AI transport deadline exceeded')
        return left

    def interrupt(self):
        self.expired.set()
        with self.lock:
            for transport in self.sockets:
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def track(self, transport):
        with self.lock:
            self.sockets.append(transport)
            try:
                self.remaining()
            except TimeoutError:
                transport.close()
                raise
        return transport

    def addresses(self, host, port):
        self.remaining()
        if not _dns_slots.acquire(blocking=False):
            raise TimeoutError('AI resolver capacity exhausted')
        result = queue.Queue(maxsize=1)

        def lookup():
            try:
                result.put(socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM))
            except OSError as error:
                result.put(error)
            finally:
                _dns_slots.release()

        threading.Thread(target=lookup, daemon=True, name='ai-dns').start()
        try:
            value = result.get(timeout=self.remaining())
        except queue.Empty:
            raise TimeoutError('AI DNS deadline exceeded') from None
        self.remaining()
        if isinstance(value, OSError):
            raise value
        return value

    def connect(self, address, timeout=None, source_address=None):
        last_error = None
        for family, kind, proto, _, target in self.addresses(*address):
            transport = self.track(socket.socket(family, kind, proto))
            try:
                transport.settimeout(self.remaining())
                if source_address:
                    transport.bind(source_address)
                transport.connect(target)
                self.remaining()
                return transport
            except OSError as error:
                transport.close()
                last_error = error
                self.remaining()
        raise last_error or OSError('AI host has no addresses')

    def __enter__(self):
        self.timer.start()
        return self

    def __exit__(self, *args):
        self.timer.cancel()
        self.timer.join()
        for transport in self.sockets:
            transport.close()

    def handlers(self):
        deadline = self

        class HTTPConnection(http.client.HTTPConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._create_connection = deadline.connect

        class HTTPSConnection(http.client.HTTPSConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._create_connection = deadline.connect

            def connect(self):
                http.client.HTTPConnection.connect(self)
                self.sock.settimeout(deadline.remaining())
                self.sock = deadline.track(self._context.wrap_socket(
                    self.sock, server_hostname=self._tunnel_host or self.host,
                    do_handshake_on_connect=False))
                self.sock.settimeout(deadline.remaining())
                handshake = getattr(self.sock, 'do_handshake', None)
                if handshake:
                    handshake()
                deadline.remaining()

        class HTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, req):
                return self.do_open(HTTPConnection, req)

        class HTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(HTTPSConnection, req, context=self._context)

        return HTTPHandler(), HTTPSHandler()
