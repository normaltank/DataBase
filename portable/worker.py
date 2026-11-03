"""One optional worker owned by the portable server, using the existing queues/gateway."""
from contextlib import closing
import json
from pathlib import Path
import threading
import time

from platform_app import store
from platform_app.worker_service import process_lock


def set_policy(data, settings, *, paused, configure=False):
    """Settings carry no ledger: enabling never resets reservations or unknown fees."""
    value = settings.load()
    with closing(store.connect(Path(data) / 'platform.sqlite3')) as db, db:
        if value and configure:
            db.execute("INSERT OR REPLACE INTO settings VALUES('ai_policy',?)",
                       (json.dumps({'cap': value['cap'], 'currency': 'CNY'}),))
        db.execute("INSERT OR REPLACE INTO settings VALUES('ai_paused',?)", ('1' if paused else '0',))


def prepare_runtime(data, settings):
    import os
    # Defense in depth for callers other than the isolated launcher.
    for key in list(os.environ):
        if key.startswith('DEEPSEEK_'):
            del os.environ[key]
    environment = settings.runtime_environment()
    os.environ.update(environment)
    if not environment:
        with closing(store.connect(Path(data) / 'platform.sqlite3')) as db, db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('ai_paused','1')")
    return bool(environment)


def enforce_local_opt_in(settings):
    """Discard loaded credentials after disable/corruption; in-flight calls keep their snapshot."""
    import os
    if not settings.status()['enabled']:
        for key in list(os.environ):
            if key.startswith('DEEPSEEK_'):
                try:
                    del os.environ[key]
                except KeyError:  # Another Web thread already discarded the same credential.
                    pass
        return False
    return True


def install_runtime_guard(app, settings):
    @app.before_request
    def require_local_opt_in():
        enforce_local_opt_in(settings)


class PortableWorker:
    def __init__(self, data, state, settings, stopping):
        self.data, self.state = Path(data), Path(state)
        self.settings, self.stopping = settings, stopping
        self.thread = None
        self.worker_state = 'not_started'
        self.reason = ''
        self.publish_lock = threading.Lock()
        self.lifecycle_lock = threading.Lock()

    def status(self):
        return self.settings.status() | {'worker_state': self.worker_state, 'worker_reason': self.reason}

    def publish(self):
        # Only safe status fields, never exception text or configuration secrets.
        value = {'worker_state': self.worker_state, 'worker_reason': self.reason,
                 'heartbeat_epoch': time.time()}
        path = self.state / 'worker-status.json'
        temporary = path.with_suffix('.tmp')
        with self.publish_lock:
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)

    def should_stop(self):
        requested = self.stopping.is_set() or not enforce_local_opt_in(self.settings)
        with self.lifecycle_lock:
            if requested and self.worker_state == 'running':
                self.worker_state = 'stopping'
                self.reason = '正在完成当前有界任务及费用结算，不再派发后续任务。'
                self.publish()
        return requested

    def start(self):
        if self.thread is not None:
            raise ValueError('本实例后台已启动。')
        if not self.settings.status()['enabled']:
            self.publish()
            return
        # Fail before launching; a second external worker must never share dispatch.
        self.ownership = process_lock(self.data / '.worker.lock')
        self.ownership.__enter__()
        self.worker_state = 'running'
        self.publish()
        self.thread = threading.Thread(target=self.run, name='portable-maintenance', daemon=False)
        try:
            self.thread.start()
        except BaseException:
            self.ownership.__exit__(None, None, None)
            raise

    def run(self):
        from platform_app.ingestion import run_worker
        try:
            run_worker(self.data, stopping=self.should_stop, heartbeat=self.publish)
            with self.lifecycle_lock:
                self.worker_state = 'stopped'
                self.reason = '后台已停止，队列和费用账本保留。'
        except Exception:
            with self.lifecycle_lock:
                self.worker_state = 'failed'
                self.reason = '后台执行失败，已停止；在维护界面核对任务和费用状态后再启动。'
        finally:
            self.publish()
            self.ownership.__exit__(None, None, None)

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.should_stop()
            # Never kill a worker during transport/settlement. Existing tasks are bounded.
            self.thread.join()
