"""Explicit portable-only admission; ordinary deployments never enable this module."""
import json
import secrets
import uuid
from pathlib import Path

from flask import abort, request, session
from werkzeug.security import generate_password_hash

from platform_app.store import connect, now

SAMPLES = 'portable_trial_samples_v1'
MEMBER = 'portable_trial_member:'
HOST = 'portable_trial_host_v1'
RETURN = 'portable_research_return_v1'


def local_request():
    return request.remote_addr in {'127.0.0.1', '::1'}


def initialize(data_dir):
    """Import explicit seed identities once; settings travel with full backups."""
    path = Path(data_dir) / 'demo-seed.json'
    if not path.is_file():
        return
    seed = json.loads(path.read_text(encoding='utf-8'))
    if not seed.get('fictional_collaboration'):
        return
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        topics = [seed[k] for k in ('complete_topic', 'active_topic') if seed.get(k) and
                  db.execute('SELECT 1 FROM collaboration_topics WHERE id=?', (seed[k],)).fetchone()]
        journal = db.execute('SELECT record_id FROM journal_works WHERE id=?', (seed.get('journal'),)).fetchone()
        value = dict(topics=topics, records=[journal[0]] if journal else [])
        with db:
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (SAMPLES, json.dumps(value)))
    finally:
        db.close()


def member(db, uid):
    return bool(db.execute('SELECT 1 FROM settings WHERE key=?', (MEMBER + uid,)).fetchone())


def enrich(db, account):
    result = dict(account)
    if member(db, result['id']):
        sample = db.execute('SELECT value FROM settings WHERE key=?', (SAMPLES,)).fetchone()
        samples = json.loads(sample[0]) if sample else {}
        result.update(temporary=True, trial_sample_topics=samples.get('topics', []),
                      trial_sample_records=samples.get('records', []))
    host = db.execute('SELECT value FROM settings WHERE key=?', (HOST,)).fetchone()
    if host and host[0] == result['id']:
        if not local_request():
            abort(403, '本机维护身份只能在主机本机使用。')
        result['host_maintenance'] = True
    return result


def sign_in(row):
    session.clear()
    session.update(uid=row['id'], csrf=secrets.token_hex(24), credential_version=row['credential_version'])
    session.permanent = True


def return_identity(db):
    """A signed session marker is proof of the authenticated pre-switch user."""
    proof = session.get(RETURN)
    host = db.execute('SELECT value FROM settings WHERE key=?', (HOST,)).fetchone()
    if not local_request() or not host or session.get('uid') != host[0] or not isinstance(proof, dict):
        return None
    row = db.execute('SELECT * FROM users WHERE id=? AND active=1', (proof.get('uid'),)).fetchone()
    if not row or row['role'] != 'researcher' or row['credential_version'] != proof.get('credential_version') or not member(db, row['id']):
        return None
    return row


def return_to_research(db):
    row = return_identity(db)
    if row is None:
        abort(403, '原研究身份不能恢复，请使用已有账号或重新进入体验。')
    sign_in(row)


def admit(db):
    uid = 'trial_' + uuid.uuid4().hex
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO users(id,username,name,password_hash,role) VALUES (?,?,?,?,?)',
                   (uid, uid, '临时研究员 · ' + uid[-6:], generate_password_hash(secrets.token_hex(32)), 'researcher'))
        db.execute('INSERT INTO settings VALUES (?,?)', (MEMBER + uid, '1'))
        db.execute('INSERT INTO lead_qualifications VALUES (?,1,1)', (uid,))
        db.execute('INSERT INTO qualification_events(member_id,actor_id,enabled,version,created_at) VALUES (?,?,1,1,?)', (uid, uid, now()))
    sign_in(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())


def host_sign_in(db):
    if not local_request():
        abort(403, '请在主机本机地址打开维护入口。')
    proof = session.get(RETURN) if return_identity(db) is not None else None
    previous = db.execute('SELECT * FROM users WHERE id=? AND active=1', (session.get('uid'),)).fetchone()
    if previous and previous['role'] == 'researcher' and member(db, previous['id']) and previous['credential_version'] == session.get('credential_version'):
        proof = dict(uid=previous['id'], credential_version=previous['credential_version'])
    with db:
        db.execute('BEGIN IMMEDIATE')
        saved = db.execute('SELECT value FROM settings WHERE key=?', (HOST,)).fetchone()
        if saved:
            row = db.execute('SELECT * FROM users WHERE id=? AND active=1', (saved[0],)).fetchone()
            if not row:
                abort(403, '本机维护身份已停用，请使用已有管理员账号。')
        else:
            uid = 'host_' + uuid.uuid4().hex
            db.execute('INSERT INTO users(id,username,name,password_hash,role) VALUES (?,?,?,?,?)',
                       (uid, uid, '本机维护', generate_password_hash(secrets.token_hex(32)), 'admin'))
            db.execute('INSERT INTO settings VALUES (?,?)', (HOST, uid))
            row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    sign_in(row)
    if proof:
        session[RETURN] = proof
