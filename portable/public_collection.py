"""Per-user, per-extraction public collection permission, outside business backups."""
import hashlib
import json
from pathlib import Path
import threading

from .ai_settings import user_storage


class LocalPublicSettings:
    def __init__(self, root, *, storage_root=None):
        identity = hashlib.sha256(str(Path(root).resolve()).casefold().encode('utf-8')).hexdigest()
        self.path = (Path(storage_root) if storage_root is not None else user_storage()) / identity / 'public-collection.json'
        self.lock = threading.Lock()

    def status(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            self.validate(value)
            return value
        except (OSError, ValueError, TypeError):
            return dict(version=1, enabled=False, source_ids=[])

    @staticmethod
    def validate(value):
        if (not isinstance(value, dict) or set(value) != {'version','enabled','source_ids'} or value['version'] != 1
                or type(value['enabled']) is not bool or not isinstance(value['source_ids'], list)
                or len(value['source_ids']) > 3 or not all(isinstance(s, str) and 1<=len(s)<=200 for s in value['source_ids'])
                or len(set(value['source_ids'])) != len(value['source_ids']) or value['enabled'] and not value['source_ids']):
            raise ValueError('请明确选择一至三个已登记期刊，然后开启本机公开采集。')

    def configure(self, enabled, source_ids):
        value = dict(version=1, enabled=enabled, source_ids=source_ids)
        self.validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)
        return self.status()


def install_public_control(app, worker):
    app.config['PUBLIC_COLLECTION_STATUS'] = worker.public_status
    def configure(enabled, source_ids):
        worker.public_settings.configure(enabled, source_ids)
        worker.ensure_started()
        return worker.public_status()
    app.config['PUBLIC_COLLECTION_CONFIGURE'] = configure
