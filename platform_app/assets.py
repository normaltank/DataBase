"""One public revision for the HTML and all local application assets."""
from functools import lru_cache
from hashlib import sha256
from threading import RLock


@lru_cache(maxsize=4)
def _digest(manifest):
    value = sha256()
    for filename, _, _ in manifest:
        from pathlib import Path
        path = Path(filename)
        value.update(path.name.encode('utf-8'))
        value.update(path.read_bytes())
    return value.hexdigest()[:16]


class AssetRevision:
    def __init__(self, root):
        self.root = root
        self.lock = RLock()
        self.stats = {}
        self.value = None

    def current(self, *, force=False, filename=None):
        # Ordinary API requests reuse the manifest. A static read checks its own
        # file before serving, while HTML and upgrade checks rescan the manifest.
        # This avoids scanning every asset for every parallel stylesheet request.
        with self.lock:
            changed = False
            if filename:
                path = (self.root / 'static' / filename).resolve()
                if path.is_relative_to((self.root / 'static').resolve()):
                    try:
                        stat = path.stat()
                        changed = self.stats.get(str(path)) != (stat.st_mtime_ns, stat.st_size)
                    except OSError:
                        changed = str(path) in self.stats
            if force or changed or self.value is None:
                files = sorted([*self.root.joinpath('static').rglob('*'), *self.root.joinpath('templates').rglob('*.html')])
                manifest = tuple((str(p.resolve()), p.stat().st_mtime_ns, p.stat().st_size) for p in files if p.is_file())
                self.value = _digest(manifest)
                self.stats = {path: (mtime, size) for path, mtime, size in manifest}
            return self.value


@lru_cache(maxsize=4)
def revision(root):
    return AssetRevision(root)
