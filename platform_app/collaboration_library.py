"""Read-only work discovery and explicitly scoped portable originals.

Business services remain the authority for work and record access. No new owners,
copies of records, or persisted progress are introduced by these projections.
"""
import hashlib
import json
import tempfile
import zipfile
from datetime import date

from flask import abort, jsonify, request, send_file

from . import collaboration, handoff_files, journal_collaboration as journal
from . import topic_review, topic_finals
from .store import now


def work_items(db, actor, access):
    for row in db.execute('SELECT * FROM collaboration_topics ORDER BY updated_at DESC,id'):
        if not collaboration.can_read(db, actor, row):
            continue
        work = collaboration.projection(db, actor, row)
        workflow = topic_review.workflow_projection(db, actor, row)
        activity = [row['updated_at']]
        for table in ('topic_candidates', 'topic_meetings', 'topic_manuscripts', 'topic_returns', 'topic_finals', 'topic_summaries'):
            stamp = db.execute(f'SELECT MAX(created_at) FROM {table} WHERE topic_id=?', (row['id'],)).fetchone()[0]
            if stamp:
                activity.append(stamp)
        work['updated_at'] = max(activity)
        products = workflow['summaries'][:1]
        products = [dict(p, product_kind='summary') for p in products]
        products += [dict(max(a['finals'], key=lambda f: f['version']), product_kind='final') for a in workflow['assignments'] if a['finals']]
        yield {**work, 'business': 'topic', 'title': row['theme'], 'products': products,
               'countries': sorted({a['country'] for a in workflow['assignments'] if a['country']}),
               'participating': work['can_submit'], 'leading': work['can_manage'],
               'participant_ids': [p['id'] for p in work['participants']],
               'participant_names': [p['name'] for p in work['participants']]}
    service = journal.JournalWorks(db, access)
    for row in db.execute('SELECT * FROM journal_works ORDER BY updated_at DESC,id'):
        record = db.execute('SELECT * FROM records WHERE id=?', (row['record_id'],)).fetchone()
        if not record or not access.visible(record):
            continue
        work = service.detail(row['id'])
        people = {e[0] for e in db.execute('SELECT actor_id FROM journal_work_events WHERE work_id=?', (row['id'],))}
        people |= {s['uploader_id'] for s in work['submissions']}
        if record['kind'] in {'compilation', 'research_report'}:
            people.add(record['author_id'])
        people.discard(None)
        products = [dict(s, product_kind='journal') for s in work['submissions'] if s['id'] == work['current_product_id']]
        yield {**work, 'business': 'journal', 'title': work['journal_name'] + ' · ' + work['coverage'],
               'products': products, 'countries': [], 'participating': actor['id'] in people,
               'leading': record['kind'] in {'compilation', 'research_report'} and record['author_id'] == actor['id'] and access.editable(record),
               'participant_ids': sorted(people),
               'participant_names': [db.execute('SELECT name FROM users WHERE id=?', (uid,)).fetchone()[0] for uid in sorted(people)]}


def register(app, ctx):
    @app.get('/api/collaboration/works')
    def works():
        actor, db = ctx.user(), ctx.db()
        scope = request.args.get('scope', 'all')
        business, view = request.args.get('business', ''), request.args.get('view', 'works')
        if scope not in {'all', 'participating', 'leading', 'maintenance'} or business not in {'', 'topic', 'journal'} or view not in {'works', 'products'}:
            abort(400, '工作查找条件不正确。')
        if scope == 'maintenance' and actor['role'] != 'admin':
            abort(403, '维护查阅需要管理员权限。')
        start, end = request.args.get('from', ''), request.args.get('to', '')
        try:
            for value in (start, end):
                if value and date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            if start and end and start > end:
                raise ValueError()
        except ValueError:
            abort(400, '请填写有效的起止日期，起始日期不能晚于截止日期。')
        q, country, participant = [request.args.get(k, '').strip().casefold() for k in ('q', 'country', 'participant')]
        access = topic_finals.access(db, actor, ctx.data_dir)
        items = []
        for item in work_items(db, actor, access):
            if business and item['business'] != business:
                continue
            if scope in {'participating', 'leading'} and not item[scope]:
                continue
            if view == 'products' and not item['products']:
                continue
            if q and q not in item['title'].casefold():
                continue
            if country and not any(country in c.casefold() for c in item['countries']):
                continue
            if participant and not any(participant in p.casefold() for p in item['participant_ids'] + item['participant_names']):
                continue
            stamp = item['updated_at'][:10]
            if (start and stamp < start) or (end and stamp > end):
                continue
            # Discovery needs titles and product identities, not every file history.
            item.pop('submissions', None)
            items.append(item)
        items.sort(key=lambda w: (w['updated_at'], w['id']), reverse=True)
        return jsonify(items=items, total=len(items), can_create=collaboration.qualified(db, actor['id']))

    @app.get('/api/collaboration/materials/<business>/<wid>')
    def materials(business, wid):
        return material_response(ctx, business, wid, request.args.get('scope', 'all'))


def material_payload(ctx, business, wid, scope):
    if scope not in {'all', 'products', 'process'}:
        abort(400, '请选择全部已提交材料、成果或过程材料范围。')
    db, actor = ctx.db(), ctx.user()
    payload = {'format': 'work-materials-v1', 'business': business, 'work_id': wid, 'scope': scope,
               'exported_at': now(), 'files': [], 'exclusions': '不含未提交文件、关联成果正文及附件、关联原文或其他工作；不据此宣称这些内容已经导出。'}
    if business == 'topic':
        topic = collaboration.topic_for(db, actor, wid)
        payload['topic'] = collaboration.projection(db, actor, topic)
        workflow = topic_review.workflow_projection(db, actor, topic)
        candidates = collaboration.candidate_projection(db, wid) if scope != 'products' else []
        if scope == 'products':
            workflow['meetings'] = []
            for a in workflow['assignments']:
                a['submissions'] = [s for s in a['submissions'] if any(f['submission_id'] == s['id'] for f in a['finals'])]
                a['returns'] = []
        elif scope == 'process':
            workflow['summaries'] = []
            for a in workflow['assignments']:
                a['finals'] = []
        payload.update(candidates=candidates, workflow=workflow)
        originals = candidates + workflow['meetings'] + workflow['summaries'] + [s for a in workflow['assignments'] for k in ('submissions', 'returns', 'finals') for s in a[k]]
        for summary in workflow['summaries']:
            summary['adopted_final_ids'] = json.loads(db.execute('SELECT adoptions_json FROM topic_summaries WHERE id=?', (summary['id'],)).fetchone()[0])
            originals += summary['adoptions']
        payload['coverage'] = {'all': '本期全部已提交过程、定稿和汇总及其历史版本', 'products': '本期全部已确认定稿及汇总版本，含汇总采用的具体稿件；不含候选、会议文件及返修意见', 'process': '本期全部选题报告、会议、稿件与返修意见；不含定稿决定及整期汇总'}[scope]
    elif business == 'journal':
        access = topic_finals.access(db, actor, ctx.data_dir)
        work, _ = journal.JournalWorks(db, access).get(wid)
        # Reuse the existing historical projection after this exact work ACL.
        item = journal.export_projection(db, access, work_ids={wid})[0]
        if scope == 'products':
            item['submissions'] = [s for s in item['submissions'] if s['id'] == work['current_product_id']]
        elif scope == 'process':
            item['submissions'] = [s for s in item['submissions'] if s['id'] != work['current_product_id']]
        payload['journal'] = item
        originals = item['submissions']
        payload['coverage'] = {'all': '本期刊工作全部已提交原件及工作、采用历史', 'products': '本期刊工作当前明确采用的成品，附采用历史；其他原件不在所选范围', 'process': '本期刊工作除当前成品之外的已提交原件，附工作、采用历史'}[scope]
    else:
        abort(404, '编译业务不存在。')
    return payload, originals


def material_response(ctx, business, wid, scope):
    payload, originals = material_payload(ctx, business, wid, scope)
    output = tempfile.TemporaryFile(prefix='database-materials-', suffix='.zip')
    try:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            files = {}
            for item in originals:
                if not item.get('file_id'):
                    continue
                fid = item['file_id']
                row = ctx.db().execute('SELECT * FROM handoff_files WHERE id=?', (fid,)).fetchone()
                item['path'] = 'originals/' + row['stored_name']
                if fid in files:
                    continue
                path = handoff_files.original_path(ctx.data_dir, row)
                digest, count = hashlib.sha256(), 0
                with path.open('rb') as source, archive.open(item['path'], 'w', force_zip64=True) as destination:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        destination.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                if (count, digest.hexdigest()) != (row['bytes'], row['sha256']):
                    abort(409, '原件校验未通过，本次材料包未生成。')
                files[fid] = {'file_id': fid, 'name': row['name'], 'path': item['path'], 'bytes': count, 'sha256': digest.hexdigest()}
            payload['files'] = list(files.values())
            archive.writestr('manifest.json', json.dumps(payload, ensure_ascii=False, indent=2))
            archive.writestr('README.txt', payload['coverage'] + '\n' + payload['exclusions'] + '\n原名、版本、决定与采用关系见manifest.json。独立核验：python scripts/verify_work_materials.py 材料包.zip\n清单能验证内部一致性，来源真实性需与保存的整包SHA-256或在线原件比对。\n')
        # Permission may have changed during a long export. No half ZIP is sent.
        actor = ctx.user()
        if business == 'topic':
            collaboration.topic_for(ctx.db(), actor, wid)
        else:
            journal.JournalWorks(ctx.db(), topic_finals.access(ctx.db(), actor, ctx.data_dir)).get(wid)
        output.seek(0)
        response = send_file(output, mimetype='application/zip', as_attachment=True, download_name=f'{business}-{wid}-{scope}.zip')
        response.call_on_close(output.close)
        return response
    except BaseException:
        output.close()
        raise
