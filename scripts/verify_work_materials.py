"""Independently verify a work ZIP with Python's standard library only.

Checks bytes, exact file coverage, work/version identities, review/adoption links
and the declared scope. Internal consistency is not authenticity: compare a
separately saved whole-ZIP SHA-256 or the original HTTP files for that purpose.
Never extracts files, executes archive content, or imports the application.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile


def require(value, message):
    if not value:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def digest(stream):
    sha, size = hashlib.sha256(), 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        size += len(chunk)
        sha.update(chunk)
    return size, sha.hexdigest()


def series(items):
    versions = sorted(x['version'] for x in items)
    require(versions == list(range(1, len(items) + 1)), 'Missing or duplicate historical version')


def identities(items):
    result = {}
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'] not in result, 'Missing or duplicate identity')
        result[item['id']] = item
    return result


def verify(path, expected_sha256=None):
    if expected_sha256:
        with Path(path).open('rb') as stream:
            require(digest(stream)[1] == expected_sha256.lower(), 'Whole ZIP SHA-256 mismatch')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'Duplicate ZIP member')
        require('manifest.json' in names and 'README.txt' in names, 'Missing manifest or coverage readme')
        require(archive.getinfo('manifest.json').file_size <= 32 * 1024 * 1024, 'Manifest too large')
        m = json.loads(archive.read('manifest.json'), object_pairs_hook=unique_object)
        require(m['format'] == 'work-materials-v1' and m['business'] in ('topic', 'journal') and m['scope'] in ('all', 'products', 'process'), 'Unknown material scope')
        require(bool(m['coverage']) and bool(m['exclusions']), 'Missing coverage declaration')
        wid, scope = m['work_id'], m['scope']
        files = {}
        for f in m['files']:
            fid, filename = f['file_id'], f['path']
            require(isinstance(fid, str) and re.fullmatch('[a-f0-9]{32}', fid) and fid not in files, 'Duplicate or invalid file identity')
            require(re.fullmatch('originals/' + fid + r'\.(txt|md|docx|pdf)', filename), 'Unsafe or mismatched file path')
            require(type(f['bytes']) is int and f['bytes'] > 0 and re.fullmatch('[a-f0-9]{64}', f['sha256']), 'Invalid file hash or size')
            require(bool(f['name']) and '/' not in f['name'] and '\\' not in f['name'], 'Invalid original name')
            with archive.open(filename) as stream:
                require(digest(stream) == (f['bytes'], f['sha256']), 'Original bytes differ from manifest')
            files[fid] = f
        require(set(names) == {'manifest.json', 'README.txt'} | {f['path'] for f in files.values()}, 'Missing or extra ZIP files')
        referenced, owners = set(), {}

        def original(item, owner=None):
            fid = item.get('file_id')
            if not fid:
                require(not item.get('path'), 'Path without original identity')
                return
            f = files.get(fid)
            require(f is not None and all(item.get(k) == f[k] for k in ('name', 'bytes', 'sha256', 'path')), 'Original reference differs from file list')
            referenced.add(fid)
            if owner:
                require(fid not in owners or owners[fid] == owner, 'Original has conflicting business owners')
                owners[fid] = owner

        if m['business'] == 'topic':
            require(m['topic']['id'] == wid, 'Wrong topic identity')
            workflow, candidates = m['workflow'], m['candidates']
            identities(candidates)
            if scope == 'products':
                require(not candidates and not workflow['meetings'], 'Process materials in products scope')
            for uid in {c['author_id'] for c in candidates}:
                series([c for c in candidates if c['author_id'] == uid])
            for c in candidates:
                require(c['topic_id'] == wid, 'Cross-topic candidate')
                original(c, ('candidate', c['id']))
            meetings = identities(workflow['meetings'])
            if scope != 'products':
                series(list(meetings.values()))
                require(workflow['meeting_version'] == len(meetings), 'Missing meeting decision')
            for meeting in meetings.values():
                require(meeting['topic_id'] == wid, 'Cross-topic meeting')
                original(meeting, ('meeting', meeting['id']))
            all_finals = {}
            identities(workflow['assignments'])
            for a in workflow['assignments']:
                submissions, finals = identities(a['submissions']), identities(a['finals'])
                identities(a['returns'])
                if scope != 'products':
                    series(list(submissions.values()))
                else:
                    require(not a['returns'] and {f['submission_id'] for f in finals.values()} == set(submissions), 'Wrong products submission scope')
                if scope == 'process':
                    require(not finals, 'Final decisions in process scope')
                for s in submissions.values():
                    require(s['topic_id'] == wid and s['assignment_id'] == a['id'], 'Cross-work submission')
                    if scope != 'products':
                        meeting = meetings.get(s['meeting_id'])
                        require(meeting and any(x['id'] == a['id'] and x['author_id'] == s['author_id'] for x in meeting['assignments']), 'Submission differs from historical assignment')
                    original(s, ('submission', s['id']))
                for r in a['returns']:
                    require(r['topic_id'] == wid and r['assignment_id'] == a['id'] and r['submission_id'] in submissions, 'Return decision has wrong version')
                    original(r, ('return', r['id']))
                for f in finals.values():
                    s = submissions.get(f['submission_id'])
                    require(f['id'] not in all_finals and s and f['topic_id'] == wid and f['assignment_id'] == a['id'], 'Final has wrong work or submission')
                    require(all(f[k] == s[k] for k in ('file_id', 'version', 'sha256', 'name', 'author_id')), 'Final adopted another original version')
                    require(not any(r['submission_id'] == s['id'] for r in a['returns']), 'Same submission returned and finalized')
                    if scope != 'products':
                        meeting = meetings.get(f['meeting_id'])
                        require(meeting and any(x['id'] == a['id'] and x['author_id'] == f['author_id'] and x['title'] == f['title'] and x['country'] == f['country'] for x in meeting['assignments']), 'Final differs from meeting assignment')
                    original(f)  # Adoption is a reference, not another owner.
                    all_finals[f['id']] = f
            summaries = workflow['summaries']
            identities(summaries)
            series(summaries)
            if scope == 'process':
                require(not summaries, 'Summary in process scope')
            for s in summaries:
                require(s['topic_id'] == wid and bool(s['adoptions']), 'Missing summary adoption')
                original(s, ('summary', s['id']))
                adopted = identities(s['adoptions'])
                require(set(s['adopted_final_ids']) == set(adopted) and len(s['adopted_final_ids']) == len(adopted), 'Missing declared summary adoption')
                for fid, f in adopted.items():
                    require(fid in all_finals and f == all_finals[fid], 'Summary adoption differs from exact final')
                    original(f)
        else:
            work = m['journal']
            require(work['id'] == wid, 'Wrong journal work identity')
            submissions = identities(work['submissions'])
            history = work['history']
            series(history)
            require(len(history) == work['version'] and history[-1]['snapshot']['current_product_id'] == work['current_product_id'], 'Missing journal work or adoption history')
            if scope == 'all':
                series(list(submissions.values()))
                # Each historical upload is represented by one immutable owner.
                require(sum(e['action'] in ('保存编译稿', '保存审稿材料', '保存成品文件') for e in history) == len(submissions), 'Missing journal submission')
                adopted = {e['snapshot']['current_product_id'] for e in history} - {None}
                require(adopted <= set(submissions), 'Missing adopted journal original')
            elif scope == 'products':
                require(set(submissions) == ({work['current_product_id']} if work['current_product_id'] else set()), 'Wrong current product scope')
            else:
                require(work['current_product_id'] not in submissions, 'Current product in process scope')
            for e in history:
                require(e['work_id'] == wid and e['snapshot']['id'] == wid and e['snapshot']['version'] == e['version'], 'Cross-work journal history')
            for s in submissions.values():
                require(s['work_id'] == wid and s['material_kind'] in ('manuscript', 'review', 'product'), 'Cross-work journal submission')
                require(s['id'] != work['current_product_id'] or s['material_kind'] != 'review', 'Review file cannot be current product')
                original(s, ('journal', s['id']))
        require(referenced == set(files) == set(owners), 'Missing or unreferenced original files')
        return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path')
    parser.add_argument('--sha256', help='Whole-ZIP digest obtained through a separate trusted channel')
    args = parser.parse_args()
    try:
        count = verify(args.zip_path, args.sha256)
    except (OSError, ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile, RuntimeError) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    print(f'OK: {count} originals; bytes, declared scope and exact adoption/version relations consistent. Internal consistency only; not authenticity or proof of unexported data.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
