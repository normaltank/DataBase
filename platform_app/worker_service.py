"""Local process ownership for the existing ingestion CLI; no second scheduler."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import signal
import threading
import time

from . import store


@contextmanager
def process_lock(path):
    """An OS-owned lock is released on crash; never use a PID to kill a process."""
    path = Path(path)
    with path.open('a+b') as handle:
        try:
            # Windows mandatory byte locks also block reads. Inspect the file size
            # without touching the byte owned by a running service.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('This data directory is busy; stop its service first.') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value), encoding='utf-8')
    temp.replace(path)


def read_state(data):
    try:
        return json.loads((data / '.worker-status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def command(action, config):
    data = Path(config['data_dir'])
    if not (data / 'platform.sqlite3').is_file():
        raise ValueError('Initialize administrator before worker use.')
    state = read_state(data)
    if action == 'worker-status':
        # Status never substitutes for checking the independent service manager.
        try:
            with process_lock(data / '.worker.lock'):
                state['process_lock_held'] = False
        except ValueError:
            state['process_lock_held'] = True
        if state.get('state') == 'running' and not state['process_lock_held']:
            state['state'] = 'stale'
        state['heartbeat_recent'] = time.time() - state.get('heartbeat_epoch', 0) < 90
        print(json.dumps(state))
        return
    stop = data / '.worker-stop.json'
    if action == 'worker-stop':
        if state.get('state') == 'running':
            write_json(stop, {'instance': state['instance']})
            print('Stop requested. The current bounded task finishes before exit; check worker-status.')
        else:
            print('No running worker is recorded; check the service manager.')
        return
    from .deployment import configure_logging, default_password_users
    from .ingestion import run_worker
    if default_password_users(data):
        raise ValueError('Replace or disable default demo credentials first.')
    with process_lock(data / '.worker.lock'):
        store.initialize(data, mode='production')
        configure_logging(config['log_dir'], 'worker')
        instance = secrets.token_hex(16)
        stop.unlink(missing_ok=True)
        event = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: event.set())

        def stopping():
            try:
                requested = json.loads(stop.read_text(encoding='utf-8')).get('instance') == instance
            except (OSError, ValueError):
                requested = False
            return event.is_set() or requested

        def heartbeat():
            write_json(data / '.worker-status.json', {'instance': instance, 'pid': os.getpid(),
                'state': 'running', 'heartbeat': store.now(), 'heartbeat_epoch': time.time()})

        try:
            run_worker(data, stopping=stopping, heartbeat=heartbeat)
        finally:
            write_json(data / '.worker-status.json', {'instance': instance, 'state': 'stopped', 'heartbeat': store.now()})
            stop.unlink(missing_ok=True)
