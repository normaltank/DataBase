"""Resolve proxy Fake-IP aliases to real addresses before the public-only fetch.

Some desktop proxies return 198.18.0.0/15 aliases, paired with 2001:2::/48.
The paired pattern only triggers a public DNS recheck, never trust in aliases.
These aliases never become connection targets. A fixed HTTPS DNS endpoint
supplies real addresses, which the caller must validate and pin as usual.
"""
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
from urllib.parse import quote


PROXY_ALIAS_RANGE = ipaddress.ip_network('198.18.0.0/15')
PAIRED_BENCHMARK_RANGE = ipaddress.ip_network('2001:2::/48')
DNS_BOOTSTRAP = '1.1.1.1'
MAX_RESPONSE = 65536


class DeadlineConnection(http.client.HTTPConnection):
    """Pin a connection and interrupt all socket reads at one absolute deadline.

    Keep the transport separately: HTTPConnection may drop its socket while an
    HTTPResponse's makefile still owns it. close alone cannot interrupt that read.
    The caller must finish() after closing its response, including on redirects.
    """
    def __init__(self, host, port, ip, secure, deadline):
        self.default_port = 443 if secure else 80
        super().__init__(host, port, timeout=max(.001, deadline - time.monotonic()))
        self.ip, self.secure, self.deadline = ip, secure, deadline
        self._transport = None
        self._timer = None
        self._expired = threading.Event()
        self._transport_lock = threading.Lock()

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self._expired.is_set():
            raise TimeoutError('acquisition deadline exceeded')
        return remaining

    def _interrupt(self):
        self._expired.set()
        with self._transport_lock:
            transport = self._transport
            if transport:
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _track(self, transport):
        with self._transport_lock:
            self._transport = transport
        self.remaining()

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.remaining())
        self._track(self.sock)
        if ipaddress.ip_address(self.sock.getpeername()[0]) != ipaddress.ip_address(self.ip):
            raise ValueError('站点连接目标不安全，已停止提取。')
        self._timer = threading.Timer(self.remaining(), self._interrupt)
        self._timer.daemon = True
        self._timer.start()
        if self.secure:
            self.sock.settimeout(self.remaining())
            # Register the SSL socket before starting its blocking handshake.
            self.sock = ssl.create_default_context().wrap_socket(
                self.sock, server_hostname=self.host, do_handshake_on_connect=False)
            self._track(self.sock)
            self.sock.settimeout(self.remaining())
            handshake = getattr(self.sock, 'do_handshake', None)
            if handshake:
                handshake()
        self.sock.settimeout(self.remaining())

    def finish(self):
        if self._timer:
            self._timer.cancel()
            self._timer.join()
        self.close()
        if self._transport:
            self._transport.close()


def resolve_proxy_alias(host, system_addresses, deadline):
    """Recheck only IPv4 aliases and their bounded dual-stack candidate pattern."""
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    addresses = [ipaddress.ip_address(value) for value in system_addresses]
    if not any(address in PROXY_ALIAS_RANGE for address in addresses) or any(
            address not in PROXY_ALIAS_RANGE and address not in PAIRED_BENCHMARK_RANGE
            for address in addresses):
        return None
    name = host.encode('idna').decode('ascii').rstrip('.').lower()
    if '.' not in name or any(not label or len(label) > 63 for label in name.split('.')):
        raise ValueError('不能为此站点取得公开网络地址，请继续手填。')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('解析站点超时，请继续手填。')
    connection = DeadlineConnection(DNS_BOOTSTRAP, 443, DNS_BOOTSTRAP, True, deadline)
    response = None
    try:
        # Numeric bootstrap and normal TLS certificate verification avoid a
        # dependency on the very system DNS answer being replaced.
        connection.connect()
        if ipaddress.ip_address(connection.sock.getpeername()[0]) != ipaddress.ip_address(DNS_BOOTSTRAP):
            raise ValueError('公开解析服务连接目标不符，请继续手填。')
        connection.request('GET', '/dns-query?name=' + quote(name, safe='') + '&type=A',
                           headers={'Host': 'cloudflare-dns.com', 'Accept': 'application/dns-json', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        connection.remaining()
        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0].strip() not in {'application/dns-json', 'application/json'}:
            raise ValueError('公开解析服务暂不可用，请稍后重试或继续手填。')
        chunks, size = [], 0
        while size <= MAX_RESPONSE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('解析站点超时，请继续手填。')
            if connection.sock:
                connection.sock.settimeout(min(5, remaining))
            chunk = response.read1(min(8192, MAX_RESPONSE + 1 - size))
            connection.remaining()
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_RESPONSE:
            raise ValueError('公开解析服务响应过大，请继续手填。')
        result = json.loads(b''.join(chunks))
        questions = result.get('Question', [])
        if result.get('Status') != 0 or result.get('TC') or not any(
                item.get('type') == 1 and str(item.get('name', '')).rstrip('.').lower() == name for item in questions):
            raise ValueError('未能确认站点的公开网络地址，请继续手填。')
        answers = result.get('Answer', [])
        accepted_names = {name}
        for _ in range(8):
            added = {str(item.get('data', '')).rstrip('.').lower() for item in answers
                     if item.get('type') == 5 and str(item.get('name', '')).rstrip('.').lower() in accepted_names}
            if added <= accepted_names:
                break
            accepted_names.update(added)
        addresses = list(dict.fromkeys(str(item.get('data', '')) for item in answers
                        if item.get('type') == 1 and str(item.get('name', '')).rstrip('.').lower() in accepted_names))
        if not addresses:
            raise ValueError('此代理环境下未取得站点的公开 IPv4 地址，请继续手填。')
        # The fetch boundary repeats public-address validation. Validate the
        # entire reply here as well, so no private alternate is silently used.
        for value in addresses:
            address = ipaddress.ip_address(value)
            if address.version != 4 or not address.is_global or address.is_multicast or address.is_reserved:
                raise ValueError('站点解析包含非公开地址，已停止提取。')
        return addresses
    except (OSError, http.client.HTTPException, UnicodeError, json.JSONDecodeError, TypeError, AttributeError) as error:
        raise ValueError('公开解析服务连接失败、超时或响应无效，请稍后重试或继续手填。') from error
    finally:
        if response:
            response.close()
        connection.finish()
