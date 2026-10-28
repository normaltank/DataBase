"""Freeze membership of a resolved batch query; content and permissions stay live."""
import hashlib
import json
import uuid
from pathlib import Path

from .store import connect, now
from .saved_searches import CONDITION_KEYS
from .search import normalize

SCHEMA_VERSION = 18


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute('''CREATE TABLE reading_queries (
                id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES reading_batches(id),
                conditions_json TEXT NOT NULL, ids_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(batch_id, conditions_json))''')
            # One atomic v18 migration covers both fixes; v17 is ingestion's
            # migration and must run before this migration in initialize().
            from .translations import create_call_schema
            create_call_schema(db)
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('reading_queries_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def conditions(args):
    # Callers resolve saved searches before this boundary. Pagination never creates
    # another membership set; batch order already determines the result order.
    result = {k: str(args[k]).strip() for k in CONDITION_KEYS - {'feed', 'sort'} if args.get(k)}
    for key in ['country','kind','source','source_country','source_group','language','topic','availability']:
        if key in result:
            values = (v.strip() for v in result[key].split('|') if v.strip())
            if key in {'country','topic'}:
                values = (v.casefold() for v in values)
            result[key] = '|'.join(sorted(set(values)))
    if 'q' in result:
        result['q'] = ' '.join(sorted(set(normalize(result['q']).split())))
    for key in ['favorite','editable','date_unknown']:
        if result.get(key) != '1':
            result.pop(key, None)
    if result.get('date_field') == 'published':
        result.pop('date_field')
    result['batch_scope'] = args.get('batch_scope', 'recent')
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def get(db, args):
    if not args.get('batch'):
        return None
    return db.execute('SELECT * FROM reading_queries WHERE batch_id=? AND conditions_json=?',
                      (args['batch'], conditions(args))).fetchone()


def freeze(db, args, rows):
    if not args.get('batch'):
        return None
    # A concurrent request with the same conditions must reuse the first writer.
    def insert():
        db.execute('INSERT OR IGNORE INTO reading_queries VALUES(?,?,?,?,?)',
                   (uuid.uuid4().hex, args['batch'], conditions(args), json.dumps([r['id'] for r in rows]), now()))
    if db.in_transaction:
        insert()
    else:
        with db:
            insert()
    return get(db, args)


def confirmation(query, rows):
    return {'query': query['id'],
            'membership': hashlib.sha256(json.dumps([r['id'] for r in rows]).encode()).hexdigest()}


def validate_backup(db):
    from .translations import validate_calls
    validate_calls(db)
    for query in db.execute('SELECT * FROM reading_queries'):
        try:
            ids = json.loads(query['ids_json'])
            args = json.loads(query['conditions_json'])
            batch = db.execute('SELECT ids_json FROM reading_batches WHERE id=?', (query['batch_id'],)).fetchone()
            if (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
                    or len(ids) != len(set(ids)) or not set(ids).issubset(json.loads(batch['ids_json']))
                    or not isinstance(args, dict) or conditions(args) != query['conditions_json']):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ValueError('新增查找记录不完整。') from None
