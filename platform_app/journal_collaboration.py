"""Journal file archives inherit their content record's current access policy.

This business has no topic participants, lead qualification or review gate.
Files are immutable originals; a product selection records adoption, not review.
"""
import hashlib
import html
import json
import re
import uuid
from pathlib import Path

from flask import abort, jsonify, request, send_file

from . import handoff_files
from .record_revisions import check_version, validate_text
from .store import connect, now

SCHEMA_VERSION = 22
SCHEMA = [
    "CREATE TABLE journal_works(id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id), journal_id TEXT REFERENCES sources(id), journal_name TEXT NOT NULL, coverage TEXT NOT NULL, source_clue TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0), current_product_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE journal_work_events(id INTEGER PRIMARY KEY, work_id TEXT NOT NULL REFERENCES journal_works(id), actor_id TEXT NOT NULL REFERENCES users(id), version INTEGER NOT NULL CHECK(version>0), action TEXT NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(work_id,version))",
    "CREATE TABLE journal_submissions(id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES journal_works(id), version INTEGER NOT NULL CHECK(version>0), work_version INTEGER NOT NULL, material_kind TEXT NOT NULL CHECK(material_kind IN ('manuscript','review','product')), file_id TEXT UNIQUE NOT NULL REFERENCES handoff_files(id), uploader_id TEXT NOT NULL REFERENCES users(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(work_id,version), UNIQUE(work_id,uploader_id,request_id))",
    "CREATE TABLE journal_product_requests(work_id TEXT NOT NULL REFERENCES journal_works(id), actor_id TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL, request_hash TEXT NOT NULL, submission_id TEXT NOT NULL REFERENCES journal_submissions(id), result_version INTEGER NOT NULL, PRIMARY KEY(work_id,actor_id,request_id))",
]


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
            return
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA:
                db.execute(statement)
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('journal_collaboration_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def event(db, wid, actor, action):
    snapshot = dict(db.execute("SELECT * FROM journal_works WHERE id=?", (wid,)).fetchone())
    db.execute("INSERT INTO journal_work_events(work_id,actor_id,version,action,snapshot_json,created_at) VALUES (?,?,?,?,?,?)", (wid, actor, snapshot['version'], action, json.dumps(snapshot, ensure_ascii=False), now()))


def values(access, data, base=None):
    result = validate_text(data, ['journal_name', 'coverage', 'source_clue'], base)
    jid = data.get('journal_id', base['journal_id'] if base else None) or None
    if jid is not None:
        if not isinstance(jid, str):
            abort(400, '期刊编号格式不正确。')
        source = access.source(jid)
        if source['kind'] != 'journal':
            abort(400, '请选择既有期刊档案。')
        jid = source['id']
        result['journal_name'] = source['name']
    if not result['journal_name'] or not result['coverage']:
        abort(400, '请填写已知刊名与原刊卷期或覆盖范围；未知信息无需猜填。')
    return {**result, 'journal_id': jid}


class JournalWorks:
    def __init__(self, db, access):
        self.db, self.access = db, access

    def get(self, wid, edit=False):
        row = self.db.execute('SELECT * FROM journal_works WHERE id=?', (wid,)).fetchone()
        if not row:
            abort(404, '期刊编译不存在或当前无权查阅。')
        original = self.db.execute('SELECT * FROM records WHERE id=?', (row['record_id'],)).fetchone()
        if not original or not self.access.visible(original):
            abort(404, '期刊编译不存在或当前无权查阅。')
        record = self.access.get(row['record_id'], edit=edit)
        if record['kind'] not in {'directory_translation', 'compilation', 'research_report'}:
            abort(409, '关联内容已不属于目录译稿或个人成果，请核查内容身份。')
        return row, record

    def submissions(self, wid):
        self.get(wid)
        result = []
        for row in self.db.execute('SELECT s.*,f.name,f.bytes,f.sha256,u.name AS uploader_name FROM journal_submissions s JOIN handoff_files f ON f.id=s.file_id JOIN users u ON u.id=s.uploader_id WHERE work_id=? ORDER BY s.version DESC', (wid,)):
            item = {k: row[k] for k in row.keys() if k not in {'request_id', 'request_hash'}}
            item['file_url'] = f"/api/collaboration/journals/{wid}/submissions/{row['id']}/file"
            result.append(item)
        return result

    def detail(self, wid):
        row, record = self.get(wid)
        result = dict(row)
        if row['journal_id']:
            source = self.access.source(row['journal_id'])
            result.update(journal_id=source['id'], journal_name=source['name'])
        result.update(record_id=record['id'], record_kind=record['kind'], record_title=record['title'], can_edit=self.access.editable(record), visibility=record['visibility'], submissions=self.submissions(wid))
        return result


def fingerprint(data, uploaded):
    name, _, raw = uploaded
    return hashlib.sha256(json.dumps({'name': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'version': data['version'], 'material_kind': data['material_kind'], 'note': data.get('note', '').strip()}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def product_fingerprint(version, sid, note):
    return hashlib.sha256(json.dumps({'version':version,'submission_id':sid,'note':note},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def referenced_files(db):
    return {r[0] for r in db.execute('SELECT file_id FROM journal_submissions')}


def export_projection(db, access, record_ids=None, work_ids=None):
    """Only authorized journal archives; every historical original stays explicit."""
    service = JournalWorks(db, access)
    result = []
    for row in db.execute('SELECT * FROM journal_works ORDER BY updated_at DESC,id'):
        if work_ids is not None and row['id'] not in work_ids:
            continue
        original = db.execute('SELECT * FROM records WHERE id=?', (row['record_id'],)).fetchone()
        if not original or not access.visible(original):
            continue
        record = access.get(row['record_id'])
        if record_ids is not None and record['id'] not in record_ids:
            continue
        item = service.detail(row['id'])
        item.pop('can_edit')
        item['path'] = 'journal-works/' + row['id'] + '.html'
        item['history'] = []
        for event_row in db.execute('SELECT e.*,u.name AS actor_name FROM journal_work_events e JOIN users u ON u.id=e.actor_id WHERE work_id=? ORDER BY version', (row['id'],)):
            event_item = dict(event_row)
            event_item['snapshot'] = json.loads(event_item.pop('snapshot_json'))
            item['history'].append(event_item)
        for submission in item['submissions']:
            original_file = db.execute('SELECT * FROM handoff_files WHERE id=?', (submission['file_id'],)).fetchone()
            submission.pop('file_url')
            submission['path'] = 'journal-originals/' + original_file['stored_name']
        result.append(item)
    return result


def export_html(item):
    content = '<p><a href="../index.html">返回目录</a></p><p>'+html.escape(item['journal_name']+' · '+item['coverage'])+'</p>'
    content += '<pre>'+html.escape(item['source_clue'])+'</pre><p>成品采用记录不是主题负责人审稿结论。所有文件均为本机写作后提交的原件。</p>'
    for submission in item['submissions']:
        label = {'manuscript':'编译稿','review':'审稿材料','product':'成品文件'}[submission['material_kind']]
        content += '<section><h2>'+label+' v'+str(submission['version'])+(' · 当前成品' if submission['id']==item['current_product_id'] else '')+'</h2><a href="../'+submission['path']+'">'+html.escape(submission['name'])+'</a><p>'+html.escape(submission['uploader_name']+' · '+submission['created_at'])+'</p><pre>'+html.escape(submission['note'])+'</pre><p>SHA-256：'+submission['sha256']+'</p></section>'
    content += '<h2>工作与采用历史</h2><pre>'+html.escape(json.dumps(item['history'],ensure_ascii=False,indent=2))+'</pre>'
    return content


def write_export_files(archive, data_dir, db, works):
    for work in works:
        for submission in work['submissions']:
            original = db.execute('SELECT * FROM handoff_files WHERE id=?', (submission['file_id'],)).fetchone()
            archive.writestr(submission['path'], handoff_files.original_path(data_dir,original).read_bytes())


def validate_backup(db):
    for work in db.execute('SELECT * FROM journal_works'):
        events = db.execute('SELECT * FROM journal_work_events WHERE work_id=? ORDER BY version', (work['id'],)).fetchall()
        if not events or [e['version'] for e in events] != list(range(1,work['version']+1)):
            raise ValueError('期刊工作历史不连续。')
        submissions = db.execute('SELECT s.*,f.name,f.sha256,f.uploader_id AS file_uploader FROM journal_submissions s JOIN handoff_files f ON f.id=s.file_id WHERE work_id=? ORDER BY s.version', (work['id'],)).fetchall()
        if [s['version'] for s in submissions] != list(range(1,len(submissions)+1)):
            raise ValueError('期刊文件版本不连续。')
        snapshots = {}
        for e in events:
            try:
                snap = json.loads(e['snapshot_json'])
                if (set(snap) != set(work.keys()) or snap['id'] != work['id'] or snap['record_id'] != work['record_id']
                        or snap['version'] != e['version'] or not snap['journal_name'].strip() or not snap['coverage'].strip()
                        or (snap['journal_id'] and not db.execute('SELECT 1 FROM sources WHERE id=?',(snap['journal_id'],)).fetchone())):
                    raise ValueError()
                product = next((s for s in submissions if s['id']==snap['current_product_id']),None)
                if snap['current_product_id'] and (not product or product['material_kind']=='review' or product['work_version']>=e['version']):
                    raise ValueError()
                snapshots[e['version']] = snap
            except (ValueError,KeyError,TypeError,AttributeError):
                raise ValueError('期刊工作历史或采用关系无效。') from None
        if snapshots[work['version']] != dict(work):
            raise ValueError('期刊工作与最新历史不一致。')
        versions = set()
        for s in submissions:
            expected = hashlib.sha256(json.dumps({'name':s['name'],'sha256':s['sha256'],'version':s['work_version'],'material_kind':s['material_kind'],'note':s['note']},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            event_row = next((e for e in events if e['version']==s['work_version']+1),None)
            if (s['work_version'] not in snapshots or s['work_version'] in versions or not event_row
                    or event_row['actor_id']!=s['uploader_id'] or s['file_uploader']!=s['uploader_id']
                    or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',s['request_id']) or expected!=s['request_hash']
                    or event_row['action'] != '保存'+{'manuscript':'编译稿','review':'审稿材料','product':'成品文件'}[s['material_kind']]):
                raise ValueError('期刊文件归属、来历或提交身份无效。')
            versions.add(s['work_version'])
        requests = db.execute('SELECT * FROM journal_product_requests WHERE work_id=?',(work['id'],)).fetchall()
        adoption_versions = {e['version'] for e in events if e['action'] == '采用为当前成品' or e['action'].startswith('采用为当前成品：')}
        if adoption_versions != {r['result_version'] for r in requests} or len(adoption_versions) != len(requests):
            raise ValueError('期刊成品采用历史缺少对应请求。')
        for r in requests:
            e = next((e for e in events if e['version']==r['result_version']),None)
            note = e['action'][len('采用为当前成品：'):] if e and e['action'].startswith('采用为当前成品：') else ''
            if (not e or e['actor_id']!=r['actor_id'] or snapshots[r['result_version']]['current_product_id']!=r['submission_id']
                    or e['action'] not in {'采用为当前成品','采用为当前成品：'+note}
                    or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',r['request_id'])
                    or product_fingerprint(r['result_version']-1,r['submission_id'],note)!=r['request_hash']):
                raise ValueError('期刊成品采用的请求或版本依据无效。')


def register(app, ctx):
    def service():
        return JournalWorks(ctx.db(), ctx.records())

    @app.get('/api/collaboration/journals/options')
    def journal_content_options():
        access = ctx.records()
        return jsonify(items=[{'id':r['id'],'title':r['title'],'kind':r['kind']} for r in ctx.db().execute("SELECT * FROM records WHERE kind IN ('directory_translation','compilation','research_report') AND merged_into IS NULL ORDER BY updated_at DESC") if access.editable(r)])

    @app.get('/api/collaboration/journals')
    def journal_works_list():
        access = ctx.records()
        items = []
        for row in ctx.db().execute('SELECT w.* FROM journal_works w ORDER BY updated_at DESC,id'):
            record = ctx.db().execute('SELECT * FROM records WHERE id=?', (row['record_id'],)).fetchone()
            if record and access.visible(record):
                items.append(service().detail(row['id']))
        return jsonify(items=items)

    @app.post('/api/collaboration/journals')
    def journal_work_create():
        data, access = ctx.body(), ctx.records()
        props = values(access, data)
        if any(data.get(k) for k in ['topic_id', 'lead_id', 'participant_ids']):
            abort(400, '期刊工作不挂靠主题或主题参与者。')
        wid = uuid.uuid4().hex

        def insert(rid):
            stamp = now()
            ctx.db().execute('INSERT INTO journal_works VALUES (?,?,?,?,?,?,1,NULL,?,?)', (wid, rid, props['journal_id'], props['journal_name'], props['coverage'], props['source_clue'], stamp, stamp))
            event(ctx.db(), wid, ctx.user()['id'], '建立期刊工作')

        if data.get('record_id'):
            with handoff_files.transaction(ctx.db()):
                record = access.get(data['record_id'], edit=True)
                if record['kind'] not in {'directory_translation', 'compilation', 'research_report'}:
                    abort(400, '请选择目录译稿或个人成果。')
                insert(record['id'])
        else:
            kind = data.get('content_kind', 'directory_translation')
            if kind not in {'directory_translation', 'compilation', 'research_report'}:
                abort(400, '内容责任类型不正确。')
            access.create({'kind': kind, 'title': props['journal_name']+' · '+props['coverage'], 'publication_title': props['journal_name'], 'unresolved_refs': props['source_clue'], 'authors': ctx.user()['name'], 'coverage': props['coverage'], 'serial_id': props['journal_id'], 'related_source_ids': [props['journal_id']] if props['journal_id'] else [], 'visibility': data.get('visibility', 'shared')}, after_create=insert)
        return jsonify(id=wid), 201

    @app.get('/api/collaboration/journals/<wid>')
    def journal_work_detail(wid):
        return jsonify(service().detail(wid))

    @app.put('/api/collaboration/journals/<wid>')
    def journal_work_edit(wid):
        data = ctx.body()
        with handoff_files.transaction(ctx.db()):
            row, _ = service().get(wid, edit=True)
            check_version(data, row)
            if any(k in data for k in ['record_id','current_product_id','topic_id','lead_id','participant_ids']):
                abort(400, '内容身份、成品采用和主题职责不能由工作信息更改。')
            props = values(ctx.records(), data, row)
            ctx.db().execute('UPDATE journal_works SET journal_id=?,journal_name=?,coverage=?,source_clue=?,version=version+1,updated_at=? WHERE id=?', (props['journal_id'],props['journal_name'],props['coverage'],props['source_clue'],now(),wid))
            event(ctx.db(), wid, ctx.user()['id'], '补充期刊与覆盖范围')
        return jsonify(id=wid)

    @app.get('/api/collaboration/journals/<wid>/history')
    def journal_work_history(wid):
        service().get(wid)
        items = []
        for row in ctx.db().execute('SELECT e.*,u.name AS actor_name FROM journal_work_events e JOIN users u ON u.id=e.actor_id WHERE work_id=? ORDER BY e.version DESC', (wid,)):
            item = dict(row)
            item['snapshot'] = json.loads(item.pop('snapshot_json'))
            items.append(item)
        return jsonify(items=items)

    @app.post('/api/collaboration/journals/<wid>/product')
    def journal_work_product(wid):
        data = ctx.body()
        with handoff_files.transaction(ctx.db()):
            row, _ = service().get(wid, edit=True)
            sid = data.get('submission_id')
            if not isinstance(sid, str) or type(data.get('version')) is not int:
                abort(400, '请选择实际提交的成品原件。')
            note = validate_text(data,['note'])['note']
            digest = product_fingerprint(data['version'],sid,note)
            request_id = data.get('request_id', 'product-'+digest)
            if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id):
                abort(400,'采用请求编号不正确。')
            old = ctx.db().execute('SELECT * FROM journal_product_requests WHERE work_id=? AND actor_id=? AND request_id=?',(wid,ctx.user()['id'],request_id)).fetchone()
            if old:
                if old['request_hash']!=digest:
                    abort(409,'同一成品采用请求内容发生变化。')
                return jsonify(id=wid)
            check_version(data, row)
            submission = ctx.db().execute('SELECT * FROM journal_submissions WHERE work_id=? AND id=?', (wid,sid)).fetchone()
            if not submission or submission['material_kind'] == 'review':
                abort(400, '成品须对应本工作实际提交的编译稿或成品文件。')
            ctx.db().execute('UPDATE journal_works SET current_product_id=?,version=version+1,updated_at=? WHERE id=?', (sid,now(),wid))
            event(ctx.db(),wid,ctx.user()['id'],'采用为当前成品'+('：'+note if note else ''))
            ctx.db().execute('INSERT INTO journal_product_requests VALUES (?,?,?,?,?,?)',(wid,ctx.user()['id'],request_id,digest,sid,row['version']+1))
        return jsonify(id=wid)

    @app.post('/api/collaboration/journals/<wid>/submissions')
    def journal_work_submit(wid):
        # Authorize before reading even the selected upload.
        service().get(wid, edit=True)
        data = ctx.body()
        if (type(data.get('version')) is not int or not isinstance(data.get('request_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', data['request_id']) or data.get('material_kind') not in {'manuscript', 'review', 'product'}):
            abort(400, '提交版本、材料类型或请求编号不正确。')
        validate_text(data, ['note'])
        uploaded = handoff_files.read_upload(request.files.get('file'))
        digest = fingerprint(data, uploaded)
        with handoff_files.transaction(ctx.db()) as created:
            row, _ = service().get(wid, edit=True)
            actor = ctx.user()['id']
            old = ctx.db().execute('SELECT * FROM journal_submissions WHERE work_id=? AND uploader_id=? AND request_id=?', (wid, actor, data['request_id'])).fetchone()
            if old:
                if old['request_hash'] != digest:
                    abort(409, '同一提交请求内容发生变化，请核对后重新提交。')
                return jsonify(id=old['id'], version=old['version'])
            check_version(data, row)
            seq = ctx.db().execute('SELECT COALESCE(MAX(version),0)+1 FROM journal_submissions WHERE work_id=?', (wid,)).fetchone()[0]
            fid = handoff_files.save_original(ctx.db(), ctx.data_dir, actor, uploaded, created)
            sid = uuid.uuid4().hex
            ctx.db().execute('INSERT INTO journal_submissions VALUES (?,?,?,?,?,?,?,?,?,?,?)', (sid, wid, seq, row['version'], data['material_kind'], fid, actor, data.get('note', '').strip(), data['request_id'], digest, now()))
            ctx.db().execute('UPDATE journal_works SET version=version+1,updated_at=? WHERE id=?', (now(), wid))
            event(ctx.db(), wid, actor, '保存'+{'manuscript':'编译稿','review':'审稿材料','product':'成品文件'}[data['material_kind']])
        return jsonify(id=sid, version=seq), 201

    @app.get('/api/collaboration/journals/<wid>/submissions/<sid>/file')
    def journal_original(wid, sid):
        service().get(wid)
        row = ctx.db().execute('SELECT f.* FROM journal_submissions s JOIN handoff_files f ON f.id=s.file_id WHERE work_id=? AND s.id=?', (wid, sid)).fetchone()
        if not row:
            abort(404)
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row['name'])
