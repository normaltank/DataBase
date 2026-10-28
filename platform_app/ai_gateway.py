"""Shared fail-closed AI reservation ledger. Amounts are integer microcurrency units."""
import hashlib
import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from flask import abort, jsonify
from .store import connect, now

SCHEMA_VERSION = 19
SCALE = 1000000


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute('''CREATE TABLE ai_attempts (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, task TEXT NOT NULL,input_hash TEXT NOT NULL,
                month TEXT NOT NULL,currency TEXT NOT NULL,price_json TEXT NOT NULL,config_json TEXT NOT NULL,
                input_bound INTEGER NOT NULL,output_bound INTEGER NOT NULL,reserved_units INTEGER NOT NULL,
                charged_units INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,created_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}')''')
            db.execute('CREATE INDEX ai_input ON ai_attempts(scope,task,input_hash)')
            # Legacy running jobs may already have been billed. Preserve uncertainty and refuse automatic retry.
            db.execute("UPDATE translation_jobs SET status='failed',error='旧任务调用费用未知；禁止自动重试，请管理员核对供应商账单。' WHERE status='running'")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('ai_legacy_unknown',?)", (str(db.execute("SELECT changes()").fetchone()[0]),))
            db.execute("UPDATE settings SET value='19' WHERE key='schema_version'")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('ai_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def local_policy(db, config):
    try:
        policy_row = db.execute("SELECT value FROM settings WHERE key='ai_policy'").fetchone()
        policy = json.loads(policy_row[0]) if policy_row else {}
        cap = Decimal(policy.get('cap', ''))
        currency = policy.get('currency', '')
        price = config['pricing']
        if not cap.is_finite() or cap <= 0 or cap > Decimal('1000000000'):
            raise ValueError()
        if not price or price['currency'] != currency or not re.fullmatch('[A-Z]{3}', currency):
            raise ValueError()
        return int((cap * SCALE).to_integral_value(rounding='ROUND_FLOOR')), currency, price
    except (ValueError, KeyError, InvalidOperation):
        raise ValueError('AI未启用：需在本地配置正月额度、匹配币种及有效模型价格版本。') from None


def cost(tokens, price):
    return int(tokens.to_integral_value(rounding=ROUND_CEILING))


def reserve(db, scope, task, payload, config):
    cap, currency, price = local_policy(db, config)
    serialized = json.dumps(payload, ensure_ascii=True).encode()
    input_hash = hashlib.sha256(serialized).hexdigest()
    # Each UTF-8 byte can conservatively represent one token; include provider chat framing.
    bound = len(serialized) + 1024
    if bound > 128000:
        raise ValueError('AI输入超过安全上界；原始材料仍可阅读。')
    output = payload['max_tokens']
    worst = max(Decimal(price['input_cache_hit_per_million']), Decimal(price['input_cache_miss_per_million']))
    reserved = cost(Decimal(bound) * worst + Decimal(output) * Decimal(price['output_per_million']), price)
    if reserved <= 0:
        raise ValueError('AI价格必须支持非零保守预留。')
    month = now()[:7]  # UTC month; frozen on every attempt.
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT value FROM settings WHERE key='ai_paused'").fetchone() == ('1',):
            raise ValueError('管理员已暂停AI。')
        pause = db.execute("SELECT value FROM settings WHERE key='ai_paused'").fetchone()
        legacy = db.execute("SELECT value FROM settings WHERE key='ai_legacy_unknown'").fetchone()
        if (pause and pause[0]=='1') or (legacy and int(legacy[0])>0):
            raise ValueError('AI暂停：管理员暂停或旧调用费用待核对。')
        rows = db.execute('SELECT * FROM ai_attempts WHERE scope=? AND task=? AND input_hash=? ORDER BY rowid', (scope,task,input_hash)).fetchall()
        if any(r['status'] in {'sent','unknown'} for r in rows):
            raise ValueError('该输入已有费用未知调用；保留占用，禁止重复发送。')
        success = next((r for r in rows if r['status']=='settled' and json.loads(r['result_json'])), None)
        if success:
            return dict(success), True
        if len(rows) >= 3 or (rows and (now() < rows[-1]['finished_at'] or now()[:19] == rows[-1]['finished_at'][:19])):
            raise ValueError('该输入重试达到上限或正在退避，请稍后处理。')
        if db.execute("SELECT COUNT(*) FROM ai_attempts WHERE status IN ('sent','unknown')").fetchone()[0] >= 2:
            raise ValueError('AI全局并发或未知费用占用已满。')
        monthly = db.execute('SELECT * FROM ai_attempts WHERE month=?', (month,)).fetchall()
        if any(r['currency'] != currency for r in monthly):
            raise ValueError('本月账本币种已冻结，不能通过切换币种绕过额度。')
        used = sum(r['reserved_units'] if r['status'] in {'sent','unknown'} else r['charged_units'] for r in monthly)
        if used + reserved > cap:
            raise ValueError('AI本月额度不足，原文仍可阅读；新月或调整配置后续作。')
        aid = uuid.uuid4().hex
        db.execute('''INSERT INTO ai_attempts(id,scope,task,input_hash,month,currency,price_json,config_json,
            input_bound,output_bound,reserved_units,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'sent',?)''',
            (aid,scope,task,input_hash,month,currency,json.dumps(price),json.dumps(config),bound,output,reserved,now()))
        return dict(db.execute('SELECT * FROM ai_attempts WHERE id=?', (aid,)).fetchone()), False


def settle(db, attempt, evidence, result):
    usage = evidence.get('usage', {})
    valid = (all(type(usage.get(k)) is int and usage[k]>=0 for k in ['prompt_tokens','completion_tokens','total_tokens'])
             and usage.get('total_tokens') == usage.get('prompt_tokens',0)+usage.get('completion_tokens',0)
             and usage.get('prompt_tokens',0) <= attempt['input_bound']
             and usage.get('completion_tokens',0) <= attempt['output_bound']
             and evidence.get('response_model') == json.loads(attempt['config_json'])['model'])
    for key in ['prompt_cache_hit_tokens','prompt_cache_miss_tokens']:
        if key in usage and usage[key] > usage.get('prompt_tokens',0):
            valid = False
    if all(k in usage for k in ['prompt_cache_hit_tokens','prompt_cache_miss_tokens']):
        valid = valid and usage['prompt_cache_hit_tokens']+usage['prompt_cache_miss_tokens']==usage.get('prompt_tokens')
    details = usage.get('prompt_tokens_details', {})
    if 'cached_tokens' in details:
        valid = valid and details['cached_tokens'] <= usage.get('prompt_tokens',0)
    price = json.loads(attempt['price_json'])
    hit = usage.get('prompt_cache_hit_tokens', details.get('cached_tokens', 0))
    if 'prompt_cache_miss_tokens' in usage and 'prompt_cache_hit_tokens' not in usage:
        hit = usage.get('prompt_tokens',0)-usage['prompt_cache_miss_tokens']
    charged = (cost(Decimal(hit)*Decimal(price['input_cache_hit_per_million']) + Decimal(usage['prompt_tokens']-hit)*Decimal(price['input_cache_miss_per_million']) + Decimal(usage['completion_tokens'])*Decimal(price['output_per_million']), price) if valid else 0)
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE ai_attempts SET status=?,charged_units=?,evidence_json=?,result_json=?,finished_at=? WHERE id=? AND status IN ('sent','unknown')",
                   ('settled' if valid else 'unknown',charged,json.dumps(evidence),json.dumps(result if valid else {}),now(),attempt['id']))
    if not valid:
        raise ValueError('供应商用量缺失、矛盾或模型不匹配：费用未知并保留全部预留，暂停此输入。')


def summary(db):
    rows = [dict(r) for r in db.execute('SELECT * FROM ai_attempts ORDER BY rowid DESC')]
    paused = db.execute("SELECT value FROM settings WHERE key='ai_paused'").fetchone()
    policy_row = db.execute("SELECT value FROM settings WHERE key='ai_policy'").fetchone()
    policy = json.loads(policy_row[0]) if policy_row else {}
    return dict(cap_units=int(Decimal(policy.get('cap','0'))*SCALE),currency=policy.get('currency',''),month=now()[:7],timezone='UTC',unit='microcurrency',paused=bool(paused and paused[0]=='1'),
        held_units=sum(r['reserved_units'] for r in rows if r['status'] in {'sent','unknown'}),
        charged_units=sum(r['charged_units'] for r in rows if r['month']==now()[:7]),
        attempts=[{k:r[k] for k in ['id','scope','task','month','currency','status','reserved_units','charged_units','created_at']} for r in rows[:100]])


def register(app, ctx):
    @app.get('/api/admin/ai')
    def state():
        ctx.admin()
        return jsonify(summary(ctx.db()))

    @app.post('/api/admin/ai/config')
    def configure():
        ctx.admin()
        data = ctx.body()
        try:
            cap = Decimal(str(data.get('cap', '')))
            currency = data.get('currency', '')
            if not cap.is_finite() or cap <= 0 or cap > Decimal('1000000000') or cap*SCALE != (cap*SCALE).to_integral_value() or not re.fullmatch('[A-Z]{3}',currency):
                raise ValueError()
        except (ValueError,TypeError,InvalidOperation):
            abort(400, '请输入正月额度（最多六位小数）及三字母币种。')
        db = ctx.db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM ai_attempts WHERE month=? AND currency<>?', (now()[:7],currency)).fetchone():
                abort(409, '本月已有账本，不能更换币种。')
            db.execute("INSERT OR REPLACE INTO settings VALUES('ai_policy',?)", (json.dumps({'cap':str(cap),'currency':currency}),))
        return jsonify(summary(db))

    @app.post('/api/admin/ai/pause')
    def pause():
        ctx.admin()
        value = ctx.body().get('paused')
        if type(value) is not bool:
            abort(400)
        with ctx.db():
            ctx.db().execute("INSERT OR REPLACE INTO settings VALUES('ai_paused',?)", ('1' if value else '0',))
        return jsonify(summary(ctx.db()))


def validate_backup(db):
    for row in db.execute('SELECT * FROM ai_attempts'):
        try:
            price, config = json.loads(row['price_json']), json.loads(row['config_json'])
            if (row['status'] not in {'sent','unknown','settled'} or not re.fullmatch(r'\d{4}-\d{2}', row['month'])
                or not re.fullmatch('[A-Z]{3}',row['currency']) or row['currency'] != price['currency']
                or price != config['pricing'] or price['model'] != config['model'] or not price['version']
                or row['reserved_units']<=0 or not 0<=row['charged_units']<=row['reserved_units']
                or row['input_bound']<=0 or row['output_bound']<=0 or not re.fullmatch('[0-9a-f]{64}',row['input_hash'])):
                raise ValueError()
            json.loads(row['evidence_json']); json.loads(row['result_json'])
        except (ValueError,KeyError,TypeError):
            raise ValueError('AI费用账本无效。') from None
