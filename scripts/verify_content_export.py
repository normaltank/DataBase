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


def verify_anchors(archive, entries):
    """Check declared anchors against both projections and the checked file list."""
    if 'content.json' not in entries:
        if 'evidence-coverage.json' in entries:
            raise VerificationError('Missing attachment anchor content declarations')
        return
    content = json.loads(archive.read('content.json'), object_pairs_hook=unique_object)
    if not isinstance(content, dict) or not isinstance(content.get('records'), list):
        raise VerificationError('Invalid content schema for attachment anchors')
    attachments = {}
    for row in content.get('attachments', []):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in attachments:
            raise VerificationError('Invalid or duplicate attachment anchor file identity')
        attachments[row['id']] = row
    declared = {}

    def check(anchor, aid, path=None):
        if not isinstance(anchor, dict) or not isinstance(aid, str) or anchor.get('id') != aid:
            raise VerificationError('Attachment anchor identity mismatch')
        attached = attachments.get(aid)
        if not attached or not isinstance(attached.get('path'), str):
            raise VerificationError('Missing attachment anchor file')
        if path is not None and path != attached['path']:
            raise VerificationError('Attachment anchor path mismatch')
        registered = entries.get(attached['path'])
        if not attached['path'].startswith('attachments/') or not registered:
            raise VerificationError('Missing attachment anchor manifest entry')
        if anchor.get('name') != attached.get('name'):
            raise VerificationError('Attachment anchor filename mismatch')
        for key in ['bytes', 'sha256']:
            if key not in anchor or anchor[key] != attached.get(key) or anchor[key] != registered[key]:
                raise VerificationError('Attachment anchor ' + key + ' mismatch')
        if type(anchor['bytes']) is not int or not isinstance(anchor['sha256'], str):
            raise VerificationError('Invalid attachment anchor checksum')

    for row in content['records']:
        for key, snapshot in [(('record', row['id']), row), *[(('citation', row['id'], c['excerpt_id']), c['snapshot']) for c in row.get('evidence_citations', [])]]:
            original = snapshot.get('evidence_snapshot')
            if original is None:
                original = json.loads(snapshot.get('evidence_snapshot_json') or '{}', object_pairs_hook=unique_object)
            if isinstance(original, dict) and 'attachment_anchor' in original:
                anchor = original['attachment_anchor']
                check(anchor, snapshot.get('evidence_attachment_id'))
                declared[key] = anchor
    if 'evidence-coverage.json' not in entries:
        if declared:
            raise VerificationError('Missing attachment anchor coverage')
        return
    coverage = json.loads(archive.read('evidence-coverage.json'), object_pairs_hook=unique_object)
    observed = {}
    for row in coverage['records']:
        for key, retained in [(('record', row['id']), row['evidence']), *[(('citation', row['id'], c['excerpt_id']), c) for c in row.get('citations', [])]]:
            if 'attachment_anchor' in retained and retained['attachment_anchor'] is not None:
                anchor = retained['attachment_anchor']
                attached = retained.get('attachment') or {}
                if not isinstance(attached.get('path'), str):
                    raise VerificationError('Missing attachment anchor coverage path')
                check(anchor, attached.get('id'), attached['path'])
                observed[key] = anchor
    if declared != observed:
        raise VerificationError('Attachment anchor content/coverage declarations differ')


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
            verify_anchors(archive, entries)
            return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path', help='ZIP to read; nothing is extracted or executed')
    parser.add_argument('--sha256', help='Whole ZIP SHA-256 obtained through a separate trusted channel')
    args = parser.parse_args()
    try:
        count = verify(args.zip_path, args.sha256)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    print(f'OK: {count} files and declared attachment anchors match the manifest. Historical records without anchors remain unchecked. Internal consistency only; not proof of authenticity, authorship, or research validity.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
