"""Offline source ZIP verifier; checks inventory, native artifacts and every file hash."""
import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from verify_portable import check_name, sha


def verify_zip(path):
    from build_server import DIRS, FILES
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError('Duplicate case-insensitive ZIP entry')
        for entry in z.infolist():
            check_name(entry.orig_filename)
            if entry.orig_filename != entry.filename or entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unsafe ZIP entry')
        manifest = json.loads(z.read('manifest.json'))
        if manifest['format'] != 'research-server-v1' or set(names) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('Manifest inventory differs from ZIP')
        sources = set(manifest['source_files'])
        if not FILES <= sources or not sources <= set(names):
            raise ValueError('Required source files missing')
        for name in sources:
            parts = PurePosixPath(name).parts
            if not (name in FILES or parts[0] in DIRS or name.startswith('scripts/') and name.endswith('.py')):
                raise ValueError('File outside source allowlist: ' + name)
            if any(part.startswith('.') for part in parts) or any(part in {'__pycache__', 'data', 'backups', 'logs'} for part in parts):
                raise ValueError('Runtime/development residue: ' + name)
        locked = json.loads(z.read('server/dependency-lock.json'))
        wheels = set()
        for platform, artifacts in locked['platforms'].items():
            for artifact in artifacts:
                name = 'wheels/' + platform + '/' + artifact['filename']
                wheels.add(name)
                raw = z.read(name)
                if sha(raw) != artifact['sha256'] or len(raw) != artifact['bytes']:
                    raise ValueError('Native dependency differs from lock: ' + name)
                for license in artifact['license_text_files']:
                    license_path = 'server/' + license['saved_path']
                    if sha(z.read(license_path)) != license['sha256']:
                        raise ValueError('Third-party license differs from lock')
        if set(names) != sources | wheels | {'manifest.json'}:
            raise ValueError('File outside source/dependency allowlist')
        for name, metadata in manifest['files'].items():
            raw = z.read(name)
            if metadata != {'bytes': len(raw), 'sha256': sha(raw)}:
                raise ValueError('Manifest hash mismatch: ' + name)
        return {'files': len(names), 'source_commit': manifest['source_commit'], 'source_dirty': manifest['source_dirty'],
                'python': manifest['python'], 'dependency_platforms': sorted(locked['platforms'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_zip(args.package)))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, str(error) + '\n')
