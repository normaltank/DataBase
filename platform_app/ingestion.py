"""Fixed-source durable acquisition. The web only configures and queues work."""
import argparse
import base64
import hashlib
import io
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from flask import abort, jsonify, send_file

from . import discovery, identity, intake, store, workflow

SCHEMA_VERSION = 17
SYSTEM_ID = 'system-public-ingestion'
LEASE_SECONDS = 120
ADAPTER = 'liia-opinions-auto-v1'


def later(seconds):
    return (datetime.fromisoformat(store.now()) + timedelta(seconds=seconds)).isoformat(timespec='seconds')


def migrate(data_dir):
    db = store.connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute('''INSERT INTO users(id,username,name,password_hash,role,active)
                VALUES (?,?,?,'!','system',0)''', (SYSTEM_ID, SYSTEM_ID, '系统 · 公开来源采集'))
            db.execute('''CREATE TABLE ingestion_sources (
                source_id TEXT PRIMARY KEY REFERENCES sources(id), enabled INTEGER NOT NULL DEFAULT 0,
                frequency_hours INTEGER NOT NULL DEFAULT 24, initial_days INTEGER NOT NULL DEFAULT 30,
                inclusion_rule TEXT NOT NULL DEFAULT 'research_only', next_run TEXT NOT NULL,
                last_attempt TEXT NOT NULL DEFAULT '', last_success TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '', cursor TEXT NOT NULL DEFAULT '',
                coverage_json TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL, updated_by TEXT NOT NULL REFERENCES users(id))''')
            db.execute('''CREATE TABLE ingestion_runs (
                id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),
                status TEXT NOT NULL DEFAULT 'queued',stage TEXT NOT NULL DEFAULT 'feed',
                lease_token TEXT NOT NULL DEFAULT '',lease_until TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',
                coverage_json TEXT NOT NULL DEFAULT '{}',feed_bytes BLOB,feed_sha256 TEXT NOT NULL DEFAULT '')''')
            db.execute('''CREATE UNIQUE INDEX ingestion_one_active_run ON ingestion_runs(source_id)
                WHERE status IN ('queued','running')''')
            db.execute('''CREATE TABLE ingestion_entries (
                id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
                source_id TEXT NOT NULL REFERENCES sources(id),entry_id TEXT NOT NULL,evidence_json TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,
                record_id TEXT REFERENCES records(id),error TEXT NOT NULL DEFAULT '',reason TEXT NOT NULL DEFAULT '',
                UNIQUE(run_id,entry_id))''')
            db.execute('''CREATE TABLE automatic_processing (
                record_id TEXT PRIMARY KEY REFERENCES records(id),source_version INTEGER NOT NULL,
                input_hash TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending_configuration',
                reason TEXT NOT NULL DEFAULT '未配置自动中文处理与月额度；原始题录可读',created_at TEXT NOT NULL)''')
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('ingestion_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def configuration(db, sid):
    row = db.execute('SELECT * FROM ingestion_sources WHERE source_id=?', (sid,)).fetchone()
    result = dict(row) if row else dict(source_id=sid, enabled=False, frequency_hours=24, initial_days=30,
        inclusion_rule='research_only', next_run='', last_attempt='', last_success='', last_error='', cursor='',
        coverage_json='{}', version=0)
    result['enabled'] = bool(result['enabled'])
    result['coverage'] = json.loads(result.pop('coverage_json'))
    result.update(feed_url=discovery.FEED, column_url=discovery.COLUMN)
    result['runs'] = []
    for row in db.execute('SELECT * FROM ingestion_runs WHERE source_id=? ORDER BY created_at DESC,rowid DESC LIMIT 10',(sid,)):
        run = {k:row[k] for k in row.keys() if k not in {'feed_bytes','lease_token'}}
        run['coverage'] = json.loads(run.pop('coverage_json'))
        run['entries'] = []
        for entry in db.execute('SELECT * FROM ingestion_entries WHERE run_id=? ORDER BY rowid',(row['id'],)):
            item = {k:entry[k] for k in entry.keys() if k != 'evidence_json'}
            evidence = json.loads(entry['evidence_json'])
            item.update(title=evidence['fields']['title'],url=evidence['fields']['url'],raw=evidence['raw'])
            run['entries'].append(item)
        result['runs'].append(run)
    return result


class PageParser(HTMLParser):
    """Capture the official article container and separately labelled sidebar credit."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.capture = None
        self.author = None
        self.author_strong = None
        self.fragments = []
        self.author_fragments = []
        self.credit_fragments = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        void = tag in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
        if self.capture is None and tag == 'div' and 'article' in attrs.get('class','').split():
            self.capture = self.depth
        elif self.capture is not None:
            self.fragments.append(self.get_starttag_text())
        if tag == 'p' and 'author' in attrs.get('class','').split():
            self.author = self.depth
        if self.author is not None and tag == 'strong':
            self.author_strong = self.depth
        if not void:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            return
        self.depth = max(0,self.depth-1)
        if self.capture is not None:
            if self.depth == self.capture:
                self.capture = None
            else:
                self.fragments.append('</'+tag+'>')
        if self.author is not None and self.depth == self.author:
            self.author = None
        if self.author_strong is not None and self.depth == self.author_strong:
            self.author_strong = None

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.capture is not None:
            self.fragments.append(data)
        if self.author is not None:
            self.author_fragments.append(data)
        if self.author_strong is not None:
            self.credit_fragments.append(data)

    def handle_entityref(self, name):
        self.handle_data('&'+name+';')

    def handle_charref(self, name):
        self.handle_data('&#'+name+';')


def page_snapshot(document):
    if document['content_type'] not in {'text/html','application/xhtml+xml'}:
        raise intake.AcquisitionError('文章页不是 HTML；未取得网页正文。')
    parser = PageParser()
    parser.feed(document['text'])
    cleaned, text = workflow.clean_rich(''.join(parser.fragments))
    content = document['bytes']
    return dict(id=hashlib.sha256(content).hexdigest(),url=document['url'],retrieved_at=store.now(),
        sha256=hashlib.sha256(content).hexdigest(),bytes=len(content),raw_base64=base64.b64encode(content).decode(),
        content_type=document['content_type'],adapter=ADAPTER,page_html=cleaned,page_text=text,
        sidebar_credit=intake.plain(' '.join(parser.credit_fragments or parser.author_fragments)),
        sidebar_credit_raw=intake.plain(' '.join(parser.author_fragments)),
        content_kind='webpage_description' if text else 'no_body',work_body_available=False,
        work_body=None,work_body_basis='',
        reason='已保存文章页原字节与清洗说明；未验证所指作品全文，不能据此生成观点概述。' if text else '文章页没有可辨认的正文容器。')


def acquisition_projection(row):
    raw = json.loads(row['raw_json'] or '{}')
    result = raw.get('automatic_acquisition')
    if not result:
        return None
    result = dict(result)
    result['snapshots'] = [{k:v for k,v in snapshot.items() if k != 'raw_base64'} |
        dict(download_url='/api/records/'+row['id']+'/snapshots/'+snapshot['id']) for snapshot in result.get('snapshots',[])]
    return result


def substantive_input(snapshot):
    """Future processing seam: page text alone never authorizes a work summary.

    Adapters may supply an independently evidenced work body. This pilot's LIIA
    extractor deliberately supplies none; it preserves source-page descriptions.
    """
    if not snapshot.get('work_body_available') or not snapshot.get('work_body_basis'):
        return None
    body = snapshot.get('work_body')
    return body if isinstance(body,dict) and body.get('text') else None


def searchable_text(row):
    raw = json.loads(row['raw_json'] or '{}')
    snapshots = raw.get('automatic_acquisition',{}).get('snapshots',[])
    return snapshots[-1]['page_text'] if snapshots else ''


def validate_backup(db):
    actor = db.execute('SELECT * FROM users WHERE id=?',(SYSTEM_ID,)).fetchone()
    if not actor or actor['active'] or actor['role'] != 'system' or actor['password_hash'] != '!':
        raise ValueError('自动取得系统主体不完整或可登录。')
    for row in db.execute('SELECT * FROM records'):
        acquired = json.loads(row['raw_json'] or '{}').get('automatic_acquisition')
        if not acquired:
            continue
        for snapshot in acquired.get('snapshots',[]):
            try:
                content = base64.b64decode(snapshot['raw_base64'],validate=True)
                if len(content) != snapshot['bytes'] or hashlib.sha256(content).hexdigest() != snapshot['sha256']:
                    raise ValueError()
                if type(snapshot['work_body_available']) is not bool or snapshot['content_kind'] not in {'webpage_description','no_body','work_body'}:
                    raise ValueError()
                if snapshot['work_body_available']:
                    body = snapshot.get('work_body')
                    if not snapshot.get('work_body_basis') or not isinstance(body,dict) or not body.get('text') or workflow.clean_rich(body['html'])[1] != body['text']:
                        raise ValueError()
                clean_html, clean_text = workflow.clean_rich(snapshot['page_html'])
                if clean_text != snapshot['page_text'] or clean_html != snapshot['page_html']:
                    raise ValueError()
            except (ValueError,KeyError,TypeError):
                raise ValueError('自动取得原文快照校验失败。') from None
    for run in db.execute('SELECT * FROM ingestion_runs'):
        if run['status'] not in {'queued','running','failed','partial','succeeded'}:
            raise ValueError('采集任务状态无效。')
        if run['feed_bytes'] is not None and hashlib.sha256(run['feed_bytes']).hexdigest() != run['feed_sha256']:
            raise ValueError('采集 RSS 原字节校验失败。')
    for row in db.execute('SELECT * FROM ingestion_sources'):
        if row['enabled'] not in {0,1} or not 1 <= row['frequency_hours'] <= 720 or row['initial_days'] != 30 or row['inclusion_rule'] not in {'research_only','all_opinions'}:
            raise ValueError('采集来源配置无效。')


def _claim(db):
    stamp = store.now()
    with db:
        db.execute('BEGIN IMMEDIATE')
        for config in db.execute('SELECT * FROM ingestion_sources WHERE enabled=1 AND next_run<=?',(stamp,)).fetchall():
            source = identity.resolve(db,'sources',config['source_id'])
            if source is None or not discovery.supported(source) or source['id'] != config['source_id']:
                db.execute("UPDATE ingestion_sources SET last_error=?,enabled=0 WHERE source_id=?",('来源已变化或合并；请管理员重新确认启用。',config['source_id']))
                continue
            active = db.execute("SELECT 1 FROM ingestion_runs WHERE source_id=? AND status IN ('queued','running')",(config['source_id'],)).fetchone()
            if not active:
                db.execute('INSERT INTO ingestion_runs(id,source_id,created_at) VALUES (?,?,?)',(uuid.uuid4().hex,config['source_id'],stamp))
        run = db.execute('''SELECT r.* FROM ingestion_runs r JOIN ingestion_sources s ON s.source_id=r.source_id
            WHERE s.enabled=1 AND (r.status='queued' OR (r.status='running' AND r.lease_until<=?))
            ORDER BY r.created_at,r.rowid LIMIT 1''',(stamp,)).fetchone()
        if not run:
            return None
        token = uuid.uuid4().hex
        db.execute("UPDATE ingestion_runs SET status='running',attempts=attempts+1,lease_token=?,lease_until=?,started_at=? WHERE id=?",(token,later(LEASE_SECONDS),stamp,run['id']))
        db.execute('UPDATE ingestion_sources SET last_attempt=?,last_error=? WHERE source_id=?',(stamp,'',run['source_id']))
        return dict(run) | dict(lease_token=token)


def _owns(db, run):
    return db.execute('''SELECT 1 FROM ingestion_runs r JOIN ingestion_sources s ON s.source_id=r.source_id
        WHERE r.id=? AND r.lease_token=? AND r.status='running' AND r.lease_until>? AND s.enabled=1''',
        (run['id'],run['lease_token'],store.now())).fetchone() is not None


def _renew(db, run):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not _owns(db,run):
            raise intake.AcquisitionError('任务租约失效或来源已停用；已提交结果保留。')
        db.execute('UPDATE ingestion_runs SET lease_until=? WHERE id=?',(later(LEASE_SECONDS),run['id']))


def _feed(db, run):
    document = intake.fetch_document(discovery.FEED,time.monotonic()+intake.MAX_SECONDS,fixed_feed=discovery.FEEDS)
    config = configuration(db,run['source_id'])
    previous = json.loads(config['cursor']) if config['cursor'] else None
    seen = set(previous.get('seen_urls',[])) if previous is not None else None
    admitted = {json.loads(row[0])['fields']['url'] for row in db.execute("SELECT evidence_json FROM ingestion_entries WHERE source_id=? AND stage<>'excluded'",(run['source_id'],))}
    result = discovery._parse(document['bytes'],store.now(),run['source_id'],previously_seen=seen,admitted_urls=admitted)
    coverage = {k:v for k,v in result.items() if k != 'items'}
    coverage.update(scope='仅当前固定 RSS；没有遍历栏目或历史回填',coverage_complete=False,
        zero_interpretation='零条只表示本次窗口未返回可纳入条目，不证明来源没有更新。' if not result['items'] else '',
        cursor=dict(kind='rss_response_and_seen_identities',sha256=result['sha256'],window=result['window'],returned=result['returned'],
            seen_urls=sorted((seen or set())|set(result['observed_urls']))))
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not _owns(db,run):
            raise intake.AcquisitionError('取得后任务租约失效；未提交题录。')
        for item in result['items']:
            evidence = item['evidence']
            title = item['fields']['title'].casefold()
            excluded = config['inclusion_rule'] == 'research_only' and any(word in title for word in ('vacancy','job opening','registration','annual general meeting','job vacancy'))
            db.execute('''INSERT OR IGNORE INTO ingestion_entries(id,run_id,source_id,entry_id,evidence_json,stage,reason)
                VALUES (?,?,?,?,?,?,?)''',(uuid.uuid4().hex,run['id'],run['source_id'],evidence['entry_id'],json.dumps(evidence,ensure_ascii=False),
                'excluded' if excluded else 'queued','规则排除一般事务通知；可调整为全部 Opinions 后重跑。' if excluded else '固定研究栏目；保留原文类别待分类'))
        db.execute("UPDATE ingestion_runs SET stage='entries',coverage_json=?,feed_bytes=?,feed_sha256=? WHERE id=?",
            (json.dumps(coverage,ensure_ascii=False),document['bytes'],result['sha256'],run['id']))


def run_pending(data_dir, limit=1):
    """Process at most limit durable runs. No Flask session, member token or AI call."""
    from .record_revisions import RecordRevisions
    data_dir = Path(data_dir)
    db = store.connect(data_dir/'platform.sqlite3')
    totals = dict(runs=0,saved=0,failed=0,excluded=0,blocked=0)
    try:
        for _ in range(limit):
            run = _claim(db)
            if not run:
                break
            totals['runs'] += 1
            if not intake._slots.acquire(blocking=False):
                with db:
                    db.execute("UPDATE ingestion_runs SET status='queued',lease_token='',lease_until='' WHERE id=? AND lease_token=?",(run['id'],run['lease_token']))
                break
            try:
                if run['stage'] == 'feed':
                    _feed(db,run)
                entries = db.execute("SELECT * FROM ingestion_entries WHERE run_id=? AND stage IN ('queued','acquiring','failed') ORDER BY rowid",(run['id'],)).fetchall()
                for entry in entries:
                    _renew(db,run)
                    with db:
                        db.execute("UPDATE ingestion_entries SET stage='acquiring',attempts=attempts+1,error='' WHERE id=?",(entry['id'],))
                    snapshot, error = None, ''
                    try:
                        evidence = json.loads(entry['evidence_json'])
                        document = intake.fetch_document(evidence['fields']['url'],time.monotonic()+intake.MAX_SECONDS)
                        snapshot = page_snapshot(document)
                    except (intake.AcquisitionError,ValueError) as failure:
                        error = str(failure)
                    try:
                        actor = dict(id=SYSTEM_ID,role='system',name='系统 · 公开来源采集')
                        outcome = RecordRevisions(db,actor,data_dir/'uploads').ingest_public(entry['id'],run['lease_token'],snapshot,error)
                        if outcome in totals:
                            totals[outcome] += 1
                    except Exception as failure:
                        db.rollback()
                        with db:
                            if _owns(db,run):
                                db.execute("UPDATE ingestion_entries SET stage='failed',error=? WHERE id=?",('正式保存失败：'+str(failure)[:500],entry['id']))
                        totals['failed'] += 1
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    if _owns(db,run):
                        counts = {r['stage']:r['n'] for r in db.execute('SELECT stage,COUNT(*) n FROM ingestion_entries WHERE run_id=? GROUP BY stage',(run['id'],))}
                        failed = counts.get('failed',0)
                        error = str(failed)+' 条取得或保存失败，可重跑。' if failed else ''
                        db.execute("UPDATE ingestion_runs SET status=?,stage='done',finished_at=?,error=?,lease_until='' WHERE id=?",('partial' if failed else 'succeeded',store.now(),error,run['id']))
                        coverage = db.execute('SELECT coverage_json FROM ingestion_runs WHERE id=?',(run['id'],)).fetchone()[0]
                        db.execute('''UPDATE ingestion_sources SET next_run=?,last_success=?,last_error=?,coverage_json=?,cursor=? WHERE source_id=?''',
                            (later(configuration(db,run['source_id'])['frequency_hours']*3600),store.now(),error,coverage,json.dumps(json.loads(coverage).get('cursor',{})),run['source_id']))
            except Exception as failure:
                db.rollback()
                with db:
                    if _owns(db,run):
                        db.execute("UPDATE ingestion_runs SET status='failed',finished_at=?,error=?,lease_until='' WHERE id=?",(store.now(),str(failure)[:500],run['id']))
                        db.execute('UPDATE ingestion_sources SET last_error=?,next_run=? WHERE source_id=?',(str(failure)[:500],later(3600),run['source_id']))
                totals['failed'] += 1
            finally:
                intake._slots.release()
        return totals
    finally:
        db.close()


def register(app, ctx):
    @app.post('/api/sources/<sid>/ingestion/run')
    def queue_ingestion(sid):
        ctx.admin()
        if ctx.body():
            abort(400,'固定来源运行不接受额外参数。')
        db = ctx.db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            source = discovery.source_for(db,sid)
            config = db.execute('SELECT * FROM ingestion_sources WHERE source_id=? AND enabled=1',(source['id'],)).fetchone()
            if not config:
                abort(409,'请先启用来源。')
            active = db.execute("SELECT id FROM ingestion_runs WHERE source_id=? AND status IN ('queued','running')",(source['id'],)).fetchone()
            if not active:
                db.execute('INSERT INTO ingestion_runs(id,source_id,created_at) VALUES (?,?,?)',(uuid.uuid4().hex,source['id'],store.now()))
            db.execute('UPDATE ingestion_sources SET next_run=? WHERE source_id=?',(store.now(),source['id']))
        return jsonify(configuration(db,source['id']))

    @app.post('/api/ingestion/runs/<run_id>/retry')
    def retry_ingestion(run_id):
        ctx.admin()
        if ctx.body():
            abort(400,'重跑不接受额外参数。')
        db = ctx.db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            run = db.execute('SELECT * FROM ingestion_runs WHERE id=?',(run_id,)).fetchone()
            if not run:
                abort(404,'任务不存在。')
            config = db.execute('SELECT * FROM ingestion_sources WHERE source_id=? AND enabled=1',(run['source_id'],)).fetchone()
            if not config:
                abort(409,'来源已停用，请管理员重新启用。')
            if run['status'] not in {'failed','partial'}:
                abort(409,'仅失败或部分失败的任务可重跑；运行中任务将在租约到期后续作。')
            if db.execute("SELECT 1 FROM ingestion_runs WHERE source_id=? AND status IN ('queued','running')",(run['source_id'],)).fetchone():
                abort(409,'此来源已有待运行或运行中任务。')
            db.execute("UPDATE ingestion_runs SET status='queued',stage=?,error='',finished_at='',lease_token='',lease_until='' WHERE id=?",
                ('entries' if run['feed_bytes'] is not None else 'feed',run_id))
        return jsonify(configuration(db,run['source_id']))

    @app.get('/api/records/<rid>/snapshots/<snapshot_id>')
    def download_snapshot(rid,snapshot_id):
        row = ctx.records().get(rid)
        raw = json.loads(row['raw_json'] or '{}')
        snapshot = next((s for s in raw.get('automatic_acquisition',{}).get('snapshots',[]) if s['id']==snapshot_id),None)
        if not snapshot:
            abort(404,'原文快照不存在。')
        return send_file(io.BytesIO(base64.b64decode(snapshot['raw_base64'])),mimetype='application/octet-stream',
            as_attachment=True,download_name='source-'+snapshot['sha256'][:16]+'.html.txt')

    @app.get('/api/ingestion/runs/<run_id>/rss')
    def download_feed(run_id):
        ctx.admin()
        run = ctx.db().execute('SELECT * FROM ingestion_runs WHERE id=?',(run_id,)).fetchone()
        if not run or run['feed_bytes'] is None:
            abort(404,'本轮尚未成功取得 RSS 原字节。')
        return send_file(io.BytesIO(run['feed_bytes']),mimetype='application/octet-stream',as_attachment=True,
            download_name='rss-'+run['feed_sha256'][:16]+'.xml')

    @app.get('/api/ingestion')
    def ingestion_status():
        ctx.admin()
        rows = [r for r in ctx.db().execute('SELECT * FROM sources WHERE merged_into IS NULL') if discovery.supported(r)]
        heartbeat = ctx.db().execute("SELECT value FROM settings WHERE key='ingestion_worker_heartbeat'").fetchone()
        return jsonify(items=[dict(name=r['name'], **configuration(ctx.db(), r['id'])) for r in rows],worker_heartbeat=heartbeat[0] if heartbeat else '')

    @app.get('/api/sources/<sid>/ingestion')
    def ingestion_configuration(sid):
        ctx.admin()
        source = discovery.source_for(ctx.db(), sid)
        return jsonify(configuration(ctx.db(), source['id']))

    @app.put('/api/sources/<sid>/ingestion')
    def configure_ingestion(sid):
        ctx.admin()
        data = ctx.body()
        if set(data) - {'enabled', 'frequency_hours', 'inclusion_rule'}:
            abort(400, '只可调整启用、频率和既有 Opinions 栏目纳入规则。')
        if type(data.get('enabled')) is not bool or type(data.get('frequency_hours', 24)) is not int or not 1 <= data.get('frequency_hours',24) <= 720:
            abort(400, '启用状态或巡检频率无效。')
        if data.get('inclusion_rule','research_only') not in {'research_only','all_opinions'}:
            abort(400, '纳入规则无效。')
        db = ctx.db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            source = discovery.source_for(db, sid)
            db.execute('''INSERT INTO ingestion_sources(source_id,enabled,frequency_hours,inclusion_rule,next_run,updated_at,updated_by)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET enabled=excluded.enabled,
                frequency_hours=excluded.frequency_hours,inclusion_rule=excluded.inclusion_rule,
                next_run=CASE WHEN ingestion_sources.enabled=0 THEN excluded.next_run ELSE ingestion_sources.next_run END,
                version=ingestion_sources.version+1,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
                (source['id'],int(data['enabled']),data.get('frequency_hours',24),data.get('inclusion_rule','research_only'),store.now(),store.now(),ctx.user()['id']))
        return jsonify(configuration(db, source['id']))


def main():
    parser = argparse.ArgumentParser(description='固定公开来源持久采集与公开材料中文处理后台')
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--poll-seconds',type=int,default=30)
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 3600:
        parser.error('poll-seconds must be between 1 and 3600')
    store.initialize(args.data_dir)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    while True:
        db = store.connect(args.data_dir/'platform.sqlite3')
        try:
            with db:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('ingestion_worker_heartbeat',?)",(store.now(),))
        finally:
            db.close()
        result = run_pending(args.data_dir,limit=5)
        from .automatic_processing import run_pending as process_pending
        result['chinese_processing'] = process_pending(args.data_dir,limit=5)
        if result['runs']:
            logging.info('public_ingestion %s',json.dumps(result))
        if args.once:
            print(json.dumps(result))
            return
        time.sleep(args.poll_seconds)


if __name__ == '__main__':
    main()
