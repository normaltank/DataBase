"""Bounded discovery for autonomous maintenance; no network or parallel scheduler.

Checkpoints live with the database settings and survive full backup/restore. Public
object projections are the sole input: originals, attachments and notes stay local.
"""
import json
from datetime import datetime, timedelta

from werkzeug.exceptions import HTTPException

from . import store

PREFIX = 'maintenance_scan:'
RECHECK_DAYS = 30
SCAN_PER_KIND = 40
QUEUE_PER_KIND = 4


def checkpoint(db, kind, tid):
    row = db.execute('SELECT value FROM settings WHERE key=?', (PREFIX+kind+':'+tid,)).fetchone()
    return json.loads(row[0]) if row else {}


def remember(db, kind, tid, fingerprint, **extra):
    value = {**checkpoint(db, kind, tid), 'fingerprint': fingerprint, **extra}
    db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',
               (PREFIX+kind+':'+tid, json.dumps(value)))


def fingerprint(db, kind, tid, data_dir):
    from . import maintenance_agent as agent
    return agent.digest(agent.read_object(db, agent.machine(db), kind, tid, data_dir))


def completed(db, job, data_dir):
    """A settled job observes its own edits, so the next tick does not repeat them.

    A newly created related profile has never had its own maintenance pass; leave
    it discoverable once, then its own completion supplies the checkpoint.
    """
    from . import maintenance_agent as agent
    targets = {(job['target_type'], job['target_id'])}
    observations = {}
    created = set()
    for row in db.execute("SELECT name,arguments_json,result_json FROM maintenance_steps WHERE job_id=? AND status='completed' ORDER BY position", (job['id'],)):
        result = json.loads(row['result_json'])
        if result.get('changed_target') and result.get('before') is None:
            created.add(tuple(result['changed_target']))
        if result.get('changed_target') and result.get('before') is not None:
            targets.add(tuple(result['changed_target']))
        if row['name'] == 'read' and result.get('object'):
            arguments = json.loads(row['arguments_json'])
            observations[(arguments['target_type'], arguments['id'])] = result['object']
    for kind, tid in targets:
        if (kind, tid) in created and (kind, tid) != (job['target_type'], job['target_id']):
            continue
        if (kind, tid) in observations:
            remember(db, kind, tid, agent.digest(observations[(kind, tid)]), checked_at=store.now())


def scan(db, data_dir):
    """Visit rotating bounded slices; enqueue changed or due public objects once."""
    from . import maintenance_agent as agent
    queued = 0
    actor = agent.machine(db)
    for kind, table in [('record', 'records'), ('person', 'people'), ('source', 'sources')]:
        kind_queued = 0
        key = PREFIX+'cursor:'+kind
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        cursor = row[0] if row else ''
        rows = db.execute(f'SELECT id FROM {table} WHERE merged_into IS NULL AND id>? ORDER BY id LIMIT ?',
                          (cursor, SCAN_PER_KIND)).fetchall()
        if not rows and cursor:
            rows = db.execute(f'SELECT id FROM {table} WHERE merged_into IS NULL ORDER BY id LIMIT ?',
                              (SCAN_PER_KIND,)).fetchall()
        if not rows:
            with db:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, ''))
            continue
        for row in rows:
            tid = row['id']
            try:
                current = fingerprint(db, kind, tid, data_dir)
            except HTTPException:
                continue
            if db.execute("SELECT 1 FROM maintenance_jobs WHERE target_type=? AND target_id=? AND status IN ('queued','running','paused')", (kind, tid)).fetchone():
                continue
            previous = checkpoint(db, kind, tid)
            checked = max(previous.get('checked_at', ''), previous.get('queued_at', ''))
            due = not checked or datetime.fromisoformat(checked)+timedelta(days=RECHECK_DAYS) <= datetime.fromisoformat(store.now())
            if previous.get('fingerprint') == current and not due:
                continue
            if kind_queued >= QUEUE_PER_KIND:
                break
            request = 'automatic:'+agent.digest([kind, tid, current, checked or '', store.now()[:10]])
            jid = agent.enqueue(db, actor, kind, tid, request, priority=-10, automatic=True)
            with db:
                remember(db, kind, tid, current, queued_at=store.now(), job_id=jid)
            queued += 1
            kind_queued += 1
        with db:
            # Retain the last visited identity, including ineligible objects.
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, tid))
    return queued
