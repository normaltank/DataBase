"""Verify exported ZIP internal consistency, optionally against a trusted digest.

Python standard library only. No extraction, application imports, or execution of
archive members. A self-contained manifest is not proof of authenticity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import unicodedata
import zipfile


class VerificationError(ValueError):
    pass


def safe_path(name):
    if not isinstance(name, str) or not name or any(ord(c) < 32 for c in name) or any(c in name for c in '\\:<>"|?*'):
        raise VerificationError('Unsafe archive path')
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(n) for n in range(1, 10)), *('LPT' + str(n) for n in range(1, 10))}
    if any(p in ('', '.', '..') or p.endswith((' ', '.')) or p.split('.')[0].upper() in reserved for p in parts):
        raise VerificationError('Unsafe archive path: ' + name)
    return unicodedata.normalize('NFC', name).casefold()


def digest_stream(stream):
    digest, count = hashlib.sha256(), 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
        count += len(chunk)
    return count, digest.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def verify(path, expected_sha256=None):
    with Path(path).open('rb') as source:
        if expected_sha256 is not None:
            if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
                raise VerificationError('Expected SHA-256 must have 64 hexadecimal characters')
            if digest_stream(source)[1] != expected_sha256.lower():
                raise VerificationError('Whole ZIP SHA-256 mismatch')
            source.seek(0)
        with zipfile.ZipFile(source) as archive:
            members, portable = {}, set()
            for info in archive.infolist():
                normalized = safe_path(info.filename)
                mode = info.external_attr >> 16
                if normalized in portable or info.filename in members:
                    raise VerificationError('Duplicate archive path: ' + info.filename)
                if info.is_dir() or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise VerificationError('Only regular files are supported')
                portable.add(normalized)
                members[info.filename] = info
            if 'manifest.json' not in members:
                raise VerificationError('Missing manifest.json')
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'), object_pairs_hook=unique_object)
            if (not isinstance(manifest, dict) or set(manifest) != {'format', 'files'}
                    or manifest['format'] != 'research-content-manifest-v1' or not isinstance(manifest['files'], list)):
                raise VerificationError('Invalid manifest schema or version')
            entries, portable = {}, set()
            for row in manifest['files']:
                if not isinstance(row, dict) or set(row) != {'path', 'bytes', 'sha256'}:
                    raise VerificationError('Invalid manifest file entry')
                name = row['path']
                normalized = safe_path(name)
                if name == 'manifest.json' or name in entries or normalized in portable:
                    raise VerificationError('Duplicate or self-referencing manifest path')
                if type(row['bytes']) is not int or row['bytes'] < 0 or not isinstance(row['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
                    raise VerificationError('Invalid manifest size or SHA-256')
                entries[name] = row
                portable.add(normalized)
            if set(entries) != set(members) - {'manifest.json'}:
                raise VerificationError('Missing or extra archive files')
            for name, row in entries.items():
                if members[name].file_size != row['bytes']:
                    raise VerificationError('Byte count mismatch: ' + name)
                with archive.open(members[name]) as stream:
                    size, digest = digest_stream(stream)
                if size != row['bytes'] or digest != row['sha256']:
                    raise VerificationError('File checksum mismatch: ' + name)
            return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path', help='ZIP to read; nothing is extracted or executed')
    parser.add_argument('--sha256', help='Whole ZIP SHA-256 obtained through a separate trusted channel')
    args = parser.parse_args()
    try:
        count = verify(args.zip_path, args.sha256)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    print(f'OK: {count} files match the manifest. Internal consistency only; not proof of authenticity, authorship, or research validity.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
