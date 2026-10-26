"""Structured inclusion decisions and recorded search coverage for research collections."""
from pathlib import Path

from flask import abort

from .store import connect

SCHEMA_VERSION = 14


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute("ALTER TABLE collection_items ADD COLUMN disposition TEXT NOT NULL DEFAULT 'included' CHECK(disposition IN ('included','excluded'))")
            db.execute("ALTER TABLE collection_items ADD COLUMN rationale TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE collections ADD COLUMN scope_log_json TEXT NOT NULL DEFAULT '[]'")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('collection_scope_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def decision(data):
    disposition = data.get('disposition', 'included')
    rationale = data.get('rationale', '')
    if disposition not in ('included', 'excluded') or not isinstance(rationale, str) or len(rationale) > 40000:
        abort(400, '请选择纳入或排除，并填写有效理由。')
    rationale = rationale.strip()
    if disposition == 'excluded' and not rationale:
        abort(400, '排除资料需要填写理由。')
    return disposition, rationale


def search_log(value):
    from datetime import date
    fields = {'source', 'query', 'time_range', 'language', 'searched_on', 'outcome', 'notes'}
    if not isinstance(value, list) or len(value) > 1000:
        abort(400, '排查日志需要有效的记录列表，最多 1000 条。')
    result = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) - fields:
            abort(400, '排查日志字段格式不正确。')
        item = {}
        for key in fields:
            text = entry.get(key, '')
            if not isinstance(text, str) or len(text) > (40000 if key == 'notes' else 1000):
                abort(400, '排查日志字段格式不正确或内容过长。')
            item[key] = text.strip()
        if not (item['source'] or item['query']):
            abort(400, '排查日志需要填写来源或检索词。')
        if item['outcome'] not in ('found', 'zero_results', 'access_blocked'):
            abort(400, '请选择找到结果、无结果或访问受阻。')
        try:
            if date.fromisoformat(item['searched_on']).isoformat() != item['searched_on']:
                raise ValueError()
        except ValueError:
            abort(400, '请填写有效的实际检索日期。')
        result.append(item)
    return result


def validate_backup(db):
    import json
    from werkzeug.exceptions import HTTPException
    try:
        for row in db.execute('SELECT scope_log_json FROM collections'):
            search_log(json.loads(row['scope_log_json']))
        for row in db.execute('SELECT disposition,rationale FROM collection_items'):
            decision(dict(row))
        for row in db.execute("SELECT snapshot_json FROM revisions WHERE target_type='collection'"):
            snapshot = json.loads(row['snapshot_json'])
            if 'scope_log_json' in snapshot:
                search_log(json.loads(snapshot['scope_log_json']))
            if 'item_details' in snapshot:
                items = snapshot['item_details']
                if not isinstance(items, list):
                    raise ValueError('专题历史条目格式不正确。')
                ids = []
                for item in items:
                    if not isinstance(item, dict) or not isinstance(item.get('record_id'), str):
                        raise ValueError('专题历史条目格式不正确。')
                    decision(item)
                    ids.append(item['record_id'])
                    if not db.execute('SELECT 1 FROM records WHERE id=?', (item['record_id'],)).fetchone():
                        raise ValueError('专题历史资料不存在。')
                if len(set(ids)) != len(ids) or set(ids) != set(snapshot.get('item_ids', [])):
                    raise ValueError('专题历史条目与编号不一致。')
    except (HTTPException, TypeError, KeyError) as error:
        raise ValueError('专题排查日志或纳入／排除记录不完整。') from error
