"""Frozen integrated schema22 application -> 23, rollback and portable restore."""
import argparse
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.web import create_app
from platform_app.maintenance import create_backup, restore_backup
from scripts.check_collaboration_recovery import login, stored_record, corrupt_archive
from scripts.check_journal_collaboration_recovery import SEED as TOPIC_SEED
from scripts.check_topic_finals_browser import call

SEED = TOPIC_SEED + r'''
wid=call(a,'/api/collaboration/journals',{'journal_name':'旧版独立期刊','coverage':'2025—2026跨期','record_id':rid})['id']
submission=call(a,f'/api/collaboration/journals/{wid}/submissions',{'version':1,'material_kind':'product','note':'原期刊成品','request_id':'old-journal-product'},b'legacy independent journal original')['id']
call(a,f'/api/collaboration/journals/{wid}/product',{'version':2,'submission_id':submission,'note':'实际采用','request_id':'old-journal-adopt'})
payload.update(journal_id=wid,journal=a.get('/api/collaboration/journals/'+wid).json,journal_history=a.get('/api/collaboration/journals/'+wid+'/history').json)
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True, help='Actually integrated #72 commit whose application creates schema22')
    baseline = parser.parse_args().baseline
    root = Path(__file__).resolve().parents[1]
    evidence = Path(tempfile.mkdtemp(prefix='database-topic-finals-recovery-'))
    print(json.dumps({'evidence': str(evidence)}), flush=True)
    (Path(tempfile.gettempdir()) / 'database-topic-finals-recovery-latest.txt').write_text(str(evidence), encoding='utf-8')
    archive, source, data = evidence / 'schema22.zip', evidence / 'schema22-source', evidence / 'data'
    subprocess.run(['git', 'archive', baseline, 'platform_app', '-o', str(archive)], cwd=root, check=True, capture_output=True)
    with zipfile.ZipFile(archive) as pack:
        pack.extractall(source)
    subprocess.run([sys.executable, '-c', SEED, str(data), str(evidence / 'before.json')], cwd=source, check=True, capture_output=True)
    before = json.loads((evidence / 'before.json').read_text(encoding='utf-8'))
    assert before['schema'] == 22, before['schema']
    failed = evidence / 'failed-upgrade'
    shutil.copytree(data, failed)
    with closing(sqlite3.connect(failed / 'platform.sqlite3')) as db, db:
        db.execute("CREATE TRIGGER synthetic_final_migration BEFORE UPDATE ON settings WHEN OLD.key='schema_version' AND NEW.value='23' BEGIN SELECT RAISE(ABORT,'synthetic last migration write failure'); END")
    try:
        create_app(failed, testing=True)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError('Expected failed upgrade')
    with closing(sqlite3.connect(failed / 'platform.sqlite3')) as db, db:
        assert db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] == '22'
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='topic_finals'").fetchone()
        db.execute('DROP TRIGGER synthetic_final_migration')
    assert login(create_app(failed, testing=True), 'researcher').get('/health').json['schema'] == 23
    app = create_app(data, testing=True)
    lead, author, admin = [login(app, name) for name in ('researcher', 'colleague', 'admin')]
    assert lead.get('/health').json['schema'] == 23
    record = lead.get('/api/records/' + before['record']['id']).json
    # The new optional backlink field does not alter an old independent record.
    assert record.pop('collaboration_works', []) == []
    assert stored_record(record) == stored_record(before['record'])
    assert lead.get('/api/history/record/' + before['record']['id']).json == before['history']
    assert lead.get('/api/collaboration/journals/' + before['journal_id']).json == before['journal']
    with closing(sqlite3.connect(data / 'platform.sqlite3')) as db:
        prebackup = Path(db.execute("SELECT value FROM settings WHERE key='topic_finals_migration_backup'").fetchone()[0])
    previous = restore_backup(prebackup, evidence / 'preupgrade-restored')
    with closing(sqlite3.connect(previous / 'platform.sqlite3')) as db:
        assert db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] == '22'
    assert login(create_app(previous, testing=True), 'researcher').get('/health').json['schema'] == 23
    tid = call(lead, '/api/collaboration/topics', {'theme': '定稿与汇总恢复', 'participant_ids': ['colleague']})['id']
    call(lead, f'/api/collaboration/topics/{tid}/meetings', {'version': 0, 'topic_version': 1, 'request_id': 'recovery-meeting', 'assignments': [{'title': '独立甲', 'author_id': 'colleague', 'country': '拉脱维亚、波兰'}, {'title': '独立乙', 'author_id': 'colleague', 'country': '拉脱维亚'}]})
    assignments = lead.get(f'/api/collaboration/topics/{tid}/workflow').json['assignments']
    finals, expected = [], [b'exact independent final A', b'exact independent final B']
    for index, a in enumerate(assignments):
        sid = call(author, f'/api/collaboration/topics/{tid}/assignments/{a["id"]}/submissions', {'version': 0, 'topic_version': 1, 'meeting_version': 1, 'request_id': 'recovery-draft-' + str(index)}, expected[index])['id']
        final = call(lead, f'/api/collaboration/topics/{tid}/assignments/{a["id"]}/finals', {'version': 1, 'topic_version': 1, 'meeting_version': 1, 'submission_id': sid, 'status': 'pending', 'request_id': 'recovery-final-' + str(index), 'note': '核对原件'})
        finals.append(final['id'])
    summary = call(lead, f'/api/collaboration/topics/{tid}/summaries', {'version': 0, 'topic_version': 1, 'author_id': 'colleague', 'final_ids': finals, 'request_id': 'recovery-summary'}, b'actual assembled summary independent original')
    call(author, f'/api/collaboration/topics/{tid}/assignments/{assignments[0]["id"]}/submissions', {'version': 1, 'topic_version': 1, 'meeting_version': 1, 'request_id': 'recovery-new-draft'}, b'later changed A manuscript')
    current = author.get(f'/api/collaboration/topics/{tid}/workflow').json
    full = create_backup(data)
    restored = evidence / 'new-directory-restored'
    subprocess.run([sys.executable, '-m', 'platform_app.maintenance', '--restore', str(full), '--target', str(restored)], cwd=root, check=True, capture_output=True)
    recovered_app = create_app(restored, testing=True)
    recovered_author, recovered_lead = login(recovered_app, 'colleague'), login(recovered_app, 'researcher')
    after = recovered_author.get(f'/api/collaboration/topics/{tid}/workflow').json
    assert after == current
    assert len(after['summaries'][0]['adoptions']) == 2
    for item, raw in zip(after['summaries'][0]['adoptions'], expected):
        with recovered_author.get(item['file_url']) as response:
            assert response.data == raw
    with recovered_author.get(after['summaries'][0]['file_url']) as response:
        assert response.data == b'actual assembled summary independent original'
    # The independent journal remains distinct and its historical adoption unchanged.
    assert recovered_lead.get('/api/collaboration/journals/' + before['journal_id']).json == before['journal']
    assert recovered_lead.get('/api/collaboration/journals/' + before['journal_id'] + '/history').json == before['journal_history']
    for old in before['topic_files']:
        with recovered_lead.get(old['url']) as response:
            assert response.data == old['raw'].encode()
    with recovered_lead.get(before['journal']['submissions'][0]['file_url']) as response:
        assert response.data == b'legacy independent journal original'
    with recovered_lead.get('/api/attachments/' + before['record']['attachments'][0]['id']) as response:
        assert response.data == b'legacy journal attachment'
    # Tamper with semantics while independently rewriting the archive-level hash.
    with zipfile.ZipFile(full) as pack:
        files = {name: pack.read(name) for name in pack.namelist()}
    rejected = []
    for index, mutation in enumerate(["UPDATE topic_summaries SET adoptions_json='[\"unknown-final\"]'", "UPDATE topic_finals SET actor_id='admin'", "UPDATE topic_finals SET assignment_id='wrong-series'", "UPDATE topic_finals SET qualification_version=99"]):
        corrupted = evidence / f'bad-{index}.zip'
        corrupt_archive(files, corrupted, mutation=mutation)
        target = evidence / f'bad-target-{index}'
        try:
            restore_backup(corrupted, target)
        except ValueError:
            assert not target.exists()
            rejected.append(index)
        else:
            raise AssertionError(mutation)
    result = {'baseline': baseline, 'schema_before': 22, 'schema_after': 23, 'preupgrade_backup_restored': True, 'migration_failure_rolled_back_and_retry_ok': True, 'journal_and_topic_history_retained': True, 'independent_legacy_body_and_attachment_unchanged': True, 'final_and_summary_identities_and_adoptions_restored': True, 'later_manuscript_does_not_replace_adoption': True, 'tampered_archive_rejections': len(rejected), 'final_original_sha256': [hashlib.sha256(raw).hexdigest() for raw in expected], 'summary_record_id': summary['record_id'], 'new_target_directory': str(restored)}
    (evidence / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(evidence), **result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
