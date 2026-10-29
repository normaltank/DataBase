"""Offline package inventory and hashes. No application import or data access."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

SAMPLE_SHA256 = '8aed2928d8a757236ee73cfa20746c357c6b76b9caffcc4fa8f66473a56bef3e'
PTH = b'python312.zip\n.\nLib/site-packages\n..\n'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check_name(name):
    parts = name.split('/')
    if (not name or '\\' in name or ':' in name or PurePosixPath(name).is_absolute()
            or any(p in ('', '.', '..') for p in parts)):
        raise ValueError('Unsafe file name: ' + name)
    return parts


def verify(read, names, require_intro=True):
    from build_portable import SOURCE_DIRS, SOURCE_FILES
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Duplicate case-insensitive package name')
    for name in names:
        check_name(name)
    manifest = json.loads(read('manifest.json'))
    expected = set(manifest['files']) | {'manifest.json'}
    if set(names) != expected:
        raise ValueError('Package inventory differs from manifest')
    fixed = SOURCE_FILES | {'start.bat', 'stop.bat', '使用说明.html', 'THIRD-PARTY-NOTICES.txt', 'manifest.json'}
    if require_intro:
        fixed |= {'项目介绍.pdf'}
        if not manifest['introduction_present'] or not read('项目介绍.pdf').startswith(b'%PDF-'):
            raise ValueError('Actual project introduction PDF is required')
    if not fixed <= expected:
        raise ValueError('Required source or entry missing: ' + str(fixed - expected))
    lock = json.loads(read('portable/runtime-lock.json'))
    runtime_files = {'runtime/' + name: digest for name, digest in lock['python']['installed_files'].items()}
    runtime_files['runtime/python312._pth'] = sha(PTH)
    for wheel in lock['wheels']:
        for name, digest in wheel['installed_files'].items():
            key = 'runtime/Lib/site-packages/' + name
            if key in runtime_files:
                raise ValueError('Duplicate runtime artifact path')
            runtime_files[key] = digest
    if {n for n in names if n.startswith('runtime/')} != set(runtime_files):
        raise ValueError('Runtime differs from official artifact inventory')
    for name in names:
        first = PurePosixPath(name).parts[0]
        if name.startswith('runtime/'):
            if sha(read(name)) != runtime_files[name]:
                raise ValueError('Runtime bytes differ from locked official artifact: ' + name)
        elif first in SOURCE_DIRS:
            if Path(name).suffix not in {'.py', '.js', '.css', '.html', '.svg', '.png', '.ico', '.woff2'}:
                raise ValueError('Unexpected source file: ' + name)
        elif name not in fixed and name != '项目介绍.pdf':
            raise ValueError('File outside explicit distribution allowlist: ' + name)
        if name != 'manifest.json':
            raw = read(name)
            if manifest['files'][name] != {'bytes': len(raw), 'sha256': sha(raw)}:
                raise ValueError('Manifest digest mismatch: ' + name)
    if sha(read('portable/samples/fictional-article.pdf')) != SAMPLE_SHA256:
        raise ValueError('Unexpected sample original')
    if not read('runtime/LICENSE.txt') or not read('THIRD-PARTY-NOTICES.txt'):
        raise ValueError('Missing third-party notices')
    return {'files': len(names), 'source_commit': manifest['source_commit'],
            'source_dirty': manifest['source_dirty'], 'introduction_present': manifest['introduction_present']}


def verify_zip(path):
    with zipfile.ZipFile(path) as z:
        for entry in z.infolist():
            # ZipInfo.filename normalizes backslashes on Windows; inspect its original spelling.
            check_name(entry.orig_filename)
            if entry.orig_filename != entry.filename:
                raise ValueError('Unsafe file name: ' + entry.orig_filename)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Directory or symbolic link ZIP entry')
        return verify(z.read, z.namelist())


def verify_directory(path, require_intro=True):
    names = []
    for file in path.rglob('*'):
        if file.is_symlink():
            raise ValueError('Symbolic link in staging')
        if file.is_file():
            names.append(file.relative_to(path).as_posix())
    return verify(lambda name: (path / name).read_bytes(), names, require_intro)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--preparation', action='store_true')
    args = parser.parse_args()
    try:
        result = verify_zip(args.package) if args.package.is_file() else verify_directory(args.package, not args.preparation)
        print(json.dumps(result))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, str(error) + '\n')
