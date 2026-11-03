"""Topic material handoffs: one interface for direct work and real legacy history.

Callers use board/submit/decide/archive; legacy meeting knowledge stays here.
Originals and decisions are immutable, and authority is checked in transactions.
"""
import json
import re
import uuid
from pathlib import Path

from flask import abort, jsonify, request, send_file

from . import collaboration, handoff_files, topic_review as review, topic_stages, topic_closure
from .store import connect, now

SCHEMA_VERSION = 27
TABLES = ('topic_materials', 'topic_material_versions', 'topic_material_reviews')
SCHEMA = [
    "CREATE TABLE topic_materials(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), stage TEXT NOT NULL CHECK(stage IN ('selection','compilation')), owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, source_ref TEXT, created_at TEXT NOT NULL)",
    "CREATE TABLE topic_material_versions(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), material_id TEXT NOT NULL REFERENCES topic_materials(id), author_id TEXT NOT NULL REFERENCES users(id), topic_version INTEGER NOT NULL, version INTEGER NOT NULL CHECK(version>0), file_id TEXT UNIQUE NOT NULL REFERENCES handoff_files(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(material_id,version), UNIQUE(topic_id,author_id,request_id))",
    "CREATE TABLE topic_material_reviews(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), version_ref TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('approved','returned')), actor_id TEXT NOT NULL REFERENCES users(id), topic_version INTEGER NOT NULL, qualification_version INTEGER NOT NULL, file_id TEXT UNIQUE REFERENCES handoff_files(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,version_ref), UNIQUE(topic_id,actor_id,request_id))",
]


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
            return
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute('BEGIN IMMEDIATE')
            for statement in SCHEMA:
                db.execute(statement)
            # Keep every legacy column/value; direct decisions have no meeting.
            db.execute('ALTER TABLE topic_stage_events RENAME TO topic_stage_events_before_direct')
            db.execute(topic_stages.SCHEMA[1].replace('meeting_id TEXT NOT NULL', 'meeting_id TEXT'))
            db.execute('INSERT INTO topic_stage_events SELECT * FROM topic_stage_events_before_direct')
            db.execute('DROP TABLE topic_stage_events_before_direct')
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('topic_handoffs_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def _file(db, tid, kind, row):
    item = dict(row)
    for key in ('request_id', 'request_hash', 'request_json'):
        item.pop(key, None)
    if item.get('file_id'):
        item.update(dict(db.execute('SELECT name,bytes,sha256 FROM handoff_files WHERE id=?', (item['file_id'],)).fetchone()))
        item['file_url'] = f"/api/collaboration/topics/{tid}/{kind}/{item['id']}/file"
    else:
        item['file_url'] = None
    return item


class _Legacy:
    """Read existing series unchanged; never transfer a previous author's work."""
    def materials(self, db, tid):
        result = {}
        for table, kind, stage in (('topic_candidates', 'candidate', 'selection'), ('topic_manuscripts', 'manuscript', 'compilation')):
            for row in db.execute(f'SELECT * FROM {table} WHERE topic_id=? ORDER BY version DESC', (tid,)):
                ref = f"{kind}:{row['author_id']}" if kind == 'candidate' else f"{kind}:{row['assignment_id']}:{row['author_id']}"
                if ref not in result:
                    title = '选题报告' if kind == 'candidate' else next((a['title'] for a in json.loads(db.execute('SELECT assignments_json FROM topic_meetings WHERE id=?', (row['meeting_id'],)).fetchone()[0]) if a['id'] == row['assignment_id']), '编译稿')
                    result[ref] = dict(ref=ref, stage=stage, owner_id=row['author_id'], title=title, legacy=True, source_ref=None, versions=[])
                item = _file(db, tid, 'candidates' if kind == 'candidate' else 'submissions', row)
                item['ref'] = f"{kind}:{row['id']}"
                item['legacy'] = True
                item['reviews'] = []
                if kind == 'manuscript':
                    for history, decision in (('topic_returns', 'returned'), ('topic_finals', 'legacy_final')):
                        for r in db.execute(f'SELECT * FROM {history} WHERE topic_id=? AND submission_id=?', (tid, row['id'])):
                            item['reviews'].append(dict(_file(db, tid, 'returns' if decision == 'returned' else 'finals', r), decision=decision, legacy=True))
                result[ref]['versions'].append(item)
        return list(result.values())


class _Direct:
    def materials(self, db, tid):
        result = []
        for row in db.execute('SELECT * FROM topic_materials WHERE topic_id=? ORDER BY created_at,id', (tid,)):
            material = dict(row, ref='material:' + row['id'], legacy=False, versions=[])
            for v in db.execute('SELECT * FROM topic_material_versions WHERE material_id=? ORDER BY version DESC', (row['id'],)):
                material['versions'].append(dict(_file(db, tid, 'handoff-versions', v), ref='version:' + v['id'], legacy=False, reviews=[]))
            result.append(material)
        return result


def _materials(db, tid):
    items = _Legacy().materials(db, tid) + _Direct().materials(db, tid)
    for material in items:
        material['owner_name'] = db.execute('SELECT name FROM users WHERE id=?', (material['owner_id'],)).fetchone()[0]
        for v in material['versions']:
            v['author_name'] = db.execute('SELECT name FROM users WHERE id=?', (v['author_id'],)).fetchone()[0]
            for r in db.execute('SELECT r.*,u.name AS actor_name FROM topic_material_reviews r JOIN users u ON u.id=r.actor_id WHERE topic_id=? AND version_ref=?', (tid, v['ref'])):
                v['reviews'].append(_file(db, tid, 'handoff-reviews', r))
            v['status'] = v['reviews'][-1]['decision'] if v['reviews'] else 'pending'
        material['status'] = material['versions'][0]['status']
    return items


def identities(db, tid):
    """Versioned archival basis shared by closure and restore, including reviews."""
    return {table: [r[0] for r in db.execute(f'SELECT id FROM {table} WHERE topic_id=? ORDER BY id', (tid,))] for table in (*topic_closure.WORK_TABLES, *TABLES)}


def _token(db, topic):
    return review.fingerprint(topic_closure.basis(db, topic))


def board(db, actor, tid):
    topic = collaboration.topic_for(db, actor, tid)
    t = collaboration.projection(db, actor, topic)
    items = _materials(db, tid)
    for material in items:
        material['superseded'] = any(m['source_ref'] in {v['ref'] for v in material['versions']} for m in items if m['source_ref'])
        material['can_submit'] = t['can_submit'] and material['owner_id'] == actor['id'] and not any(m['source_ref'] in {v['ref'] for v in material['versions']} for m in items if m['source_ref'])
        for i, version in enumerate(material['versions']):
            version['can_review'] = t['can_manage'] and i == 0 and not any(not r.get('legacy') for r in version['reviews']) and not material['superseded'] and not any(r['decision'] == 'legacy_final' for r in version['reviews'])
    return {**t, 'token': _token(db, topic), 'materials': items}


def _material_archive(db, actor, tid, scope):
    collaboration.topic_for(db, actor, tid)
    if scope not in {'all', 'products', 'process'}:
        abort(400, '材料范围无效。')
    # Approval is a review, never publication. Legacy products stay in their adapter.
    items = _materials(db, tid) if scope != 'products' else []
    if scope == 'process':
        for m in items:
            for v in m['versions']:
                v['reviews'] = [r for r in v['reviews'] if r['decision'] != 'legacy_final']
    return {'format': 'topic-handoffs-v1', 'materials': items}, [v for m in items for v in m['versions']] + [r for m in items for v in m['versions'] for r in v['reviews'] if not r.get('legacy')]


def archive(db, actor, tid, scope):
    """Own scope and legacy adoption knowledge; callers only copy authorized files."""
    if scope not in {'all', 'products', 'process'}:
        abort(400, '材料范围无效。')
    payload = {}
    topic = collaboration.topic_for(db, actor, tid)
    payload['topic'] = collaboration.projection(db, actor, topic)
    payload['stage_coverage'] = '阶段与结束状态为导出时当前状态；升级、人工转换、结束／重开及确认缺项依据单独列明，不代表各份旧材料提交时已有该状态。'
    workflow = review.workflow_projection(db, actor, topic)
    candidates = collaboration.candidate_projection(db, tid) if scope != 'products' else []
    if scope == 'products':
        workflow['meetings'] = []
        for a in workflow['assignments']:
            a['submissions'] = [s for s in a['submissions'] if any(f['submission_id'] == s['id'] for f in a['finals'])]
            a['returns'] = []
    elif scope == 'process':
        workflow['summaries'] = []
        for a in workflow['assignments']:
            a['finals'] = []
    handoffs, direct_originals = _material_archive(db, actor, tid, scope)
    payload.update(candidates=candidates, workflow=workflow, handoffs=handoffs)
    originals = candidates + workflow['meetings'] + workflow['summaries'] + [s for a in workflow['assignments'] for k in ('submissions', 'returns', 'finals') for s in a[k]]
    originals += direct_originals
    for summary in workflow['summaries']:
        summary['adopted_final_ids'] = json.loads(db.execute('SELECT adoptions_json FROM topic_summaries WHERE id=?', (summary['id'],)).fetchone()[0])
        originals += summary['adoptions']
    payload['coverage'] = {'all': '本期全部已提交过程、定稿和汇总及其历史版本', 'products': '本期全部已确认定稿及汇总版本，含汇总采用的具体稿件；不含候选、会议文件及返修意见', 'process': '本期两阶段材料、审阅与旧选题报告、会议、稿件及返修意见；不含旧定稿决定及整期汇总'}[scope]
    return payload, originals


def _expect(db, topic, data):
    if data.get('token') != _token(db, topic):
        abort(409, '本期材料或状态已更新。文件与说明仍保留，请刷新状态后重试。')


def _participant(db, actor, tid):
    topic = collaboration.topic_for(db, actor, tid)
    if not db.execute('SELECT 1 FROM topic_participants p JOIN users u ON u.id=p.member_id WHERE p.topic_id=? AND p.member_id=? AND p.active=1 AND u.active=1', (tid, actor['id'])).fetchone():
        abort(403, '只有本期有效参与者可提交自己的材料。')
    return topic


def _reused(db, table, actor_column, tid, actor, key, digest):
    old = db.execute(f'SELECT * FROM {table} WHERE topic_id=? AND {actor_column}=? AND request_id=?', (tid, actor['id'], key)).fetchone()
    if old and old['request_hash'] != digest:
        abort(409, '同一请求已保存不同内容，请核对已存版本。')
    return old


def submit(ctx, tid, data, uploaded):
    key, digest = review.request_key(data), review.request_identity(data, uploaded)
    with handoff_files.transaction(ctx.db()) as created:
        db, actor = ctx.db(), ctx.user()
        topic = _participant(db, actor, tid)
        old = _reused(db, 'topic_material_versions', 'author_id', tid, actor, key, digest)
        if old:
            return dict(id=old['id'], material_ref='material:' + old['material_id'], reused=True), 200
        topic_closure.require_open(db, tid)
        _expect(db, topic, data)
        stage = data.get('stage')
        if stage not in {'selection', 'compilation'} or (stage == 'compilation' and topic_stages.state(db, tid)['stage'] != 'compilation'):
            abort(409, '进入编译后才可提交编译材料。')
        note = review.text(data.get('note', ''), '说明')
        title = review.text(data.get('title', uploaded[0]), '材料题名', 500)
        if not title:
            abort(400, '请填写材料题名。')
        material_ref = data.get('material_ref')
        material = next((m for m in _materials(db, tid) if m['ref'] == material_ref), None) if material_ref else None
        if material_ref and not material:
            abort(404, '材料不存在。')
        if material and (material['owner_id'] != actor['id'] or material['stage'] != stage):
            abort(403, '只能为本人同阶段材料提交新版本。')
        source_ref = None
        if material and material['legacy']:
            source_ref = data.get('source_ref')
            if source_ref not in {v['ref'] for v in material['versions']}:
                abort(403, '前驱版本不属于本人的材料。')
            if any(m['source_ref'] in {v['ref'] for v in material['versions']} for m in _materials(db, tid) if m['source_ref']):
                abort(409, '此材料已有接续版本，请在该材料提交新版。')
        mid = material['id'] if material and not material['legacy'] else uuid.uuid4().hex
        stamp = now()
        if not material or material['legacy']:
            db.execute('INSERT INTO topic_materials VALUES (?,?,?,?,?,?,?)', (mid, tid, stage, actor['id'], material['title'] if material else title, source_ref, stamp))
        version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM topic_material_versions WHERE material_id=?', (mid,)).fetchone()[0]
        fid = handoff_files.save_original(db, ctx.data_dir, actor['id'], uploaded, created)
        vid = uuid.uuid4().hex
        db.execute('INSERT INTO topic_material_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (vid, tid, mid, actor['id'], topic['version'], version, fid, note, key, digest, json.dumps(data, ensure_ascii=False), stamp))
    return dict(id=vid, material_ref='material:' + mid, version=version), 201


def decide(ctx, tid, data, uploaded):
    key, digest = review.request_key(data), review.request_identity(data, uploaded)
    with handoff_files.transaction(ctx.db()) as created:
        db, actor = ctx.db(), ctx.user()
        topic = collaboration.topic_for(db, actor, tid, manage=True)
        old = _reused(db, 'topic_material_reviews', 'actor_id', tid, actor, key, digest)
        if old:
            return dict(id=old['id'], reused=True), 200
        topic_closure.require_open(db, tid)
        _expect(db, topic, data)
        version_ref, decision = data.get('version_ref'), data.get('decision')
        version = next((v for m in board(db, actor, tid)['materials'] for v in m['versions'] if v['ref'] == version_ref and v['can_review']), None)
        if not version:
            abort(409, '请审阅材料的最新版本。')
        if decision not in {'approved', 'returned'}:
            abort(400, '请选择通过或退回。')
        if db.execute('SELECT 1 FROM topic_material_reviews WHERE topic_id=? AND version_ref=?', (tid, version_ref)).fetchone():
            abort(409, '此版本已审阅，请核对新版本。')
        note = review.text(data.get('note', ''), '审阅意见')
        fid = handoff_files.save_original(db, ctx.data_dir, actor['id'], uploaded, created) if uploaded else None
        qv = db.execute('SELECT version FROM lead_qualifications WHERE member_id=?', (actor['id'],)).fetchone()[0]
        rid = uuid.uuid4().hex
        db.execute('INSERT INTO topic_material_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (rid, tid, version_ref, decision, actor['id'], topic['version'], qv, fid, note, key, digest, json.dumps(data, ensure_ascii=False), now()))
    return dict(id=rid), 201


def referenced_files(db):
    return [r[0] for table in TABLES[1:] for r in db.execute(f'SELECT file_id FROM {table} WHERE file_id IS NOT NULL')]


def validate_backup(db):
    def require(value):
        if not value:
            raise ValueError('材料、版本或审阅归属不一致。')
    for topic in db.execute('SELECT * FROM collaboration_topics'):
        materials = _materials(db, topic['id'])
        legacy = {v['ref']: (m, v) for m in materials if m['legacy'] for v in m['versions']}
        refs = {v['ref'] for m in materials for v in m['versions']}
        sources = []
        for m in materials:
            if m['legacy']:
                continue
            versions = db.execute('SELECT * FROM topic_material_versions WHERE material_id=? ORDER BY version', (m['id'],)).fetchall()
            require(bool(versions) and [v['version'] for v in versions] == list(range(1, len(versions) + 1)))
            if m['source_ref']:
                require(m['source_ref'] in legacy)
                previous, v = legacy[m['source_ref']]
                require(previous['owner_id'] == m['owner_id'] and previous['stage'] == m['stage'] and previous['ref'] not in sources)
                require(v['created_at'] <= m['created_at'])
                sources.append(previous['ref'])
            for row in versions:
                require(row['topic_id'] == topic['id'] and row['author_id'] == m['owner_id'])
                _validate_row(db, row, 'author_id', require)
                data = json.loads(row['request_json'])
                require(data['stage'] == m['stage'])
                if row['version'] == 1:
                    if m['source_ref']:
                        require(data.get('material_ref') == previous['ref'] and data.get('source_ref') == m['source_ref'])
                    else:
                        require(not data.get('material_ref'))
                        f = db.execute('SELECT name FROM handoff_files WHERE id=?', (row['file_id'],)).fetchone()
                        require(data.get('title', f[0]).strip() == m['title'])
                else:
                    require(data.get('material_ref') == m['ref'])
                if m['stage'] == 'compilation':
                    stage = topic_stages.state(db, topic['id'])
                    require(json.loads(stage['origin_json'])['initial_stage'] == 'compilation' or db.execute("SELECT 1 FROM topic_stage_events WHERE topic_id=? AND created_at<=?", (topic['id'], row['created_at'])).fetchone())
        for r in db.execute('SELECT * FROM topic_material_reviews WHERE topic_id=?', (topic['id'],)):
            require(r['version_ref'] in refs and r['actor_id'] == topic['lead_id'])
            _validate_row(db, r, 'actor_id', require)
            q = db.execute('SELECT enabled FROM qualification_events WHERE member_id=? AND version=?', (r['actor_id'], r['qualification_version'])).fetchone()
            require(q is not None and q[0] == 1)
            data = json.loads(r['request_json'])
            require(data['version_ref'] == r['version_ref'] and data['decision'] == r['decision'])


def _validate_row(db, row, actor_column, require):
    data = json.loads(row['request_json'])
    f = db.execute('SELECT * FROM handoff_files WHERE id=?', (row['file_id'],)).fetchone() if row['file_id'] else None
    require(not row['file_id'] or (f and f['uploader_id'] == row[actor_column]))
    require(review.fingerprint({'data': data, 'file': [f['name'], f['sha256']] if f else None}) == row['request_hash'])
    require(isinstance(data.get('request_id'), str) and re.fullmatch(r'[A-Za-z0-9_-]{8,100}', data['request_id']) and data['request_id'] == row['request_id'])
    require(isinstance(data.get('token'), str) and re.fullmatch(r'[a-f0-9]{64}', data['token']))
    require(isinstance(data.get('note', ''), str) and data.get('note', '').strip() == row['note'] and len(row['note']) <= 4000)
    history = db.execute('SELECT snapshot_json FROM topic_events WHERE topic_id=? AND version=?', (row['topic_id'], row['topic_version'])).fetchone()
    require(history is not None and row[actor_column] in json.loads(history[0])['participant_ids'])


def register(app, ctx):
    @app.get('/api/collaboration/topics/<tid>/handoffs')
    def handoff_board(tid):
        with ctx.db():
            ctx.db().execute('BEGIN')
            result = board(ctx.db(), ctx.user(), tid)
        return jsonify(result)

    @app.post('/api/collaboration/topics/<tid>/handoffs')
    def handoff_submit(tid):
        uploaded = handoff_files.read_upload(request.files.get('file'))
        result, code = submit(ctx, tid, ctx.body(), uploaded)
        return jsonify(result), code

    @app.post('/api/collaboration/topics/<tid>/handoff-reviews')
    def handoff_decide(tid):
        uploaded = handoff_files.read_upload(request.files['file']) if request.files.get('file') else None
        result, code = decide(ctx, tid, ctx.body(), uploaded)
        return jsonify(result), code

    @app.get('/api/collaboration/topics/<tid>/handoff-preview')
    def handoff_preview(tid):
        import os
        import subprocess
        import sys
        from . import attachment_worker
        db = ctx.db()
        collaboration.topic_for(db, ctx.user(), tid)
        ref = request.args.get('version_ref')
        version = next((v for m in _materials(db, tid) for v in m['versions'] if v['ref'] == ref), None)
        if not version:
            abort(404, '材料版本不存在。')
        original = db.execute('SELECT * FROM handoff_files WHERE id=?', (version['file_id'],)).fetchone()
        path = handoff_files.original_path(ctx.data_dir, original)
        if original['bytes'] > attachment_worker.MAX_BYTES:
            return jsonify(status='limit', segments=[])
        try:
            process = subprocess.run([sys.executable, str(Path(attachment_worker.__file__)), str(path)], capture_output=True, timeout=12, check=False,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            result = json.loads(process.stdout.decode('utf-8')) if process.returncode == 0 else {'status': 'failed', 'segments': []}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result = {'status': 'failed', 'segments': []}
        return jsonify(status=result['status'], segments=result.get('segments', []), name=original['name'], version=version['version'])

    @app.get('/api/collaboration/topics/<tid>/handoff-versions/<vid>/file')
    @app.get('/api/collaboration/topics/<tid>/handoff-reviews/<rid>/file')
    def handoff_download(tid, vid=None, rid=None):
        db = ctx.db()
        collaboration.topic_for(db, ctx.user(), tid)
        table, eid = ('topic_material_versions', vid) if vid else ('topic_material_reviews', rid)
        row = db.execute(f'SELECT f.* FROM {table} s JOIN handoff_files f ON f.id=s.file_id WHERE s.id=? AND s.topic_id=?', (eid, tid)).fetchone()
        if not row:
            abort(404, '原件不存在。')
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row['name'])
