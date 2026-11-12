"""Bounded public rechecks; immutable observations never edit members' content.

The existing run/entry lease is the durable queue. Per-record observations and
one current exception live with the acquisition evidence, inside full backups.
"""
import base64
import hashlib
import json
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

from flask import abort, jsonify

from . import intake, store, source_adapters, journal_metadata, workflow

RECHECK_LIMIT = 3
RECHECK_DAYS = 7
NOTICE_LIMIT = 5
LABELS = {'retraction':'上游登记撤回', 'correction':'上游登记更正', 'withdrawal':'上游登记撤回',
          'expression-of-concern':'上游登记关注声明', 'removed':'上游入口失效',
          'access_limited':'上游暂无法访问', 'changed':'上游内容已变化'}


def pending_entries(db, source, present):
    """Oldest unchecked first, at most three, excluding this response's works."""
    adapter = source_adapters.for_source(source)
    cutoff = (datetime.fromisoformat(store.now())-timedelta(days=RECHECK_DAYS)).isoformat(timespec='seconds')
    candidates = []
    for row in db.execute("SELECT * FROM records WHERE merged_into IS NULL AND visibility='shared'"):
        raw = json.loads(row['raw_json'] or '{}')
        acquired = raw.get('automatic_acquisition', {})
        evidence = next((e for e in reversed(raw.get('discovery_evidence', []))
                         if e.get('source_id')==source['id'] and e.get('adapter')==adapter['id']), None)
        if row['kind'] in workflow.CONTENT_KINDS:
            continue
        if not evidence and (row['serial_id']==source['id'] if adapter['mode']=='crossref' else row['source_id']==source['id']):
            doi = intake.normalize_doi(row['doi'])
            if adapter['mode']=='crossref' and not doi or adapter['mode']!='crossref' and not source_adapters.article_url(adapter,row['url']):
                continue
            fields = {key:row[key] for key in ('kind','title','url','doi','authors','serial_id','source_id')}
            evidence = dict(format=adapter['format'],version=1,adapter=adapter['id'],source_id=source['id'],
                feed_url=adapter['feed'],column_url=adapter['column'],retrieved_at=store.now(),
                entry_id=hashlib.sha256((adapter['id']+':'+(doi or row['url'])).encode()).hexdigest(),raw={},fields=fields)
        if not evidence or evidence['entry_id'] in present:
            continue
        checked = acquired.get('upstream', {}).get('last_checked_at', row['created_at'])
        if checked > cutoff:
            continue
        candidates.append((checked, row['id'], evidence))
    return [dict(evidence, recheck_record_id=rid) for _, rid, evidence in sorted(candidates)[:RECHECK_LIMIT]]


def notices(items, target):
    result = []
    for item in items:
        for update in item.get('update-to', []):
            kind = update.get('type')
            doi = intake.normalize_doi(item.get('DOI'))
            if kind in LABELS and intake.normalize_doi(update.get('DOI'))==target and doi:
                result.append(dict(kind=kind, doi=doi, target_doi=target,
                                   updated=update.get('updated'), source=update.get('source', 'Crossref')))
    return result


def check_updates(doi):
    url = 'https://api.crossref.org/works?'+urlencode(dict(filter='updates:'+doi, rows=NOTICE_LIMIT))
    document = intake.fetch_document(url, time.monotonic()+intake.MAX_SECONDS)
    if document['url'] != url or document['content_type'] not in {'application/json','application/vnd.crossref-api-message+json'}:
        raise intake.AcquisitionError('更新声明响应离开固定Crossref入口。')
    try:
        payload = json.loads(document['bytes'])
        message = payload['message']
        items = message['items']
        if payload['status']!='ok' or not isinstance(items,list) or len(items)>NOTICE_LIMIT or type(message['total-results']) is not int:
            raise ValueError()
        found = notices(items, doi)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise intake.AcquisitionError('更新声明响应无效；未将无声明解释为没有更正。') from None
    content = document['bytes']
    return dict(url=url, retrieved_at=store.now(), raw_base64=base64.b64encode(content).decode(),
                sha256=hashlib.sha256(content).hexdigest(), bytes=len(content), target_doi=doi,
                notices=found, has_more=message['total-results']>len(items))


def fetch(evidence, adapter):
    from .ingestion import page_snapshot
    fields = evidence['fields']
    doi = intake.normalize_doi(fields.get('doi'))
    url = 'https://api.crossref.org/works/'+quote(doi, safe='') if adapter['mode']=='crossref' else fields['url']
    document = intake.fetch_document(url, time.monotonic()+intake.MAX_SECONDS)
    if adapter['mode']=='crossref':
        if document['url']!=url or document['content_type'] not in {'application/json','application/vnd.crossref-api-message+json'}:
            raise intake.AcquisitionError('重查题录离开固定Crossref入口。')
        snap = journal_metadata.snapshot(document, adapter, doi, store.now())
        try:
            updates = check_updates(doi)
            return snap, dict(status='available', notice_evidence=updates)
        except intake.AcquisitionError as failure:
            # Keep the valid DOI observation even if the independent notice
            # query fails. Missing notice coverage remains explicit and retryable.
            return snap, dict(status='available', notice_error=str(failure),
                              notice_http_status=failure.http_status, notice_failure=failure)
    if not source_adapters.article_url(adapter, document['url']):
        raise intake.AcquisitionError('原文重查离开已接入的官方文章入口。')
    return page_snapshot(document, adapter), dict(status='available')


def observe(automatic, before, snapshot, error, check):
    """Called inside the owning record revision transaction; returns a change."""
    old = automatic.get('upstream', {})
    upstream = dict(old, last_checked_at=store.now(), status=check.get('status','available'), error=error,
                    http_status=check.get('http_status'))
    if snapshot and not error:
        upstream['last_successful_check_at'] = store.now()
    changed_fields = []
    if before and snapshot:
        a, b = before.get('metadata') or {}, snapshot.get('metadata') or {}
        changed_fields = [key for key in sorted(set(a.get('fields',{}))|set(b.get('fields',{})))
                          if a.get('fields',{}).get(key)!=b.get('fields',{}).get(key)]
        if before.get('page_html')!=snapshot.get('page_html'):
            changed_fields.append('original_content')
        if a.get('authors')!=b.get('authors'):
            changed_fields.append('authors_identifiers')
    if changed_fields:
        upstream.update(last_change_at=store.now(), last_changed_fields=changed_fields)
    if snapshot:
        upstream['latest_snapshot_id'] = snapshot['id']
    if check.get('notice_evidence'):
        proof = check['notice_evidence']
        proofs = upstream.setdefault('notice_evidence', [])[:]
        if not any(p['sha256']==proof['sha256'] for p in proofs):
            proofs.append(proof)
        upstream['notice_evidence'] = proofs
        upstream['notice_coverage_limited'] = proof['has_more']
        upstream['notice_checked_at'] = proof['retrieved_at']
    upstream['notice_error'] = check.get('notice_error','')
    # Absence of a previously observed notice never silently removes the warning.
    registered = {json.dumps(n,sort_keys=True):n for p in upstream.get('notice_evidence',[]) for n in p['notices']}
    upstream['notices'] = list(registered.values())
    reasons = sorted(set((['changed'] if changed_fields else []) +
        [n['kind'] for n in upstream['notices']] +
        ([upstream['status']] if upstream['status']!='available' else []) +
        (['notice_check_failed'] if upstream['notice_error'] else []) +
        (['notice_coverage_limited'] if upstream.get('notice_coverage_limited') else [])))
    prior=old.get('exception',{})
    carry_change=bool(not changed_fields and prior and not prior.get('resolved') and 'changed' in prior['reasons'])
    if carry_change:
        reasons=sorted(set(reasons+['changed']))
        changed_fields=prior['fields']
    before_id=prior.get('before_snapshot_id') if carry_change else before['id'] if before else None
    after_id=prior.get('after_snapshot_id') if carry_change else snapshot['id'] if snapshot else None
    new_problem = (changed_fields or old.get('status','available')!=upstream['status']
        or old.get('notices',[])!=upstream['notices'] or old.get('notice_error','')!=upstream['notice_error']
        or old.get('notice_coverage_limited',False)!=upstream.get('notice_coverage_limited',False))
    if reasons and new_problem:
        signature = hashlib.sha256(json.dumps([reasons, after_id if changed_fields else None,
            upstream['notices']],sort_keys=True).encode()).hexdigest()
        prior = upstream.get('exception', {})
        if prior.get('signature') != signature:
            upstream['exception'] = dict(signature=signature, reasons=reasons, fields=changed_fields,
                before_snapshot_id=before_id, after_snapshot_id=after_id, created_at=store.now(), resolved=False)
    elif not reasons:
        prior=upstream.get('exception',{})
        temporary={'removed','access_limited','check_failed','notice_check_failed','notice_coverage_limited'}
        if prior and not prior.get('resolved') and set(prior['reasons'])<=temporary:
            upstream['exception']=dict(prior,resolved=True,resolved_at=store.now(),
                resolved_by=automatic['actor_id'],resolution='原入口及声明查询重查恢复；历史继续保留')
    automatic['upstream'] = upstream
    clocks = {'last_checked_at','notice_checked_at','last_successful_check_at'}
    return {k:v for k,v in old.items() if k not in clocks} != {k:v for k,v in upstream.items() if k not in clocks}


def same_observation(before, snapshot):
    if not before or not snapshot:
        return False
    if snapshot['content_kind']=='bibliographic_metadata' and before.get('metadata'):
        # Collection response bytes include neighbours and cursor positions.
        # Compare the actual work, preserving its raw dates, instead of the page.
        return before['metadata']['raw']['message']==snapshot['metadata']['raw']['message']
    return before['sha256']==snapshot['sha256']


def validate(acquired):
    upstream = acquired.get('upstream')
    if not upstream:
        return
    if upstream.get('status') not in {'available','removed','access_limited','check_failed'}:
        raise ValueError('上游重查状态无效。')
    snapshots=acquired.get('snapshots',[])
    ids={s['id'] for s in snapshots}
    dois={s.get('doi') for s in snapshots if s.get('doi')}
    if upstream.get('latest_snapshot_id') and upstream['latest_snapshot_id'] not in ids:
        raise ValueError('上游重查对应的原文版本缺失。')
    problem=upstream.get('exception')
    if problem and (type(problem.get('resolved')) is not bool
            or not isinstance(problem.get('reasons'),list) or not isinstance(problem.get('fields'),list)
            or any(problem.get(k) and problem[k] not in ids for k in ('before_snapshot_id','after_snapshot_id'))):
        raise ValueError('上游异常与原文版本绑定失败。')
    for proof in upstream.get('notice_evidence',[]):
        try:
            content = base64.b64decode(proof['raw_base64'], validate=True)
            payload = json.loads(content)
            url = 'https://api.crossref.org/works?'+urlencode(dict(filter='updates:'+proof['target_doi'],rows=NOTICE_LIMIT))
            items = payload['message']['items']
            if (proof['target_doi'] not in dois or len(content)!=proof['bytes'] or hashlib.sha256(content).hexdigest()!=proof['sha256']
                    or proof['url']!=url or payload['status']!='ok' or len(items)>NOTICE_LIMIT
                    or notices(items, proof['target_doi'])!=proof['notices']
                    or proof['has_more']!=(payload['message']['total-results']>len(items))):
                raise ValueError()
        except (ValueError,KeyError,TypeError,AttributeError):
            raise ValueError('上游声明与原始响应绑定失败。') from None
    expected = {json.dumps(n,sort_keys=True):n for p in upstream.get('notice_evidence',[]) for n in p['notices']}
    if upstream.get('notices')!=list(expected.values()):
        raise ValueError('上游声明投影与取得依据不一致。')


def exception_projection(db, access):
    rows = []
    for row in db.execute("SELECT * FROM records WHERE merged_into IS NULL AND visibility='shared' ORDER BY updated_at DESC,id"):
        if not access.visible(row):
            continue
        upstream = json.loads(row['raw_json'] or '{}').get('automatic_acquisition',{}).get('upstream',{})
        problem = upstream.get('exception',{})
        if problem and not problem.get('resolved'):
            rows.append(dict(record_id=row['id'], title=row['title'], version=row['version'], **problem))
            if len(rows)==101:
                break
    return dict(items=rows[:100], has_more=len(rows)>100, limit=100)


def register(app, ctx):
    @app.get('/api/ingestion/exceptions')
    def exceptions():
        ctx.admin()
        return jsonify(exception_projection(ctx.db(),ctx.records()))

    @app.post('/api/records/<rid>/upstream/acknowledge')
    def acknowledge(rid):
        ctx.admin()
        from .record_revisions import check_version
        access, db = ctx.records(), ctx.db()
        data = ctx.body()
        with access._transaction():
            row = access.get(rid)
            check_version(data,row)
            raw = json.loads(row['raw_json'] or '{}')
            problem = raw.get('automatic_acquisition',{}).get('upstream',{}).get('exception')
            if not problem or problem['signature']!=data.get('signature'):
                abort(409,'重查结果已变化，请刷新后核对。')
            problem.update(resolved=True, resolved_by=ctx.user()['id'], resolved_at=store.now())
            access._finish(row, dict(raw_json=json.dumps(raw,ensure_ascii=False)), '已核看上游异常；原始材料、提示与人工字段保留')
        return jsonify(ok=True)
