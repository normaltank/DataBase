"""Application-local Windows launcher with an explicitly opted-in existing worker."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import socket
import ipaddress
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.portable'
IDENTITY = hashlib.sha256(str(ROOT).casefold().encode('utf-8')).hexdigest()


def isolated_environment():
    # Read only named Windows essentials, never inspect or print inherited secrets.
    allowed = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    windows = env.get('SYSTEMROOT', r'C:\Windows')
    env.update(PATH=str(Path(windows) / 'System32'), TEMP=str(STATE / 'tmp'),
               TMP=str(STATE / 'tmp'))
    return env


@contextmanager
def lock(name, timeout=120):
    import msvcrt
    path = STATE / name
    with path.open('a+b') as handle:
        # Windows mandatory locks block reads of the owned byte, but not fstat.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('This copy is busy. Wait and try again.')
                time.sleep(.1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def read_state():
    try:
        info = json.loads((STATE / 'server.json').read_text(encoding='utf-8'))
        if (info['identity'] == IDENTITY and type(info['port']) is int
                and 1024 <= info['port'] <= 65535 and info['port'] != 8848
                and isinstance(info['token'], str) and len(info['token']) == 64):
            return info
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def contact(info, stop=False):
    if not info:
        return False
    request = urllib.request.Request(
        f"http://127.0.0.1:{info['port']}/__portable/{'stop' if stop else 'status'}",
        headers={'X-Portable-Token': info['token']}, method='POST' if stop else 'GET')
    try:
        # Explicitly ignore any machine-wide proxy configuration.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
            body = json.load(response)
            return body.get('identity') == IDENTITY and body.get('instance') == info['instance']
    except (OSError, ValueError):
        return False


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def initialize_data():
    from platform_app.web import create_app
    data = ROOT / 'data'
    if (data / 'platform.sqlite3').is_file():
        return create_app(data, embedded_worker=False, portable_trial=True)
    if data.exists() and any(data.iterdir()):
        raise RuntimeError('data is nonempty without a database. Preserve it and use a fresh extraction.')
    from portable.demo_seed import seed
    import shutil
    temporary = STATE / ('initializing-' + secrets.token_hex(8))
    if temporary.resolve().parent != STATE.resolve():
        raise RuntimeError('Initialization path is outside this portable copy.')
    try:
        app = create_app(temporary, embedded_worker=False)
        seed(app)
        # These are migration backups of this just-created synthetic empty DB.
        shutil.rmtree(temporary / 'backups', ignore_errors=True)
        (temporary / '.session-key').unlink(missing_ok=True)
        if data.exists():
            data.rmdir()
        temporary.replace(data)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return create_app(data, embedded_worker=False, portable_trial=True)


def lan_addresses():
    addresses = set()
    for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        value = entry[4][0]
        ip = ipaddress.ip_address(value)
        if not ip.is_loopback and not ip.is_unspecified and not ip.is_link_local:
            addresses.add(value)
    return sorted(addresses)


def lan_config():
    if not (STATE / 'lan.json').exists():
        return {'port': 0}
    try:
        value = json.loads((STATE / 'lan.json').read_text(encoding='utf-8'))
        if type(value['port']) is int and (value['port'] == 0 or 1024 <= value['port'] <= 65535) and value['port'] != 8848:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise RuntimeError('局域网端口设置无效，请运行 lan-configure.bat --port 0 重新设置。')


def serve(mode='local'):
    from waitress.server import create_server
    from waitress import wasyncore
    from werkzeug.wrappers import Response
    with lock('server.lock', timeout=0):
        app = initialize_data()
        from portable.ai_settings import LocalAISettings
        from portable.worker import PortableWorker, prepare_runtime, install_runtime_guard
        settings = LocalAISettings(ROOT)
        prepare_runtime(ROOT / 'data', settings)
        install_runtime_guard(app, settings)
        addresses = lan_addresses() if mode == 'lan' else []
        if mode == 'lan':
            config = lan_config()
            if not addresses:
                raise RuntimeError('尚未找到可用IPv4地址。请连接校园网络后重试。')
        app.config.update(SESSION_COOKIE_NAME='preview_' + IDENTITY[:24],
                          TRUSTED_HOSTS=['127.0.0.1', 'localhost', *addresses],
                          DEMO_LOGIN=False,
                          PRODUCTION_PASSWORD_POLICY=mode == 'lan')
        token, instance = secrets.token_hex(32), secrets.token_hex(16)
        stopping = threading.Event()
        worker = PortableWorker(ROOT / 'data', STATE, settings, stopping)
        app.config['PORTABLE_AI_STATUS'] = worker.status

        def application(environ, start_response):
            path = environ.get('PATH_INFO', '')
            if path.startswith('/__portable/'):
                authenticated = (environ.get('REMOTE_ADDR') in {'127.0.0.1', '::1'} and
                    secrets.compare_digest(environ.get('HTTP_X_PORTABLE_TOKEN', ''), token))
                method = environ.get('REQUEST_METHOD')
                if not authenticated or (path, method) not in {
                        ('/__portable/status', 'GET'), ('/__portable/stop', 'POST')}:
                    return Response('Not found', status=404)(environ, start_response)
                if path.endswith('/stop'):
                    stopping.set()
                return Response(json.dumps({'identity': IDENTITY, 'instance': instance}),
                                mimetype='application/json')(environ, start_response)
            # LAN uses direct HTTP; no forwarded headers or trusted proxy are accepted.
            if any(k.startswith('HTTP_X_FORWARDED_') or k == 'HTTP_FORWARDED' for k in environ):
                return Response('Untrusted forwarding headers', status=400)(environ, start_response)
            return app(environ, start_response)

        try:
            preferred = int((STATE / ('last-port-' + mode)).read_text())
        except (OSError, ValueError):
            preferred = 0
        if mode == 'lan' and config['port'] and not preferred:
            preferred = config['port']
        if not 1024 <= preferred <= 65535 or preferred == 8848:
            preferred = 0
        server = None
        for port in [preferred, 0] if preferred else [0]:
            try:
                server = create_server(application, host='0.0.0.0' if mode == 'lan' else '127.0.0.1',
                    port=port, threads=6, clear_untrusted_proxy_headers=False, asyncore_loop_timeout=.1)
                break
            except OSError:
                continue
        if server is None:
            raise RuntimeError('Unable to bind an available port.')
        while server.effective_port == '8848':
            server.close()
            server = create_server(application, host='0.0.0.0' if mode == 'lan' else '127.0.0.1', port=0)
        port = int(server.effective_port)
        info = {'identity': IDENTITY, 'instance': instance, 'token': token, 'port': port, 'mode': mode,
                'urls': [f'http://{address}:{port}' for address in addresses]}
        (STATE / ('last-port-' + mode)).write_text(str(port), encoding='ascii')
        write_json(STATE / 'server.json', info)
        try:
            worker.start()
        except Exception:
            server.close()
            (STATE / 'server.json').unlink(missing_ok=True)
            raise
        runner = threading.Thread(target=server.run, daemon=True)
        runner.start()
        try:
            while runner.is_alive() and not stopping.wait(.2):
                pass
        finally:
            stopping.set()
            worker.stop()  # settle in-flight provider work before releasing this copy's lock
            time.sleep(.2)  # let the authenticated stop response flush
            server.task_dispatcher.shutdown(timeout=5)
            server.close()
            wasyncore.close_all(map=server._map)
            runner.join(timeout=2)
            if read_state() == info:
                (STATE / 'server.json').unlink(missing_ok=True)


def prompt_admin_password(password_stdin=False):
    """Read a new password at the terminal boundary, with unmistakable feedback."""
    import getpass
    from portable.terminal import hidden_input
    from platform_app.deployment import validate_password
    print('设置管理员口令：12—200字符。键入时不会显示字符或星号，并非卡住；输入后按回车。', flush=True)
    print('按 Ctrl+C 取消；不会显示或记录口令。', flush=True)
    while True:
        try:
            def read(prompt):
                if not password_stdin:
                    return hidden_input(prompt)
                value = sys.stdin.readline()
                if not value:
                    raise EOFError
                return value.rstrip('\r\n')
            password = read('新管理员口令：')
            try:
                validate_password(password)
            except ValueError:
                print('口令无效：请使用12—200字符的新口令，不能使用公开演示口令。请重试。', flush=True)
                continue
            print('已收到新口令，请再次输入确认（仍为隐藏输入）。', flush=True)
            repeated = read('再次输入口令：')
            if password != repeated:
                print('两次口令不一致，请重新输入。', flush=True)
                continue
            print('口令确认一致，正在保存设置……', flush=True)
            return password
        except (KeyboardInterrupt, EOFError):
            print('\n已取消口令设置；现有账号和口令未改变。', flush=True)
            return None


def main():
    parser = argparse.ArgumentParser(description='Start or stop this portable copy only.')
    parser.add_argument('action', choices=['start', 'lan-start', 'lan-configure', 'stop', 'status', 'diagnose', 'ai-configure', 'ai-enable', 'ai-disable', '_serve'])
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--mode', choices=['local', 'lan'], default='local')
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--password-stdin', action='store_true', help='Explicit private pipe for automated configuration only.')
    args = parser.parse_args()
    # Windows console uses its native Unicode interface; redirected logs remain UTF-8.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    STATE.mkdir(exist_ok=True)
    (STATE / 'tmp').mkdir(exist_ok=True)
    env = isolated_environment()
    os.environ.clear()
    os.environ.update(env)
    sys.dont_write_bytecode = True
    if args.action == 'diagnose':
        import flask
        import pypdf
        from PIL import Image, _imaging
        import importlib.metadata
        print(json.dumps({'executable': sys.executable, 'isolated': sys.flags.isolated,
            'paths': sys.path, 'environment_keys': sorted(os.environ),
            'modules': [flask.__file__, pypdf.__file__, Image.__file__, _imaging.__file__],
            'versions': {name: importlib.metadata.version(name) for name in
                         ('Flask', 'Werkzeug', 'Pillow', 'pypdf', 'waitress', 'blinker', 'click', 'itsdangerous', 'Jinja2', 'MarkupSafe')}}, ensure_ascii=False))
        return
    if args.action == '_serve':
        serve(args.mode)
        return
    with lock('operation.lock'):
        info = read_state()
        active = contact(info)
        mode = 'lan' if args.action == 'lan-start' else 'local'
        if args.action.startswith('ai-'):
            from portable.ai_settings import LocalAISettings
            from portable.ai_configure import prompt_configuration, enable, disable
            settings = LocalAISettings(ROOT)
            if args.action != 'ai-disable' and active:
                raise RuntimeError('请先运行 stop.bat 停止本副本，再配置或启用AI。')
            initialize_data()
            if args.action == 'ai-configure':
                prompt_configuration(settings, ROOT / 'data')
            elif args.action == 'ai-enable':
                enable(settings, ROOT / 'data')
            else:
                disable(settings, ROOT / 'data')
            return
        if args.action == 'lan-configure':
            if active:
                raise RuntimeError('请先运行 stop.bat 停止本副本，再调整局域网设置。')
            if args.port is not None and args.port != 0 and (not 1024 <= args.port <= 65535 or args.port == 8848):
                raise RuntimeError('端口请选择1024—65535且避开8848，或用0自动选择。')
            initialize_data()
            config = lan_config() if args.port is None else {'port': args.port}
            write_json(STATE / 'lan.json', config)
            if args.port is not None:
                (STATE / 'last-port-lan').unlink(missing_ok=True)
            print('局域网试用无需账号口令。已有账号、口令、停用状态和资料保持；端口已保存。请用 lan-start.bat 启动。')
            return
        if args.action == 'status':
            from portable.ai_settings import LocalAISettings
            ai = LocalAISettings(ROOT).status()
            ai['worker_state'] = 'stopped'
            if active:
                try:
                    ai.update(json.loads((STATE / 'worker-status.json').read_text(encoding='utf-8')))
                except (OSError, ValueError):
                    ai['worker_state'] = 'not_started'
            print(json.dumps({'running': active, 'portable_ai': ai, 'mode': info.get('mode') if active else None, 'urls': info.get('urls', []) if active else [], 'url': f"http://127.0.0.1:{info['port']}" if active else None}))
            return
        if args.action == 'stop':
            if active:
                if not contact(info, stop=True):
                    raise RuntimeError('Could not stop this instance. No other process was touched.')
                print('正在停止本副本，等待当前任务与费用结算；请保留窗口……', flush=True)
                for _ in range(1800):
                    if not contact(info):
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('This instance is still stopping; try again.')
            with lock('server.lock', timeout=180):
                pass
            print('This portable copy is stopped. Saved data is retained.')
            return
        if active and info.get('mode', 'local') != mode:
            raise RuntimeError('This copy is running in another mode. Use stop.bat before switching modes.')
        if mode == 'lan':
            lan_config()
        if not active:
            with (STATE / 'startup.log').open('w', encoding='utf-8') as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_serve', '--mode', mode],
                    cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(1200):
                info = read_state()
                if contact(info):
                    break
                if child.poll() is not None:
                    raise RuntimeError('Startup failed. See .portable/startup.log; use a writable extracted folder.')
                time.sleep(.1)
            else:
                raise RuntimeError('Startup is taking longer than expected. See .portable/startup.log.')
        url = f"http://127.0.0.1:{info['port']}"
        print(url)
        if mode == 'lan':
            print('LAN trial addresses (same reachable campus network):')
            for address in info.get('urls', []):
                print(address)
            print('Keep this computer awake. See 使用说明.html for restricted firewall instructions.')
        if not args.no_browser:
            os.startfile(url)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Portable preview: {error}', file=sys.stderr)
        sys.exit(1)
