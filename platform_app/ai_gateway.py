"""Shared fail-closed AI reservation ledger. Amounts are integer microcurrency units."""
import hashlib
import json
import os
import re
import uuid
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from flask import abort, jsonify
from .store import connect, now

SCHEMA_VERSION = 19
SCALE = 1000000
MAX_BYTES = 256 * 1024
MAX_ATTEMPTS = 3
MAX_CONCURRENT = 2
BACKOFF_SECONDS = 30


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
            db.execute('CREATE TABLE ai_events (id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL,actor_id TEXT NOT NULL,action TEXT NOT NULL,basis TEXT NOT NULL,details_json TEXT NOT NULL,created_at TEXT NOT NULL)')
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


def cost(tokens, price=None):
    return int(tokens.to_integral_value(rounding=ROUND_CEILING))


def reserve(db, scope, task, payload, config):
    cap, currency, price = local_policy(db, config)
    serialized = json.dumps(payload, ensure_ascii=True).encode()
    input_hash = hashlib.sha256(json.dumps({'messages':payload['messages'],'response_format':payload.get('response_format')},ensure_ascii=True,sort_keys=True).encode()).hexdigest()
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
        pause = db.execute("SELECT value FROM settings WHERE key='ai_paused'").fetchone()
        legacy = db.execute("SELECT value FROM settings WHERE key='ai_legacy_unknown'").fetchone()
        if (pause and pause[0]=='1') or (legacy and int(legacy[0])>0):
            raise ValueError('AI暂停：管理员暂停或旧调用费用待核对。')
        if db.execute("SELECT 1 FROM ai_attempts WHERE status='unknown'").fetchone():
            raise ValueError('AI暂停：存在费用未知调用，请管理员核对。')
        rows = db.execute('SELECT * FROM ai_attempts WHERE scope=? AND task=? AND input_hash=? ORDER BY rowid', (scope,task,input_hash)).fetchall()
        if any(r['status'] in {'sent','unknown'} for r in rows):
            raise ValueError('该输入已有费用未知调用；保留占用，禁止重复发送。')
        success = next((r for r in rows if r['status']=='settled' and json.loads(r['result_json'])), None)
        if success:
            return dict(success), True
        if len(rows) >= MAX_ATTEMPTS or (rows and datetime.fromisoformat(now()) < datetime.fromisoformat(rows[-1]['finished_at']) + timedelta(seconds=BACKOFF_SECONDS * 2**(len(rows)-1))):
            raise ValueError('该输入重试达到上限或正在退避，请稍后处理。')
        if db.execute("SELECT COUNT(*) FROM ai_attempts WHERE status IN ('sent','unknown')").fetchone()[0] >= MAX_CONCURRENT:
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
    valid = (not evidence.get('usage_invalid') and not evidence.get('permission_changed') and all(type(usage.get(k)) is int and usage[k]>=0 for k in ['prompt_tokens','completion_tokens','total_tokens'])
             and usage.get('total_tokens') == usage.get('prompt_tokens',0)+usage.get('completion_tokens',0)
             and usage.get('prompt_tokens',0) <= attempt['input_bound']
             and usage.get('completion_tokens',0) <= attempt['output_bound']
             and evidence.get('response_model') == json.loads(attempt['config_json'])['model'])
    for key in ['prompt_cache_hit_tokens','prompt_cache_miss_tokens']:
        if key in usage and (type(usage[key]) is not int or not 0<=usage[key]<=usage.get('prompt_tokens',0)):
            valid = False
    if all(k in usage for k in ['prompt_cache_hit_tokens','prompt_cache_miss_tokens']):
        valid = valid and usage['prompt_cache_hit_tokens']+usage['prompt_cache_miss_tokens']==usage.get('prompt_tokens')
    details = usage.get('prompt_tokens_details', {})
    if 'cached_tokens' in details:
        valid = valid and type(details['cached_tokens']) is int and 0<=details['cached_tokens']<=usage.get('prompt_tokens',0)
        if 'prompt_cache_hit_tokens' in usage:
            valid = valid and details['cached_tokens']==usage['prompt_cache_hit_tokens']
    price = json.loads(attempt['price_json'])
    hit = usage.get('prompt_cache_hit_tokens', details.get('cached_tokens', 0))
    if 'prompt_cache_miss_tokens' in usage and 'prompt_cache_hit_tokens' not in usage:
        hit = usage.get('prompt_tokens',0)-usage['prompt_cache_miss_tokens']
    charged = (cost(Decimal(hit)*Decimal(price['input_cache_hit_per_million']) + Decimal(usage['prompt_tokens']-hit)*Decimal(price['input_cache_miss_per_million']) + Decimal(usage['completion_tokens'])*Decimal(price['output_per_million']), price) if valid else 0)
    valid = valid and charged <= attempt['reserved_units']
    with db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT status FROM ai_attempts WHERE id=?',(attempt['id'],)).fetchone()
        if not current or current[0] not in {'sent','unknown'}:
            return
        db.execute("UPDATE ai_attempts SET status=?,charged_units=?,evidence_json=?,result_json=?,finished_at=? WHERE id=? AND status IN ('sent','unknown')",
                   ('settled' if valid else 'unknown',charged,json.dumps(evidence),json.dumps(result if valid else {}),now(),attempt['id']))
    if not valid:
        raise ValueError('供应商用量缺失、矛盾或模型不匹配：费用未知并保留全部预留，暂停此输入。')



class AIFailure(ValueError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def runtime_configuration():
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    endpoint = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
    model = os.environ.get('DEEPSEEK_MODEL', 'deepseek-flash')
    parsed = urlsplit(endpoint)
    if (not key or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or key in model or key in endpoint
            or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', model)):
        raise ValueError('服务未配置或配置无效；请联系运行管理员。')
    config = {'model':model, 'thinking':{'type':'disabled'}, 'max_tokens':6000,
              'version':os.environ.get('DEEPSEEK_CONFIG_VERSION', 'translation-nonthinking-v1'),
              'model_version':os.environ.get('DEEPSEEK_MODEL_VERSION', ''), 'pricing':{}}
    try:
        pricing = json.loads(os.environ.get('DEEPSEEK_PRICING_JSON', '{}'))
        if pricing:
            fields = {'version','model','currency','input_cache_hit_per_million','input_cache_miss_per_million','output_per_million'}
            if (not isinstance(pricing, dict) or set(pricing) != fields or pricing['model'] != model
                    or not all(isinstance(pricing[k], str) and 1 <= len(pricing[k]) <= 100 for k in fields)):
                raise ValueError()
            for field in fields - {'version','model','currency'}:
                amount = Decimal(pricing[field])
                if not amount.is_finite() or amount < 0:
                    raise ValueError()
            if not re.fullmatch('[A-Z]{3}', pricing['currency']):
                raise ValueError()
        elif pricing != {}:
            raise ValueError()
        config['pricing'] = pricing
        if (any(not isinstance(config[k], str) or len(config[k]) > 100 for k in ['version','model_version'])
                or not config['version'] or key in json.dumps(config)):
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError('翻译模型或价格版本配置无效；请联系运行管理员。') from None
    return key, endpoint, model, config


def request_json(db, *, scope, task, messages, validate, authorized, max_tokens=6000):
    """Stable shared AI boundary for explicit and automatic processors.

    scope is a stable record/material identity, task includes the processing-rule version.
    messages include every instruction and actual input/version evidence. Callers must check
    material eligibility and current permission in authorized(), before send and after response.
    validate(value) returns the strict domain result or raises ValueError. All I/O is here;
    processors must never call the provider themselves. This function owns short reservation
    and settlement transactions; do not call it inside a caller-owned write transaction.
    A sent/unknown attempt is never retried by time/lease expiry. AIFailure.evidence links
    processor state to attempt_id; successful results can be reused after a processor crash.
    """
    if db.in_transaction:
        raise ValueError('AI网关不能在写事务内执行。')
    if not scope or not task or type(max_tokens) is not int or not 1<=max_tokens<=6000:
        raise ValueError('AI任务身份或输出上界无效。')
    key,endpoint,model,config=runtime_configuration()
    config={**config,'max_tokens':max_tokens}
    if not isinstance(messages,list) or not messages or any(not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in {'system','user','assistant'} or not isinstance(m['content'],str) for m in messages):
        raise ValueError('AI输入格式无效。')
    payload={'model':model,'thinking':config['thinking'],'temperature':0,'max_tokens':max_tokens,
             'response_format':{'type':'json_object'},'messages':messages}
    # Construct before reservation: construction failures are known not sent.
    request=urllib.request.Request(endpoint+'/chat/completions',data=json.dumps(payload,ensure_ascii=True).encode(),
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    if not authorized():
        raise ValueError('资料或当前权限已变化；未发送。')
    attempt,cached=reserve(db,scope,task,payload,config)
    evidence={'attempt_id':attempt['id'],'requested_model':model,'response_model':'','finish_reason':'','response_id':'',
              'system_fingerprint':'','usage':{},'configuration':json.loads(attempt['config_json']),'usage_state':'unknown'}
    if cached:
        if not authorized():
            raise AIFailure('资料或当前权限已变化；未复用结果。',evidence)
        return json.loads(attempt['result_json']),json.loads(attempt['evidence_json'])
    if not authorized():
        # This process has not entered the transport. Retain the attempt and explicit evidence.
        with db:
            db.execute("UPDATE ai_attempts SET status='released',finished_at=?,evidence_json=? WHERE id=? AND status='sent'",
                (now(),json.dumps({'usage_state':'not_sent','reason':'permission_before_transport'}),attempt['id']))
        raise AIFailure('发送前权限已变化；未发送且已释放预留。',{**evidence,'usage_state':'not_sent'})
    output,error={},''
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:
            if response.geturl()!=request.full_url:
                raise ValueError()
            raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise ValueError()
            data=json.loads(raw)
            def label(value):
                return value if isinstance(value,str) and len(value)<=200 and key not in value and re.fullmatch(r'[A-Za-z0-9_.:/-]*',value) else ''
            evidence.update(response_model=label(data.get('model')),response_id=label(data.get('id')),
                            system_fingerprint=label(data.get('system_fingerprint')))
            usage=data.get('usage')
            if isinstance(usage,dict):
                # Whitelist numeric fields, preserve an invalid flag rather than silently sanitizing contradictions.
                for field in ['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']:
                    if field in usage:
                        if type(usage[field]) is int and usage[field]>=0:
                            evidence['usage'][field]=usage[field]
                        else:
                            evidence['usage_invalid']=True
                for field,child in [('prompt_tokens_details','cached_tokens'),('completion_tokens_details','reasoning_tokens')]:
                    if field in usage:
                        if isinstance(usage[field],dict) and type(usage[field].get(child)) is int and usage[field][child]>=0:
                            evidence['usage'][field]={child:usage[field][child]}
                        else:
                            evidence['usage_invalid']=True
            if {'prompt_tokens','completion_tokens','total_tokens'}.issubset(evidence['usage']):
                evidence['usage_state']='reported'
            choice=data['choices'][0]
            evidence['finish_reason']=label(choice.get('finish_reason'))
            if choice.get('finish_reason')!='stop':
                raise ValueError()
            content=choice['message']['content']
            if not isinstance(content,str) or key in content:
                raise ValueError()
            output=validate(json.loads(content))
            if not isinstance(output,dict) or not output or key in json.dumps(output,ensure_ascii=False):
                raise ValueError()
    except Exception:
        error='AI响应失败、超时、未完整结束或结构无效；费用另按已有用量核对。'
    if not authorized():
        evidence['permission_changed']=True
        output={}
        error='生成期间权限已变化；费用待核对，结果未保存。'
    try:
        settle(db,attempt,evidence,output if not error else {})
    except ValueError as failure:
        raise AIFailure(str(failure),evidence) from None
    if error:
        raise AIFailure(error,evidence)
    return output,evidence

def audit(db, actor, action, basis, details, attempt_id=''):
    db.execute('INSERT INTO ai_events VALUES(?,?,?,?,?,?,?)',
        (uuid.uuid4().hex,attempt_id,actor,action,basis,json.dumps(details),now()))


def amount_units(value, *, positive=False):
    try:
        amount=Decimal(str(value))
        units=amount*SCALE
        if not amount.is_finite() or amount<0 or amount>Decimal('1000000000') or units!=units.to_integral_value() or (positive and amount<=0):
            raise ValueError()
        return int(units)
    except (ValueError,TypeError,InvalidOperation):
        raise ValueError('金额须为非负数，最多六位小数；月额度必须大于零。') from None


def summary(db):
    rows = [dict(r) for r in db.execute('SELECT * FROM ai_attempts ORDER BY rowid DESC')]
    paused = db.execute("SELECT value FROM settings WHERE key='ai_paused'").fetchone()
    legacy=db.execute("SELECT value FROM settings WHERE key='ai_legacy_unknown'").fetchone()
    policy_row=db.execute("SELECT value FROM settings WHERE key='ai_policy'").fetchone()
    policy=json.loads(policy_row[0]) if policy_row else {}
    reasons=[]
    if paused and paused[0]=='1': reasons.append('管理员已暂停')
    if not policy: reasons.append('尚未设置有效月额度及币种')
    if legacy and int(legacy[0]): reasons.append('升级前运行中的旧调用费用待核对')
    if any(r['status']=='unknown' for r in rows): reasons.append('存在费用未知调用，保留占用并暂停新调用')
    try:
        _,_,_,config=runtime_configuration()
        local_policy(db,config)
    except ValueError:
        reasons.append('本地凭据、模型价格版本或匹配币种未配置有效')
    months=[]
    for month,currency in sorted({(r['month'],r['currency']) for r in rows},reverse=True):
        group=[r for r in rows if (r['month'],r['currency'])==(month,currency)]
        months.append({'month':month,'currency':currency,'held_units':sum(r['reserved_units'] for r in group if r['status'] in {'sent','unknown'}),
                       'charged_units':sum(r['charged_units'] for r in group)})
    cap=int(Decimal(policy.get('cap','0'))*SCALE)
    current=[r for r in rows if r['month']==now()[:7]]
    held=sum(r['reserved_units'] for r in current if r['status'] in {'sent','unknown'})
    charged=sum(r['charged_units'] for r in current)
    if cap and held+charged>=cap: reasons.append('本月额度已用完或全部预留')
    return dict(cap_units=cap,currency=policy.get('currency',''),month=now()[:7],timezone='UTC',unit='microcurrency',
        paused=bool(paused and paused[0]=='1'),blocked_reasons=reasons,legacy_unknown=int(legacy[0]) if legacy else 0,
        held_units=held,charged_units=charged,months=months,
        attempts=[{k:r[k] for k in ['id','scope','task','month','currency','status','reserved_units','charged_units','created_at','finished_at']} for r in rows[:100]],
        events=[dict(r) for r in db.execute('SELECT * FROM ai_events ORDER BY rowid DESC LIMIT 100')])


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
            audit(db,ctx.user()['id'],'configure','管理员设置月额度',{'cap':str(cap),'currency':currency})
        return jsonify(summary(db))

    @app.post('/api/admin/ai/pause')
    def pause():
        ctx.admin()
        value = ctx.body().get('paused')
        if type(value) is not bool:
            abort(400)
        with ctx.db():
            ctx.db().execute("INSERT OR REPLACE INTO settings VALUES('ai_paused',?)", ('1' if value else '0',))
            audit(ctx.db(),ctx.user()['id'],'pause','管理员调整暂停状态',{'paused':value})
        return jsonify(summary(ctx.db()))

    @app.post('/api/admin/ai/attempts/<aid>/resolve')
    def resolve(aid):
        ctx.admin()
        data=ctx.body()
        basis=data.get('basis','')
        if not isinstance(basis,str) or not 10<=len(basis.strip())<=2000:
            abort(400,'请填写可复核的供应商账单或明确未发送依据（10—2000字）。')
        try:
            charged=amount_units(data.get('charged',''))
        except ValueError as failure:
            abort(400,str(failure))
        db=ctx.db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            attempt=db.execute('SELECT * FROM ai_attempts WHERE id=?',(aid,)).fetchone()
            if not attempt: abort(404)
            if attempt['status'] not in {'sent','unknown'}:
                abort(409,'该调用已经结算，原记录及历史不能改写。')
            audit(db,ctx.user()['id'],'resolve',basis.strip(),{'charged_units':charged,'previous_status':attempt['status']},aid)
            db.execute("UPDATE ai_attempts SET status='settled',charged_units=?,finished_at=?,result_json='{}' WHERE id=?",(charged,now(),aid))
        return jsonify(summary(db))

    @app.post('/api/admin/ai/legacy/resolve')
    def resolve_legacy():
        ctx.admin()
        data=ctx.body();basis=data.get('basis','')
        if not isinstance(basis,str) or not 10<=len(basis.strip())<=2000:
            abort(400,'请填写旧调用供应商账单已核对、当前账期外部费用已处理的依据。')
        db=ctx.db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute("SELECT value FROM settings WHERE key='ai_legacy_unknown'").fetchone()
            if not old or int(old[0])==0: abort(409)
            audit(db,ctx.user()['id'],'legacy_resolve',basis.strip(),{'legacy_count':int(old[0])})
            db.execute("UPDATE settings SET value='0' WHERE key='ai_legacy_unknown'")
        return jsonify(summary(db))


def validate_backup(db):
    for row in db.execute('SELECT * FROM ai_attempts'):
        try:
            price, config = json.loads(row['price_json']), json.loads(row['config_json'])
            if (row['status'] not in {'sent','unknown','settled','released'} or not re.fullmatch(r'\d{4}-\d{2}', row['month'])
                or not re.fullmatch('[A-Z]{3}',row['currency']) or row['currency'] != price['currency']
                or price != config['pricing'] or price['model'] != config['model'] or not price['version']
                or row['reserved_units']<=0 or not 0<=row['charged_units']<=row['reserved_units']
                or row['input_bound']<=0 or row['output_bound']<=0 or not re.fullmatch('[0-9a-f]{64}',row['input_hash'])):
                raise ValueError()
            json.loads(row['evidence_json']); json.loads(row['result_json'])
        except (ValueError,KeyError,TypeError):
            raise ValueError('AI费用账本无效。') from None
