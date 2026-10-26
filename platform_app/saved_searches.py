"""Account-owned query settings. Result computation stays in the library query."""
import json
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from .record_revisions import KINDS
from flask import abort, jsonify, request
from .store import connect, now

SCHEMA_VERSION = 11
CONDITION_KEYS = {'q','kind','source','source_section','source_group','source_country','source_international',
                  'language','country','status','from','to','collection','sort','favorite','editable','evidence_of'}


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute('''CREATE TABLE saved_searches (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
                name_key TEXT NOT NULL, conditions_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner_id,name_key))''')
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'",(str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('saved_searches_migration_backup',?)",(str(backup),))
    finally:
        db.close()


def conditions(value):
    if not isinstance(value, dict) or set(value)-CONDITION_KEYS:
        abort(400, '检索条件包含不支持的字段。')
    result = {}
    for key, item in value.items():
        if not isinstance(item, str) or len(item) > (1000 if key=='q' else 200):
            abort(400, '检索条件格式不正确或内容过长。')
        if item.strip():
            result[key] = item.strip()
    enums = {'kind':KINDS,'sort':{'date','updated','title'},'status':{'pending','verified'},
             'favorite':{'1'},'editable':{'1'},'source_group':{'institution','journal','publication'},
             'source_international':{'yes','no','unknown'},
             'source_section':{'published','associated','translations','outputs'}}
    for key, allowed in enums.items():
        if key in result and result[key] not in allowed:
            abort(400, '检索条件的选项无效：'+key)
    for key in ('from','to'):
        if key in result:
            try:
                if date.fromisoformat(result[key]).isoformat()!=result[key]:
                    raise ValueError()
            except ValueError:
                abort(400, '发布日期格式不正确。')
    if result.get('from','') > result.get('to','9999-12-31'):
        abort(400, '发布日期起止范围不正确。')
    return result


def get(db, owner, sid):
    row = db.execute('SELECT * FROM saved_searches WHERE id=? AND owner_id=?', (sid, owner)).fetchone()
    if not row:
        abort(404, '检索不存在或不属于当前账号。')
    result = dict(row)
    result['conditions'] = json.loads(result.pop('conditions_json'))
    result.pop('name_key')
    return result


def resolve(db, owner, args):
    if 'saved_search' not in args:
        return args
    if not args['saved_search']:
        abort(400, '检索编号不能为空。')
    saved = get(db, owner, args['saved_search'])
    # Persisted scope cannot be weakened by a forged query-string override.
    return {**saved['conditions'], **{key:args[key] for key in ('page','size') if key in args}}


def register(app, ctx):
    db, user, body = ctx.db, ctx.user, ctx.body

    @app.get('/api/saved-searches')
    def saved_search_list():
        q = request.args.get('q','').strip().casefold()
        try:
            page = max(1,int(request.args.get('page',1)))
            size = min(50,max(1,int(request.args.get('size',20))))
        except ValueError:
            abort(400, '页码不正确。')
        if len(q)>120:
            abort(400, '检索名称过长。')
        rows = [r for r in db().execute('SELECT id,name_key FROM saved_searches WHERE owner_id=? ORDER BY updated_at DESC,id', (user()['id'],)) if q in r['name_key']]
        return jsonify(items=[get(db(),user()['id'],r['id']) for r in rows[(page-1)*size:page*size]],total=len(rows),page=page,size=size)

    @app.get('/api/saved-searches/<sid>')
    def saved_search_detail(sid):
        return jsonify(get(db(),user()['id'],sid))

    @app.post('/api/saved-searches')
    def create_saved_search():
        data = body()
        value = conditions(data.get('conditions'))
        ctx.filtered_records(value)
        name = data.get('name')
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 120:
            abort(400, '检索名称需要 1—120 个字符。')
        sid = uuid.uuid4().hex
        try:
            with db():
                db().execute('INSERT INTO saved_searches VALUES (?,?,?,?,?,1,?,?)',
                             (sid,user()['id'],name.strip(),name.strip().casefold(),json.dumps(value,ensure_ascii=False),now(),now()))
        except sqlite3.IntegrityError:
            abort(409, '检索名称已存在，请换一个名称。')
        return jsonify(get(db(),user()['id'],sid)),201

    @app.route('/api/saved-searches/<sid>',methods=['PUT','DELETE'])
    def change_saved_search(sid):
        data = body()
        # BEGIN IMMEDIATE keeps version check and write in the same SQLite transaction.
        db().execute('BEGIN IMMEDIATE')
        with db():
            current = get(db(),user()['id'],sid)
            if type(data.get('version')) is not int or data['version'] != current['version']:
                abort(409, '此检索已在其他窗口修改。输入已保留，请重新读取后再操作。')
            if request.method=='DELETE':
                db().execute('DELETE FROM saved_searches WHERE id=? AND owner_id=?',(sid,user()['id']))
                return jsonify(ok=True)
            name = data.get('name',current['name'])
            if not isinstance(name,str) or not 1<=len(name.strip())<=120:
                abort(400, '检索名称需要 1—120 个字符。')
            if db().execute('SELECT 1 FROM saved_searches WHERE owner_id=? AND name_key=? AND id<>?', (user()['id'],name.strip().casefold(),sid)).fetchone():
                abort(409, '检索名称已存在，请换一个名称。')
            value = conditions(data.get('conditions',current['conditions']))
            # Renaming invalidated scopes remains possible; execution still rejects them.
            if 'conditions' in data:
                ctx.filtered_records(value)
            db().execute('UPDATE saved_searches SET name=?,name_key=?,conditions_json=?,version=version+1,updated_at=? WHERE id=? AND owner_id=?',
                         (name.strip(),name.strip().casefold(),json.dumps(value,ensure_ascii=False),now(),sid,user()['id']))
        return jsonify(get(db(),user()['id'],sid))


def validate_backup(db):
    from werkzeug.exceptions import HTTPException
    try:
        for row in db.execute('SELECT * FROM saved_searches'):
            if not row['name'].strip() or len(row['name'])>120 or row['name_key']!=row['name'].strip().casefold() or row['version']<1:
                raise ValueError('个人检索字段不完整。')
            if conditions(json.loads(row['conditions_json'])) != json.loads(row['conditions_json']):
                raise ValueError('个人检索条件不完整。')
    except (HTTPException,TypeError,json.JSONDecodeError) as error:
        raise ValueError('个人检索条件损坏。') from error
