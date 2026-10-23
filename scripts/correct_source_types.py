"""Correct only untouched automatic catalogue types, with backup and history."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_app.maintenance import create_backup
from platform_app.source_catalog import registered_institution_types, unpack
from platform_app.store import connect, now, save_revision

KEY = 'source_catalog_type_correction_20261021'
MIGRATION_ACTION = '目录升级：补充登记依据与类型'
EVIDENCE_ACTION = '采纳 2026-10-21 样本证据（仍待中心核对）'


def plan(db):
    changes, skipped = [], []
    for row in db.execute("SELECT * FROM sources WHERE kind IN ('institution','think_tank') ORDER BY id"):
        current = unpack(row)
        revisions = db.execute("SELECT * FROM revisions WHERE target_type='source' AND target_id=? ORDER BY id",
                               (row['id'],)).fetchall()
        generated = next((r for r in revisions if r['action'] == MIGRATION_ACTION), None)
        if not generated:
            continue
        later = [r for r in revisions if r['id'] > generated['id']]
        original = unpack(json.loads(generated['snapshot_json']))
        latest = unpack(json.loads(revisions[-1]['snapshot_json']))
        if (any(r['action'] != EVIDENCE_ACTION for r in later) or
                any(current[k] != original[k] for k in ('kind', 'name', 'original_name', 'classification')) or
                current['institution_types'] != latest['institution_types']):
            skipped.append(dict(id=row['id'], reason='自动迁移后有人工或未识别修改，保留当前记录'))
            continue
        reviewed_additions = [t for t in current['institution_types'] if t not in original['institution_types']]
        corrected = list(dict.fromkeys(registered_institution_types(current) + reviewed_additions))
        if len(corrected) > 1:
            corrected = [t for t in corrected if t != 'other']
        if set(corrected) != set(current['institution_types']):
            changes.append(dict(id=row['id'], before=current['institution_types'], after=corrected,
                                classification=row['classification']))
    return dict(changed=changes, skipped=skipped)


def apply(data_dir, dry_run=False):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        previous = db.execute('SELECT value FROM settings WHERE key=?', (KEY,)).fetchone()
        if previous:
            return dict(already_applied=True, report=json.loads(previous[0]))
        if dry_run:
            return plan(db)
        backup = create_backup(data_dir)
        with db:
            db.execute('BEGIN IMMEDIATE')
            report = plan(db)
            for change in report['changed']:
                db.execute("UPDATE sources SET institution_types=?,version=version+1,status='pending',updated_at=? WHERE id=?",
                           (json.dumps(change['after']), now(), change['id']))
                save_revision(db, 'source', change['id'], '纠正自动机构类型：按自身身份分类', 'admin')
            report.update(backup=str(backup), applied_at=now())
            db.execute('INSERT INTO settings VALUES (?,?)', (KEY, json.dumps(report, ensure_ascii=False)))
        return report
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(json.dumps(apply(args.data_dir, args.dry_run), ensure_ascii=False, indent=2))
