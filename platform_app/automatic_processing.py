"""Durable processing of saved public acquisition evidence, never arbitrary record fields."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from . import ai_gateway, ingestion, store, translations, workflow

LEASE_SECONDS = 120
RULE = 'public-chinese-v1'


def create_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS automatic_tasks (
        id TEXT PRIMARY KEY,record_id TEXT NOT NULL REFERENCES records(id),task TEXT NOT NULL,
        input_hash TEXT NOT NULL,input_json TEXT NOT NULL,source_version INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',reason TEXT NOT NULL DEFAULT '',
        lease_token TEXT NOT NULL DEFAULT '',lease_until TEXT NOT NULL DEFAULT '',
        next_run TEXT NOT NULL,created_at TEXT NOT NULL,finished_at TEXT NOT NULL DEFAULT '',
        result_json TEXT NOT NULL DEFAULT '{}',evidence_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(record_id,task,input_hash))''')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def material(db, row):
    if not row or row['merged_into'] or row['visibility']!='shared' or row['kind'] in workflow.CONTENT_KINDS:
        return None
    raw=json.loads(row['raw_json'] or '{}')
    automatic=raw.get('automatic_acquisition',{})
    if automatic.get('actor_id')!=ingestion.SYSTEM_ID:
        return None
    evidence=next((e for e in reversed(raw.get('discovery_evidence',[]))
        if e.get('processing_actor')==ingestion.SYSTEM_ID and e.get('processing_version')==ingestion.ADAPTER),None)
    if not evidence or not db.execute('SELECT 1 FROM ingestion_sources WHERE source_id=? AND enabled=1',(evidence.get('source_id'),)).fetchone():
        return None
    # saved_fields/current row may contain human corrections. Only fetched fields are public input.
    fields=evidence.get('fields',{})
    title=fields.get('original_title') or fields.get('title','')
    abstract=fields.get('abstract','')
    if not isinstance(title,str) or not title.strip() or not isinstance(abstract,str):
        return None
    return {'title':title,'abstract':abstract}


def synchronize(db, limit=500):
    with db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('SELECT r.* FROM automatic_processing a JOIN records r ON r.id=a.record_id ORDER BY a.created_at LIMIT ?',(limit,)).fetchall():
            value=material(db,row)
            if not value:
                continue
            db.execute('''INSERT OR IGNORE INTO automatic_tasks
                (id,record_id,task,input_hash,input_json,source_version,next_run,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',(uuid.uuid4().hex,row['id'],'translation',digest(value),json.dumps(value,ensure_ascii=False),row['version'],store.now(),store.now()))


def later(seconds):
    return (datetime.fromisoformat(store.now())+timedelta(seconds=seconds)).isoformat(timespec='seconds')


def authorized(db, job):
    row=db.execute('SELECT * FROM records WHERE id=?',(job['record_id'],)).fetchone()
    return material(db,row)==json.loads(job['input_json'])


def execute(db, job):
    output,evidence,error,code={}, {}, '', ''
    try:
        value=json.loads(job['input_json'])
        output,evidence=translations.request_translation(db,job['record_id'],value['title'],value['abstract'],lambda:authorized(db,job))
    except ValueError as failure:
        error=str(failure)
        code=getattr(failure,'code','invalid_result')
        evidence=getattr(failure,'evidence',{})
    with db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT * FROM automatic_tasks WHERE id=?',(job['id'],)).fetchone()
        if current['lease_token']!=job['lease_token']:
            return False
        if not authorized(db,job):
            error,code='公开材料或当前权限已变化，未写回结果。','permission'
        state='succeeded' if not error else 'failed' if code in {'retry_limit','permission'} else 'paused'
        if not error:
            value=json.loads(job['input_json'])
            jid='AUTO-'+job['id']
            row=db.execute('SELECT * FROM records WHERE id=?',(job['record_id'],)).fetchone()
            db.execute('''INSERT OR IGNORE INTO translation_jobs
                (id,record_id,actor_id,request_id,source_version,input_title,input_abstract,input_hash,
                source_url,source_doi,created_at,status,attempts,output_title,output_abstract,model,finished_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,'succeeded',1,?,?,?,?)''',
                (jid,row['id'],ingestion.SYSTEM_ID,jid,job['source_version'],value['title'],value['abstract'],
                 translations.digest(value['title'],value['abstract']),row['url'],row['doi'],job['created_at'],
                 output['title'].strip(),output['abstract'].strip(),evidence.get('response_model',''),store.now()))
            db.execute('INSERT OR IGNORE INTO translation_calls VALUES(?,?,?,?,?)',
                (uuid.uuid4().hex,jid,1,json.dumps({**evidence,'outcome':'succeeded','started_at':job['created_at'],'finished_at':store.now()}),store.now()))
        db.execute('''UPDATE automatic_tasks SET status=?,reason=?,lease_token='',lease_until='',next_run=?,
            finished_at=?,result_json=?,evidence_json=? WHERE id=?''',
            (state,error,later(30),store.now(),json.dumps(output if not error else {},ensure_ascii=False),json.dumps(evidence),job['id']))
        db.execute('UPDATE automatic_processing SET status=?,reason=? WHERE record_id=?',(state,error,job['record_id']))
    return not error


def run_pending(data_dir, limit=5):
    db=store.connect(Path(data_dir)/'platform.sqlite3')
    result={'tasks':0,'succeeded':0,'paused':0}
    try:
        synchronize(db)
        with db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('automatic_worker_heartbeat',?)",(store.now(),))
        for unused in range(limit):
            with db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute("SELECT * FROM automatic_tasks WHERE (status IN ('queued','paused') AND next_run<=?) OR (status='running' AND lease_until<=?) ORDER BY created_at,rowid LIMIT 1",(store.now(),store.now())).fetchone()
                if not row:
                    break
                job=dict(row)
                job['lease_token']=uuid.uuid4().hex
                db.execute("UPDATE automatic_tasks SET status='running',lease_token=?,lease_until=? WHERE id=?",(job['lease_token'],later(LEASE_SECONDS),job['id']))
            result['tasks']+=1
            result['succeeded' if execute(db,job) else 'paused']+=1
        return result
    finally:
        db.close()
