"""One fixed official RSS adapter; previews never write records or follow item URLs."""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from flask import abort, current_app, jsonify
from itsdangerous import BadSignature, URLSafeSerializer

from . import identity, intake, store

FEED = 'https://liia.lv/en/opinions/rss.xml'
COLUMN = 'https://liia.lv/en/opinions'
FEEDS = {FEED, 'https://www.liia.lv/en/opinions/rss.xml'}
HOSTS = {'liia.lv', 'www.liia.lv'}
MAX_ITEMS = 100


def supported(source):
    url = intake.normalize_url(source['website'])
    p = urlsplit(url)
    return (source['kind'] in {'institution', 'think_tank'} and p.hostname in HOSTS
            and p.scheme == 'https' and p.port in {None, 443} and p.path in {'/', '/en', '/en/'} and not p.query)


def source_for(db, sid):
    source = identity.resolve(db, 'sources', sid) if isinstance(sid, str) else None
    if source is None or not supported(source):
        abort(422, '此来源尚未配置可用的固定官方发现入口。')
    return source


def _signer():
    return URLSafeSerializer(current_app.secret_key, salt='liia-discovery-v1')


def read_token(token, actor, db):
    if not isinstance(token, str) or len(token) > 3 * intake.MAX_BYTES:
        abort(400, '发现依据格式不正确，请重新取得。')
    try:
        payload = _signer().loads(token)
    except (BadSignature, ValueError):
        abort(400, '发现依据无效，请重新取得；当前输入仍可保留。')
    if not isinstance(payload, dict) or payload.get('actor_id') != actor['id']:
        abort(403, '发现依据不属于当前账号。')
    source_for(db, payload['evidence']['source_id'])
    return payload['evidence']


def saved_record(db, entry_id):
    for row in db.execute('SELECT id,raw_json FROM records'):
        if any(e.get('entry_id') == entry_id for e in json.loads(row['raw_json'] or '{}').get('discovery_evidence', [])):
            return identity.resolve(db, 'records', row['id'])
    return None


def article_key(value):
    url = intake.normalize_url(value)
    p = urlsplit(url)
    if p.hostname in HOSTS and p.scheme == 'https':
        return url.replace('https://www.liia.lv/', 'https://liia.lv/').rstrip('/')
    return url


def _duplicates(db, access, fields):
    visible, hidden = [], False
    doi, url = intake.normalize_doi(fields.get('doi')), article_key(fields.get('url'))
    for row in db.execute('SELECT * FROM records WHERE merged_into IS NULL'):
        basis = 'DOI' if doi and intake.normalize_doi(row['doi']) == doi else '文章网址' if url and article_key(row['url']) == url else ''
        if basis:
            if access.visible(row):
                visible.append(dict(id=row['id'], title=row['title'], basis=basis))
            else:
                hidden = True
    return dict(duplicates=visible, blocked=hidden)


def _parse(content, retrieved_at, source_id, actor):
    # Parse bytes to respect the XML encoding declaration. ASCII-compatible and
    # UTF-16/32 encodings are screened before parsing, so declarations cannot hide
    # behind zero bytes. No DTD or declared entity ever reaches ElementTree.
    screened = content.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in screened or b'<!ENTITY' in screened:
        raise intake.AcquisitionError('RSS 含 DTD 或实体声明，已拒绝解析。')
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError, LookupError):
        raise intake.AcquisitionError('RSS XML 格式无效，已有草稿仍保留。') from None
    channel = root.find('channel') if root.tag == 'rss' else None
    if channel is None:
        raise intake.AcquisitionError('未取得有效的 RSS channel。')
    nodes = channel.findall('item')
    if len(nodes) > MAX_ITEMS or sum(1 for _ in root.iter()) > 5000:
        raise intake.AcquisitionError('RSS 条目或结构超出解析限制。')
    end = datetime.fromisoformat(retrieved_at).astimezone(timezone.utc).date()
    start = end - timedelta(days=29)
    window = dict(start=start.isoformat(), end=end.isoformat())
    counts = dict(missing_date=0, invalid_date=0, outside_window=0, future=0, invalid_item=0, duplicate_url=0, duplicate_guid=0)
    items, dates, exclusions, urls, guids = [], [], [], set(), set()
    for index, node in enumerate(nodes, 1):
        raw = {key: node.findtext(key, '') for key in ['title', 'link', 'pubDate', 'guid', 'description']}
        reason = ''
        try:
            parsed = parsedate_to_datetime(raw['pubDate'])
            if parsed.tzinfo is None:
                raise ValueError()
            published = parsed.date()
            dates.append(published)
        except (TypeError, ValueError, OverflowError):
            published = None
            reason = 'missing_date' if not raw['pubDate'].strip() else 'invalid_date'
        if published:
            if published > end:
                reason = 'future'
            elif published < start:
                reason = 'outside_window'
        url = intake.normalize_url(raw['link'])
        p = urlsplit(url)
        title = intake.plain(raw['title'])
        if not reason and (not title or len(raw['title']) > 4000 or len(raw['description']) > 40000 or
                           len(raw['link']) > 4000 or len(raw['guid']) > 4000 or
                           p.scheme != 'https' or p.hostname not in HOSTS or p.port not in {None, 443} or
                           p.query or not re.fullmatch(r'/en/opinions/[A-Za-z0-9_-]+/?', p.path) or
                           p.path.endswith('/rss.xml')):
            reason = 'invalid_item'
        if reason:
            counts[reason] += 1
            exclusions.append(dict(index=index, reason=reason))
            continue
        # www and bare official aliases denote the same article identity.
        url = url.replace('https://www.liia.lv/', 'https://liia.lv/').rstrip('/')
        if url in urls:
            counts['duplicate_url'] += 1
            exclusions.append(dict(index=index, reason='duplicate_url'))
            continue
        urls.add(url)
        if raw['guid'] and raw['guid'] in guids:
            counts['duplicate_guid'] += 1
        guids.add(raw['guid'])
        fields = dict(kind='other', title=title, url=url, published_on=published.isoformat(), source_id=source_id)
        description = intake.plain(raw['description'], 40000)
        entry_id = hashlib.sha256((FEED+':'+url).encode()).hexdigest()
        evidence = dict(format='LIIA RSS', version=1, adapter='liia-opinions-v1', source_id=source_id,
                        feed_url=FEED, column_url=COLUMN, retrieved_at=retrieved_at, window=window,
                        raw=raw, description=description, fields=fields, authors=[], entry_id=entry_id,
                        provenance=dict(title='item.title', url='item.link', published_on='item.pubDate', description='item.description'))
        items.append(dict(index=index, type='待人工确认类别', fields=fields, description=description,
                          authors=[], warnings=['署名、语言与摘要未取得；来源公开描述可能只是系列介绍。'],
                          errors=[], file_duplicates=[], candidates=dict(authors=[], sources=[]), evidence=evidence,
                          token=_signer().dumps(dict(actor_id=actor['id'], evidence=evidence))))
    earliest = min(dates).isoformat() if dates else None
    warnings = ['仅列当前 RSS 返回的内容；该订阅通常只返回最近 20 条，不代表栏目全部覆盖。']
    if not dates or min(dates) >= start or len(nodes) >= 20 or any(counts.values()) or dates != sorted(dates, reverse=True):
        warnings.append('当前结果可能遗漏窗口内内容：订阅截断、日期或条目异常、乱序及最早日期均需人工核对。')
    return dict(format='discovery', source_id=source_id, filename='LIIA Opinions 近期发现', sha256=hashlib.sha256(content).hexdigest(),
                feed_url=FEED, column_url=COLUMN, retrieved_at=retrieved_at, window=window, returned=len(nodes),
                earliest=earliest, counts=counts, exclusions=exclusions, warnings=warnings, items=items)


def register(app, ctx):
    @app.post('/api/sources/<sid>/discovery')
    def discovery_preview(sid):
        data = ctx.body()
        if data:
            abort(400, '固定来源发现不接受网址或适配器参数。')
        source = source_for(ctx.db(), sid)
        if not intake._slots.acquire(blocking=False):
            abort(429, '当前取得请求较多，请稍后重试。')
        try:
            document = intake.fetch_document(FEED, time.monotonic()+intake.MAX_SECONDS, fixed_feed=FEEDS)
            result = _parse(document['bytes'], store.now(), source['id'], ctx.user())
            for item in result['items']:
                item.update(_duplicates(ctx.db(), ctx.records(), item['fields']))
                saved = saved_record(ctx.db(), item['evidence']['entry_id'])
                if saved is not None:
                    if ctx.records().visible(saved):
                        item['saved'] = saved['id']
                    else:
                        item['blocked'] = True
            return jsonify(result)
        except intake.AcquisitionError as error:
            abort(422, str(error))
        finally:
            intake._slots.release()

    @app.post('/api/discovery/status')
    def discovery_status():
        data = ctx.body()
        evidence = read_token(data.get('token'), ctx.user(), ctx.db())
        fields = data.get('fields', evidence['fields'])
        if not isinstance(fields, dict) or any(not isinstance(fields.get(k, ''), str) or len(fields.get(k, '')) > 4000 for k in ['title', 'doi', 'url']):
            abort(400, '重复核对字段格式不正确。')
        row = saved_record(ctx.db(), evidence['entry_id'])
        if row is not None and ctx.records().visible(row):
            return jsonify(saved=True, id=row['id'], title=row['title'])
        result = _duplicates(ctx.db(), ctx.records(), fields)
        result['blocked'] = result['blocked'] or row is not None
        return jsonify(saved=False, **result)
