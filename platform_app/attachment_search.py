"""Disposable attachment text cache; callers supply currently authorized records."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .store import now
from .search import normalize
from .workflow import snippet

VERSION = 1
TIMEOUT = 12
MAX_BYTES = 10 * 1024 * 1024
STATUSES = {
    'unindexed': '尚未建立索引', 'ready': '已建立文字索引',
    'empty': '无可提取文字（不支持 OCR）', 'unsupported': '格式不支持',
    'limit': '超过索引处理限制', 'failed': '文字提取失败',
    'missing': '原附件文件缺失',
}


def original_path(data_dir, attachment):
    stored = attachment['stored_name']
    if not re.fullmatch(r'[a-f0-9]{32}\.[a-z0-9]+', stored):
        return None
    path = Path(data_dir) / 'uploads' / stored
    return path if path.is_file() and not path.is_symlink() else None


def status(code, **extra):
    return {'status': code, 'message': STATUSES[code], **extra}


class AttachmentIndex:
    def __init__(self, db, data_dir):
        self.db = db
        self.data_dir = Path(data_dir)
        self.directory = self.data_dir / 'attachment-index'
        self.loaded = {}
        self.prefetched = None

    def current(self, record):
        ids = json.loads(record['attachment_ids'])
        rows = self.prefetched.get(record['id'], []) if self.prefetched is not None else self.db.execute('SELECT * FROM attachments WHERE record_id=?', (record['id'],))
        return [dict(a) for a in rows if a['id'] in ids]

    def _cache_path(self, attachment):
        # Never interpret a database identifier as a filesystem path.
        key = hashlib.sha256(attachment['id'].encode()).hexdigest()
        return self.directory / (key + '.json')

    def read(self, attachment):
        path = original_path(self.data_dir, attachment)
        if path is None:
            return status('missing', segments=[])
        stat = path.stat()
        stamp = [stat.st_size, stat.st_mtime_ns]
        if attachment['id'] in self.loaded:
            return self.loaded[attachment['id']]
        result = status('unindexed', segments=[])
        try:
            cached = self._cache_path(attachment)
            if cached.stat().st_size <= 8 * 1024 * 1024:
                value = json.loads(cached.read_text(encoding='utf-8'))
                if (isinstance(value, dict) and value.get('version') == VERSION
                        and value.get('sha256') == attachment['sha256'] and value.get('stamp') == stamp
                        and value.get('status') in STATUSES and isinstance(value.get('message'), str)
                        and isinstance(value.get('segments'), list)
                        and all(isinstance(segment, dict) and isinstance(segment.get('text'), str)
                                and isinstance(segment.get('locator'), str) for segment in value['segments'])):
                    result = value
        except (OSError, ValueError, TypeError):
            pass
        self.loaded[attachment['id']] = result
        return result

    def info(self, attachment):
        result = self.read(attachment)
        return {k: result[k] for k in ['status', 'message', 'indexed_at'] if k in result}

    def segments(self, record):
        result = []
        for attachment in self.current(record):
            cached = self.read(attachment)
            if cached['status'] == 'ready':
                result.extend({**segment, 'attachment_id': attachment['id'], 'name': attachment['name'],
                               'url': '/api/attachments/' + attachment['id']} for segment in cached['segments'])
        return result

    def matches(self, record, query):
        words = normalize(query).split()
        if not words:
            return []
        return [{k: segment[k] for k in ['attachment_id', 'name', 'locator', 'url']} |
                {'snippet': snippet(segment['text'], query)}
                for segment in self.segments(record) if any(w in normalize(segment['text']) for w in words)][:5]

    def _save(self, attachment, result):
        self.directory.mkdir(exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.directory, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(result, output, ensure_ascii=False)
            os.replace(temporary, self._cache_path(attachment))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def rebuild(self, attachment):
        path = original_path(self.data_dir, attachment)
        if path is None:
            return status('missing')
        result = status('failed', segments=[])
        try:
            stamp = [path.stat().st_size, path.stat().st_mtime_ns]
            if stamp[0] > MAX_BYTES:
                result = status('limit', segments=[])
            else:
                try:
                    completed = subprocess.run(
                        [sys.executable, str(Path(__file__).with_name('attachment_worker.py')), str(path)],
                        capture_output=True, timeout=TIMEOUT, check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                    )
                    if completed.returncode == 0:
                        result = json.loads(completed.stdout.decode('utf-8'))
                except subprocess.TimeoutExpired:
                    result = status('limit', segments=[])
            if [path.stat().st_size, path.stat().st_mtime_ns] != stamp:
                result = status('failed', segments=[])
            result.update(version=VERSION, sha256=attachment['sha256'], stamp=stamp, indexed_at=now())
            self._save(attachment, result)
        except (OSError, ValueError, TypeError):
            result = status('failed', segments=[])
        self.loaded[attachment['id']] = result
        return {k: result[k] for k in ['status', 'message', 'indexed_at'] if k in result}
