"""Direct shared journal results: one transactional interface owns each archive.

No record, work, review or adoption is invented. Series and immutable originals
belong only to this archive; existing journal works retain their own policies.
"""
import hashlib
import html
import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from flask import abort, jsonify, request, send_file

from . import handoff_files
from .record_revisions import check_version, validate_text
from .store import connect, now

SCHEMA_VERSION = 28
SCHEMA = [
    "CREATE TABLE journal_results(id TEXT PRIMARY KEY,journal_id TEXT REFERENCES sources(id),journal_name TEXT NOT NULL,year INTEGER NOT NULL CHECK(year BETWEEN 1 AND 9999),issue TEXT NOT NULL,authors TEXT NOT NULL,note TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "CREATE TABLE journal_result_series(id TEXT PRIMARY KEY,result_id TEXT NOT NULL REFERENCES journal_results(id),created_at TEXT NOT NULL)",
    "CREATE TABLE journal_result_versions(id TEXT PRIMARY KEY,series_id TEXT NOT NULL REFERENCES journal_result_series(id),version INTEGER NOT NULL CHECK(version>0),file_id TEXT UNIQUE NOT NULL REFERENCES handoff_files(id),actor_id TEXT NOT NULL REFERENCES users(id),note TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(series_id,version))",
    "CREATE TABLE journal_result_events(id INTEGER PRIMARY KEY,result_id TEXT NOT NULL REFERENCES journal_results(id),version INTEGER NOT NULL CHECK(version>0),actor_id TEXT NOT NULL REFERENCES users(id),action TEXT NOT NULL,snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(result_id,version))",
    "CREATE TABLE journal_result_requests(actor_id TEXT NOT NULL REFERENCES users(id),request_id TEXT NOT NULL,result_id TEXT NOT NULL REFERENCES journal_results(id),result_version INTEGER NOT NULL,request_hash TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(actor_id,request_id))",
]


def migrate(data_dir):
    db = connect(Path(data_dir)/'platform.sqlite3')
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
            return
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute('BEGIN IMMEDIATE')
            for statement in SCHEMA:
                db.execute(statement)
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'",(str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES('journal_results_migration_backup',?)",(str(backup),))
    finally:
        db.close()


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def metadata(data, access, base=None):
    props = validate_text(data,['journal_name','issue','authors','note'],base)
    year = data.get('year',base['year'] if base else None)
    if type(year) is not int or not 1 <= year <= 9999 or not props['journal_name'] or not props['issue']:
        abort(400,'请填写刊名、年份和成果期次。')
    jid = data.get('journal_id',base['journal_id'] if base else None) or None
    if jid is not None:
        if not isinstance(jid,str):
            abort(400,'请选择已有期刊档案。')
        source = access.source(jid)
        if source['kind'] != 'journal':
            abort(400,'请选择已有期刊档案。')
        jid = source['id']
    return {**props,'year':year,'journal_id':jid}


class JournalResults:
    """Authenticated members share the archive; all mutations own one transaction."""
    def __init__(self, db, actor, access, data_dir):
        self.db,self.actor,self.access,self.data_dir = db,actor,access,Path(data_dir)

    def get(self,rid):
        row = self.db.execute('SELECT * FROM journal_results WHERE id=?',(rid,)).fetchone()
        if not row:
            abort(404,'期刊成果不存在。')
        return row

    def snapshot(self,rid):
        return {**dict(self.get(rid)),'files':{r['id']:self.db.execute('SELECT MAX(version) FROM journal_result_versions WHERE series_id=?',(r['id'],)).fetchone()[0]
                for r in self.db.execute('SELECT * FROM journal_result_series WHERE result_id=? ORDER BY id',(rid,))}}

    def detail(self,rid):
        item = dict(self.get(rid))
        if item['journal_id']:
            item['journal_id'] = self.access.source(item['journal_id'])['id']
        item['files'] = []
        for series in self.db.execute('SELECT * FROM journal_result_series WHERE result_id=? ORDER BY created_at,id',(rid,)):
            versions = []
            for row in self.db.execute('SELECT v.*,f.name,f.bytes,f.sha256,u.name AS actor_name FROM journal_result_versions v JOIN handoff_files f ON f.id=v.file_id JOIN users u ON u.id=v.actor_id WHERE series_id=? ORDER BY version DESC',(series['id'],)):
                version = dict(row)
                version['file_url'] = f"/api/journal-results/{rid}/files/{series['id']}/versions/{row['version']}/file"
                version['preview_url'] = version['file_url'].removesuffix('/file')+'/preview'
                versions.append(version)
            item['files'].append({**dict(series),'versions':versions})
        return item

    def history(self,rid):
        self.get(rid)
        return [{**{k:r[k] for k in r.keys() if k!='snapshot_json'},'snapshot':json.loads(r['snapshot_json'])}
                for r in self.db.execute('SELECT e.*,u.name AS actor_name FROM journal_result_events e JOIN users u ON u.id=e.actor_id WHERE result_id=? ORDER BY version DESC',(rid,))]

    def original(self,rid,sid,version):
        self.get(rid)
        row = self.db.execute('SELECT f.* FROM journal_result_versions v JOIN journal_result_series s ON s.id=v.series_id JOIN handoff_files f ON f.id=v.file_id WHERE s.result_id=? AND s.id=? AND v.version=?',(rid,sid,version)).fetchone()
        if not row:
            abort(404,'文件版本不存在。')
        return row

    def save(self,action,data,uploads=(),rid=None):
        key = data.get('request_id')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):
            abort(400,'保存请求编号无效。')
        payload = {'action':action,'target':rid,'data':data,'files':[{'name':u[0],'sha256':hashlib.sha256(u[2]).hexdigest()} for u in uploads]}
        fingerprint = digest(payload)
        with handoff_files.transaction(self.db) as created:
            old = self.db.execute('SELECT * FROM journal_result_requests WHERE actor_id=? AND request_id=?',(self.actor['id'],key)).fetchone()
            if old:
                if old['request_hash'] != fingerprint:
                    abort(409,'同一保存请求的内容已改变，请读取最新状态后重试。')
                return {'id':old['result_id'],'version':old['result_version'],'replayed':True}
            base = self.get(rid) if rid else None
            if base:
                check_version(data,base)
            if action in {'create','metadata','restore'}:
                source = data
                if action=='restore':
                    if type(data.get('history_version')) is not int or data['history_version']<1:
                        abort(400,'请选择有效的期次历史版本。')
                    event = self.db.execute('SELECT snapshot_json FROM journal_result_events WHERE result_id=? AND version=?',(rid,data.get('history_version'))).fetchone()
                    if not event:
                        abort(404,'历史版本不存在。')
                    source = json.loads(event[0])
                props = metadata(source,self.access,base)
                candidates = self.db.execute('SELECT id,journal_id,journal_name FROM journal_results WHERE year=? AND issue=? AND id<>?',(props['year'],props['issue'],rid or ''))
                duplicate = next((row for row in candidates if
                                  (self.access.source(row['journal_id'])['id']==props['journal_id'] if props['journal_id'] and row['journal_id']
                                   else row['journal_name'].strip().casefold()==props['journal_name'].casefold())),None)
                if duplicate:
                    abort(409,'相同期刊、年份与成果期次已存在，请打开已有一期添加文件。编号：'+duplicate['id'])
                stamp = now()
                if not base:
                    if not uploads:
                        abort(400,'请选择首批成果文件。')
                    rid = uuid.uuid4().hex
                    self.db.execute('INSERT INTO journal_results VALUES(?,?,?,?,?,?,?,1,?,?)',(rid,props['journal_id'],props['journal_name'],props['year'],props['issue'],props['authors'],props['note'],stamp,stamp))
                else:
                    self.db.execute('UPDATE journal_results SET journal_id=?,journal_name=?,year=?,issue=?,authors=?,note=? WHERE id=?',(props['journal_id'],props['journal_name'],props['year'],props['issue'],props['authors'],props['note'],rid))
            if action in {'create','files','file_restore'}:
                sid = data.get('series_id')
                if sid is not None and (not isinstance(sid,str) or not sid):
                    abort(400,'文件编号格式不正确。')
                if sid and not self.db.execute('SELECT 1 FROM journal_result_series WHERE id=? AND result_id=?',(sid,rid)).fetchone():
                    abort(404,'本期中没有该文件。')
                if action=='file_restore':
                    if not sid or type(data.get('file_version')) is not int or data['file_version']<1:
                        abort(400,'请选择需要恢复的文件。')
                    old_file = self.original(rid,sid,data.get('file_version'))
                    uploads = [(old_file['name'],Path(old_file['stored_name']).suffix,handoff_files.original_path(self.data_dir,old_file).read_bytes())]
                if not uploads or (sid and len(uploads)!=1):
                    abort(400,'请选择文件；更新一份文件时只选择一个原件。')
                for uploaded in uploads:
                    series_id = sid or uuid.uuid4().hex
                    if not sid:
                        self.db.execute('INSERT INTO journal_result_series VALUES(?,?,?)',(series_id,rid,now()))
                    seq = self.db.execute('SELECT COALESCE(MAX(version),0)+1 FROM journal_result_versions WHERE series_id=?',(series_id,)).fetchone()[0]
                    fid = handoff_files.save_original(self.db,self.data_dir,self.actor['id'],uploaded,created)
                    note = validate_text(data,['file_note'])['file_note']
                    self.db.execute('INSERT INTO journal_result_versions VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,series_id,seq,fid,self.actor['id'],note,now()))
            if base:
                self.db.execute('UPDATE journal_results SET version=version+1,updated_at=? WHERE id=?',(now(),rid))
            snapshot = self.snapshot(rid)
            label = {'create':'保存一期成果','metadata':'修改期次信息','restore':'恢复期次信息','file_restore':'恢复文件为新版本','files':'更新文件' if data.get('series_id') else '添加并列文件'}[action]
            self.db.execute('INSERT INTO journal_result_events(result_id,version,actor_id,action,snapshot_json,created_at) VALUES(?,?,?,?,?,?)',(rid,snapshot['version'],self.actor['id'],label,json.dumps(snapshot,ensure_ascii=False),now()))
            self.db.execute('INSERT INTO journal_result_requests VALUES(?,?,?,?,?,?)',(self.actor['id'],key,rid,snapshot['version'],fingerprint,json.dumps(payload,ensure_ascii=False)))
        return {'id':rid,'version':snapshot['version'],'replayed':False}


def referenced_files(db):
    return {r[0] for r in db.execute('SELECT file_id FROM journal_result_versions')}


def export_projection(service, ids=None):
    items = []
    for row in service.db.execute('SELECT id FROM journal_results ORDER BY year DESC,issue,id'):
        if ids is not None and row['id'] not in ids:
            continue
        item = service.detail(row['id'])
        item['history'] = service.history(row['id'])
        item['path'] = 'journal-results/'+row['id']+'.html'
        for series in item['files']:
            for version in series['versions']:
                original = service.original(row['id'],series['id'],version['version'])
                version['path'] = 'journal-result-originals/'+original['stored_name']
                version.pop('file_url')
                version.pop('preview_url')
        items.append(item)
    return items


def write_export(archive,service,items):
    for item in items:
        content = '<!doctype html><html lang="zh"><meta charset="utf-8"><title>期刊成果</title><a href="../index.html">返回目录</a><h1>'+html.escape(item['journal_name'])+'</h1><p>'+html.escape(str(item['year'])+' · '+item['issue'])+'</p><pre>'+html.escape(item['authors']+'\n'+item['note'])+'</pre>'
        for series in item['files']:
            for version in series['versions']:
                content += '<p><a href="../'+version['path']+'">'+html.escape(version['name'])+'</a> · v'+str(version['version'])+' · '+html.escape(version['actor_name']+' · '+version['created_at'])+'</p>'
                row = service.original(item['id'],series['id'],version['version'])
                archive.writestr(version['path'],handoff_files.original_path(service.data_dir,row).read_bytes())
        content += '<h2>修改历史</h2><pre>'+html.escape(json.dumps(item['history'],ensure_ascii=False,indent=2))+'</pre></html>'
        archive.writestr(item['path'],content)


def validate_backup(db):
    """Reject orphan/foreign originals, discontinuous histories and forged snapshots."""
    try:
        _validate_backup(db)
    except (KeyError,TypeError,AttributeError,IndexError):
        raise ValueError('期刊成果历史或请求格式无效。') from None


def _validate_backup(db):
    for result in db.execute('SELECT * FROM journal_results'):
        if not re.fullmatch(r'[a-f0-9]{32}',result['id']):
            raise ValueError('期刊成果编号无效。')
        events = db.execute('SELECT * FROM journal_result_events WHERE result_id=? ORDER BY version',(result['id'],)).fetchall()
        if [r['version'] for r in events] != list(range(1,result['version']+1)):
            raise ValueError('期刊成果历史不连续。')
        series = db.execute('SELECT * FROM journal_result_series WHERE result_id=?',(result['id'],)).fetchall()
        if not series:
            raise ValueError('期刊成果缺少首批文件。')
        latest,seen = {},{}
        for s in series:
            if not re.fullmatch(r'[a-f0-9]{32}',s['id']):
                raise ValueError('期刊成果文件系列编号无效。')
            versions = db.execute('SELECT v.*,f.uploader_id FROM journal_result_versions v JOIN handoff_files f ON f.id=v.file_id WHERE series_id=? ORDER BY version',(s['id'],)).fetchall()
            if not versions or [v['version'] for v in versions] != list(range(1,len(versions)+1)) or any(v['actor_id']!=v['uploader_id'] or not re.fullmatch(r'[a-f0-9]{32}',v['id']) for v in versions):
                raise ValueError('期刊成果文件版本或操作者无效。')
            latest[s['id']] = len(versions)
        for e in events:
            try:
                snap = json.loads(e['snapshot_json'])
                if (set(snap) != {*result.keys(),'files'} or snap['id']!=result['id'] or snap['version']!=e['version']
                        or type(snap['year']) is not int or not 1 <= snap['year'] <= 9999
                        or not snap['journal_name'].strip() or not snap['issue'].strip()
                        or (snap['journal_id'] and not db.execute("SELECT 1 FROM sources WHERE id=? AND kind='journal'",(snap['journal_id'],)).fetchone())
                        or not snap['files'] or set(seen)-set(snap['files'])
                        or any(k not in latest or type(v) is not int or not 1 <= v <= latest[k] or v < seen.get(k,1) or v > seen.get(k,0)+1 for k,v in snap['files'].items())):
                    raise ValueError()
                seen = snap['files']
            except (ValueError,TypeError,KeyError,AttributeError):
                raise ValueError('期刊成果历史快照无效。') from None
        if seen != latest or any(snap[k] != result[k] for k in result.keys()):
            raise ValueError('期刊成果当前状态与历史不一致。')
        requests = db.execute('SELECT * FROM journal_result_requests WHERE result_id=? ORDER BY result_version',(result['id'],)).fetchall()
        if [r['result_version'] for r in requests] != [e['version'] for e in events]:
            raise ValueError('期刊成果保存请求缺失。')
        for r,e in zip(requests,events):
            try:
                payload = json.loads(r['payload_json'])
                if (digest(payload)!=r['request_hash'] or r['actor_id']!=e['actor_id'] or payload['data']['request_id']!=r['request_id']
                        or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',r['request_id'])):
                    raise ValueError()
            except (ValueError,TypeError,KeyError):
                raise ValueError('期刊成果保存请求无效。') from None
        previous = {}
        for r,e in zip(requests,events):
            payload = json.loads(r['payload_json'])
            snap = json.loads(e['snapshot_json'])
            action,data = payload['action'],payload['data']
            expected_action = {'create':'保存一期成果','metadata':'修改期次信息','restore':'恢复期次信息',
                               'file_restore':'恢复文件为新版本','files':'更新文件' if data.get('series_id') else '添加并列文件'}.get(action)
            if (not expected_action or e['action']!=expected_action
                    or payload['target']!=(None if action=='create' else result['id'])
                    or (action=='create')!=(e['version']==1)
                    or (action!='create' and data.get('version')!=e['version']-1)):
                raise ValueError('期刊成果保存请求与历史动作不一致。')
            changed = {sid:v for sid,v in snap['files'].items() if v!=previous.get(sid)}
            if action in {'metadata','restore'} and changed:
                raise ValueError('期次信息更改不能替换原件。')
            if action in {'create','files','file_restore'}:
                sid = data.get('series_id')
                if not changed or (sid and (set(changed)!={sid} or sid not in previous)) or (not sid and set(changed)&set(previous)):
                    raise ValueError('期刊成果原件的文件系列归属无效。')
                introduced = []
                for series_id,version in changed.items():
                    original = db.execute('SELECT v.actor_id,f.name,f.sha256 FROM journal_result_versions v JOIN handoff_files f ON f.id=v.file_id WHERE series_id=? AND version=?',(series_id,version)).fetchone()
                    if not original or original['actor_id']!=e['actor_id']:
                        raise ValueError('期刊成果原件与保存操作者不一致。')
                    introduced.append({'name':original['name'],'sha256':original['sha256']})
                expected = payload['files']
                if action=='file_restore':
                    old = db.execute('SELECT f.name,f.sha256 FROM journal_result_versions v JOIN handoff_files f ON f.id=v.file_id WHERE series_id=? AND version=?',(sid,data.get('file_version'))).fetchone()
                    if type(data.get('file_version')) is not int or not 1 <= data['file_version'] <= previous[sid] or not old:
                        raise ValueError('期刊成果恢复原件的依据无效。')
                    expected = [dict(old)]
                if sorted(introduced,key=lambda v:(v['sha256'],v['name']))!=sorted(expected,key=lambda v:(v['sha256'],v['name'])):
                    raise ValueError('期刊成果原件与上传请求不一致。')
            previous = snap['files']


def register(app,ctx):
    def service():
        return JournalResults(ctx.db(),ctx.user(),ctx.records(),ctx.data_dir)

    def data():
        if request.is_json:
            return ctx.body(),[]
        try:
            props = json.loads(request.form.get('data','{}'))
            if not isinstance(props,dict):
                raise ValueError()
        except (ValueError,TypeError):
            abort(400,'保存信息格式不正确。')
        uploads = [handoff_files.read_upload(f) for f in [*request.files.getlist('file'),*request.files.getlist('files')]]
        if sum(len(u[2]) for u in uploads)>handoff_files.MAX_BYTES:
            abort(400,'本次上传合计超过20 MB，请分批添加文件。')
        return props,uploads

    @app.get('/api/journal-results')
    def journal_results_list():
        s = service()
        year,jid,q = request.args.get('year',''),request.args.get('journal_id',''),request.args.get('q','').casefold().strip()
        if year and (not re.fullmatch(r'[0-9]{1,4}',year) or not 1 <= int(year) <= 9999):
            abort(400,'年份格式不正确。')
        if jid:
            jid = ctx.records().source(jid)['id']
        items = []
        for row in ctx.db().execute('SELECT * FROM journal_results ORDER BY year DESC,issue COLLATE NOCASE DESC,updated_at DESC,id'):
            if year and row['year']!=int(year):
                continue
            item = s.detail(row['id'])
            if jid and item['journal_id']!=jid:
                continue
            text = ' '.join([item['journal_name'],item['issue'],item['authors'],*[v['name'] for f in item['files'] for v in f['versions']]])
            if not q or q in text.casefold():
                items.append(item)
        return jsonify(items=items,total=len(items),sort='year_desc_issue_text_desc')

    @app.post('/api/journal-results')
    def journal_results_create():
        props,uploads = data()
        result = service().save('create',props,uploads)
        return jsonify(result),200 if result['replayed'] else 201

    @app.get('/api/journal-results/<rid>')
    def journal_results_detail(rid):
        return jsonify(service().detail(rid))

    @app.put('/api/journal-results/<rid>')
    def journal_results_edit(rid):
        return jsonify(service().save('metadata',ctx.body(),rid=rid))

    @app.post('/api/journal-results/<rid>/files')
    def journal_results_files(rid):
        props,uploads = data()
        result = service().save('files',props,uploads,rid)
        return jsonify(result),200 if result['replayed'] else 201

    @app.get('/api/journal-results/<rid>/history')
    def journal_results_history(rid):
        return jsonify(items=service().history(rid))

    @app.post('/api/journal-results/<rid>/restore')
    def journal_results_restore(rid):
        props = ctx.body()
        return jsonify(service().save('file_restore' if props.get('series_id') else 'restore',props,rid=rid))

    @app.get('/api/journal-results/<rid>/files/<sid>/versions/<int:version>/file')
    def journal_results_file(rid,sid,version):
        row = service().original(rid,sid,version)
        return send_file(handoff_files.original_path(ctx.data_dir,row),as_attachment=request.args.get('inline')!='1',download_name=row['name'])

    @app.get('/api/journal-results/<rid>/files/<sid>/versions/<int:version>/preview')
    def journal_results_preview(rid,sid,version):
        row = service().original(rid,sid,version)
        path = handoff_files.original_path(ctx.data_dir,row)
        if path.suffix=='.pdf':
            return jsonify(kind='pdf',url=request.path.removesuffix('/preview')+'/file?inline=1')
        if path.suffix=='.docx':
            try:
                with zipfile.ZipFile(path) as z:
                    info = z.getinfo('word/document.xml')
                    if info.file_size>8*1024*1024:
                        abort(400,'Word文字过大，请下载原件阅读。')
                    root = ElementTree.fromstring(z.read(info))
                    paragraphs = [''.join(p.itertext()) for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')]
                    text = '\n'.join(paragraphs)
            except (zipfile.BadZipFile,KeyError,ElementTree.ParseError):
                abort(400,'无法提取Word文字，请下载原件阅读。')
        else:
            text = path.read_text(encoding='utf-8-sig')
        return jsonify(kind='text',text=text[:30000],truncated=len(text)>30000)

    @app.get('/api/journal-results/export')
    def journal_results_export():
        s = service()
        ids = set(request.args.get('ids','').split(','))-{''}
        if not ids:
            abort(400,'请选择要导出的期刊成果。')
        for rid in ids:
            s.get(rid)
        items = export_projection(s,ids)
        output = io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('content.json',json.dumps({'format':'journal-results-v1','journal_results':items},ensure_ascii=False,indent=2))
            archive.writestr('index.html','<!doctype html><meta charset="utf-8"><h1>期刊成果</h1>'+''.join('<p><a href="'+i['path']+'">'+html.escape(i['journal_name']+' · '+str(i['year'])+' · '+i['issue'])+'</a></p>' for i in items))
            write_export(archive,s,items)
        output.seek(0)
        return send_file(output,mimetype='application/zip',as_attachment=True,download_name='journal-results.zip')
