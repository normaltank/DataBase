"""Application-local Windows launcher. No development launcher or worker imports."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
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
        handle.seek(0)
        if not handle.read(1):
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
        return create_app(data)
    if data.exists() and any(data.iterdir()):
        raise RuntimeError('data is nonempty without a database. Preserve it and use a fresh extraction.')
    from portable.demo_seed import seed
    import shutil
    temporary = STATE / ('initializing-' + secrets.token_hex(8))
    try:
        app = create_app(temporary)
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
    return create_app(data)


def serve():
    from werkzeug.serving import make_server
    from werkzeug.wrappers import Response
    with lock('server.lock', timeout=0):
        app = initialize_data()
        app.config['SESSION_COOKIE_NAME'] = 'preview_' + IDENTITY[:24]
        token, instance = secrets.token_hex(32), secrets.token_hex(16)
        server = None

        def application(environ, start_response):
            path = environ.get('PATH_INFO', '')
            if path.startswith('/__portable/'):
                authenticated = secrets.compare_digest(environ.get('HTTP_X_PORTABLE_TOKEN', ''), token)
                method = environ.get('REQUEST_METHOD')
                if not authenticated or (path, method) not in {
                        ('/__portable/status', 'GET'), ('/__portable/stop', 'POST')}:
                    return Response('Not found', status=404)(environ, start_response)
                if path.endswith('/stop'):
                    threading.Thread(target=server.shutdown, daemon=True).start()
                return Response(json.dumps({'identity': IDENTITY, 'instance': instance}),
                                mimetype='application/json')(environ, start_response)
            return app(environ, start_response)

        try:
            preferred = int((STATE / 'last-port').read_text())
        except (OSError, ValueError):
            preferred = 0
        if not 1024 <= preferred <= 65535 or preferred == 8848:
            preferred = 0
        if preferred:
            try:
                server = make_server('127.0.0.1', preferred, application, threaded=True)
            except SystemExit:
                pass
        while server is None:
            candidate = make_server('127.0.0.1', 0, application, threaded=True)
            if candidate.server_port != 8848:
                server = candidate
            else:
                candidate.server_close()
        info = {'identity': IDENTITY, 'instance': instance, 'token': token, 'port': server.server_port}
        (STATE / 'last-port').write_text(str(server.server_port), encoding='ascii')
        write_json(STATE / 'server.json', info)
        try:
            server.serve_forever(poll_interval=.1)
        finally:
            server.server_close()
            if read_state() == info:
                (STATE / 'server.json').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Start or stop this portable copy only.')
    parser.add_argument('action', choices=['start', 'stop', 'status', 'diagnose', '_serve'])
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
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
                         ('Flask', 'Werkzeug', 'Pillow', 'pypdf', 'blinker', 'click', 'itsdangerous', 'Jinja2', 'MarkupSafe', 'colorama')}}, ensure_ascii=False))
        return
    if args.action == '_serve':
        serve()
        return
    with lock('operation.lock'):
        info = read_state()
        active = contact(info)
        if args.action == 'status':
            print(json.dumps({'running': active, 'url': f"http://127.0.0.1:{info['port']}" if active else None}))
            return
        if args.action == 'stop':
            if active:
                if not contact(info, stop=True):
                    raise RuntimeError('Could not stop this instance. No other process was touched.')
                for _ in range(100):
                    if not contact(info):
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('This instance is still stopping; try again.')
            print('This portable copy is stopped. Saved data is retained.')
            return
        if not active:
            with (STATE / 'startup.log').open('w', encoding='utf-8') as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_serve'],
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
        if not args.no_browser:
            os.startfile(url)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Portable preview: {error}', file=sys.stderr)
        sys.exit(1)
