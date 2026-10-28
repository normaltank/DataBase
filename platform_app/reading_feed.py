"""Persistent account batches. Record IDs freeze order; permissions stay live."""
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import abort, jsonify, g

from .store import connect, now
from .workflow import CONTENT_KINDS

SCHEMA_VERSION = 16


def choices(value):
    return [x.strip() for x in str(value or '').split('|') if x.strip()]


def terms(value):
    return [x.strip() for x in re.split(r'[;；,，|]', value or '') if x.strip()]


def available(row, projection):
    values = []
    if row['body_text']:
        values.append('body')
    if json.loads(row['attachment_ids']):
        values.append('file')
    if row['url'] or row['doi']:
        values.append('link')
    if projection['has_chinese']:
        values.append('chinese')
    elif row['kind'] not in CONTENT_KINDS:
        values.append('translation_pending')
    if not row['abstract']:
        values.append('no_abstract')
    if not any(x in values for x in ['body', 'file', 'link']):
        values.append('bibliography')
    return values


def facets(rows, db):
    from collections import Counter
    from . import translations, source_catalog, workflow
    counts = {key: Counter() for key in ['country', 'kind', 'language', 'topic', 'source', 'source_country', 'source_group', 'availability']}
    catalog = source_catalog.catalog(db)
    for row in rows:
        from .automatic_processing import projection as automatic_projection
        automatic = automatic_projection(db,row)
        source_ids = {s for s in [row['source_id'], row['serial_id'], *workflow.source_ids(db, row['id'])] if s}
        fields = {'country': terms(automatic['subject_countries']) or ['__unknown__'], 'kind': [automatic['classified_kind']],
                  'language': re.split(r'[;,|\s]+', row['language']) if row['language'] else ['__unknown__'],
                  'topic': terms(automatic['subject_topics']) or ['__unknown__'], 'source': source_ids or ['__unknown__'],
                  'availability': available(row, translations.projection(db, row)),
                  'source_group': {catalog[s]['group'] for s in source_ids if s in catalog},
                  'source_country': {c for s in source_ids if s in catalog for c in catalog[s].get('filter_countries', []) or ['__pending__']}}
        for key, values in fields.items():
            counts[key].update(set(values))
    return {key: [{'value': value, 'count': count} for value, count in sorted(counter.items())] for key, counter in counts.items()}


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute('''CREATE TABLE reading_batches (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                ids_json TEXT NOT NULL, recent_ids_json TEXT NOT NULL,
                reason TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT '')''')
            db.execute("CREATE UNIQUE INDEX reading_active_owner ON reading_batches(owner_id) WHERE finished_at=''")
            db.execute('''CREATE TABLE reading_confirmed (
                owner_id TEXT NOT NULL REFERENCES users(id), record_id TEXT NOT NULL REFERENCES records(id),
                confirmed_at TEXT NOT NULL, PRIMARY KEY(owner_id,record_id))''')
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('reading_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def get(db, owner, batch_id):
    row = db.execute('SELECT * FROM reading_batches WHERE id=? AND owner_id=?', (batch_id, owner)).fetchone()
    if not row:
        abort(404, '这批新增不属于当前账号或已不存在。')
    return row


def scope_ids(db, owner, args):
    if not args.get('batch'):
        return None
    row = get(db, owner, args['batch'])
    scope = args.get('batch_scope', 'recent')
    if scope not in {'recent', 'all'}:
        abort(400, '新增范围不正确。')
    return json.loads(row['ids_json' if scope == 'all' else 'recent_ids_json'])


def register(app, ctx):
    def public(row):
        # Only counts of records visible now; saved batch IDs are never disclosed.
        visible, _ = ctx.filtered_records({})
        allowed = {r['id'] for r in visible if r['kind'] not in CONTENT_KINDS}
        return {'id': row['id'], 'created_at': row['created_at'], 'finished_at': row['finished_at'],
                'reason': row['reason'],
                'pending_total': sum(i in allowed for i in json.loads(row['ids_json'])),
                'recent_total': sum(i in allowed for i in json.loads(row['recent_ids_json']))}

    @app.post('/api/reading-batches')
    def start():
        db, owner = ctx.db(), ctx.user()['id']
        with db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM reading_batches WHERE owner_id=? AND finished_at=''", (owner,)).fetchone()
            if row is None or not json.loads(row['ids_json']):
                rows, _ = ctx.filtered_records({})
                confirmed = {r[0] for r in db.execute('SELECT record_id FROM reading_confirmed WHERE owner_id=?', (owner,))}
                rows = [r for r in rows if r['kind'] not in CONTENT_KINDS and r['id'] not in confirmed]
                if row is not None:
                    if not rows:
                        return jsonify(public(row))
                    # An empty visit has no unread membership to preserve or confirm.
                    db.execute('UPDATE reading_batches SET finished_at=? WHERE id=?', (now(), row['id']))
                rows.sort(key=lambda r: (r['title'].casefold(), r['id']))
                rows.sort(key=lambda r: (r['created_at'], r['published_on']), reverse=True)
                stamp = now()
                threshold = (datetime.fromisoformat(stamp) - timedelta(days=30)).isoformat(timespec='seconds')
                previous = db.execute('SELECT MAX(finished_at) FROM reading_batches WHERE owner_id=?', (owner,)).fetchone()[0]
                reason = 'first_visit' if not previous else 'long_absence' if previous < threshold else 'return_visit'
                ids = [r['id'] for r in rows]
                recent = [r['id'] for r in rows if reason == 'return_visit' or r['created_at'] >= threshold]
                bid = uuid.uuid4().hex
                db.execute('INSERT INTO reading_batches(id,owner_id,ids_json,recent_ids_json,reason,created_at) VALUES(?,?,?,?,?,?)',
                           (bid, owner, json.dumps(ids), json.dumps(recent), reason, stamp))
                row = get(db, owner, bid)
        return jsonify(public(row))

    @app.post('/api/reading-batches/<bid>/finish')
    def finish(bid):
        db, owner = ctx.db(), ctx.user()['id']
        body = ctx.body()
        data = body.get('conditions', {})
        if not isinstance(data, dict) or any(not isinstance(v, str) and not isinstance(v, int) for v in data.values()):
            abort(400, '请保留当前查找条件后确认。')
        conditions = {k: str(v) for k, v in data.items()}
        conditions['batch'] = bid
        with db:
            db.execute('BEGIN IMMEDIATE')
            row = get(db, owner, bid)
            if row['finished_at']:
                abort(409, '本批已结束，请打开当前新增。')
            from . import reading_queries, saved_searches
            resolved = saved_searches.resolve(db, owner, conditions)
            if reading_queries.get(db, resolved) is None:
                abort(409, '请先重新读取当前结果，再确认已浏览。查找条件已保留。')
            selected, _ = ctx.filtered_records(conditions)
            if body.get('confirmation') != g.get('reading_confirmation'):
                abort(409, '结果范围或访问权限已变化，请重新读取当前结果后再确认。查找条件已保留。')
            stamp = now()
            db.executemany('INSERT OR IGNORE INTO reading_confirmed VALUES(?,?,?)', [(owner, r['id'], stamp) for r in selected])
            db.execute('UPDATE reading_batches SET finished_at=? WHERE id=?', (stamp, bid))
        return jsonify(confirmed=len(selected), finished_at=stamp)


def validate_backup(db):
    try:
        for row in db.execute('SELECT * FROM reading_batches'):
            all_ids, recent = json.loads(row['ids_json']), json.loads(row['recent_ids_json'])
            if (not isinstance(all_ids, list) or not isinstance(recent, list)
                    or any(not isinstance(i, str) for i in all_ids + recent)
                    or len(set(all_ids)) != len(all_ids) or not set(recent).issubset(all_ids)
                    or row['reason'] not in {'first_visit', 'return_visit', 'long_absence'}):
                raise ValueError('新增批次结构不正确。')
            datetime.fromisoformat(row['created_at'])
        for row in db.execute('SELECT * FROM reading_confirmed'):
            datetime.fromisoformat(row['confirmed_at'])
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError('新增阅读记录不完整。') from error
