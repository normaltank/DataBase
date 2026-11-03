"""Fixed official listing adapters; previews never write records or follow item URLs."""
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from flask import abort, current_app, jsonify
from itsdangerous import BadSignature, URLSafeSerializer

from . import identity, intake, store, source_adapters

FEED = 'https://liia.lv/en/opinions/rss.xml'
COLUMN = 'https://liia.lv/en/opinions'
FEEDS = {FEED, 'https://www.liia.lv/en/opinions/rss.xml'}
HOSTS = {'liia.lv', 'www.liia.lv'}
MAX_ITEMS = 100


def supported(source):
    return source_adapters.for_source(source) is not None


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
    return identity.record_for_entry(db, entry_id, 'discovery_evidence')


def article_key(value):
    return source_adapters.canonical(value)


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


def _parse(content, retrieved_at, source_id, actor=None, *, previously_seen=None, admitted_urls=(), adapter=None, backfill_days=30):
    adapter = adapter or source_adapters.ADAPTERS[0]
    # Parse bytes to respect the XML encoding declaration. ASCII-compatible and
    # UTF-16/32 encodings are screened before parsing, so declarations cannot hide
    # behind zero bytes. No DTD or declared entity ever reaches ElementTree.
    screened = content.replace(b'\x00', b'').upper()
    if adapter['mode'] == 'rss' and (b'<!DOCTYPE' in screened or b'<!ENTITY' in screened):
        raise intake.AcquisitionError('RSS 含 DTD 或实体声明，已拒绝解析。')
    try:
        root = ET.fromstring(content) if adapter['mode'] == 'rss' else None
    except (ET.ParseError, ValueError, LookupError):
        raise intake.AcquisitionError('RSS XML 格式无效，已有草稿仍保留。') from None
    channel = root.find('channel') if root is not None and root.tag == 'rss' else None
    if channel is None and adapter['mode'] == 'rss':
        raise intake.AcquisitionError('未取得有效的 RSS channel。')
    nodes = channel.findall('item') if channel is not None else source_adapters.listing_nodes(content)
    if len(nodes) > MAX_ITEMS or root is not None and sum(1 for _ in root.iter()) > 5000:
        raise intake.AcquisitionError('RSS 条目或结构超出解析限制。')
    end = datetime.fromisoformat(retrieved_at).astimezone(timezone.utc).date()
    start = end - timedelta(days=backfill_days - 1)
    window = dict(start=start.isoformat(), end=end.isoformat())
    counts = dict(missing_date=0, invalid_date=0, outside_window=0, future=0, invalid_item=0, duplicate_url=0, duplicate_guid=0)
    items, dates, exclusions, urls, guids = [], [], [], set(), set()
    for index, node in enumerate(nodes, 1):
        raw = {key: node.findtext(key, '') for key in ['title', 'link', 'pubDate', 'guid', 'description']}
        if adapter['mode'] == 'html':
            raw.update({key: node.findtext(key, '') for key in ['displayed_date', 'authors']})
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
            elif published < start and (previously_seen is None or
                    (article_key(raw['link']) in previously_seen and article_key(raw['link']) not in admitted_urls)):
                reason = 'outside_window'
        url = intake.normalize_url(raw['link'])
        p = urlsplit(url)
        title = intake.plain(raw['title'])
        if not reason and (not title or len(raw['title']) > 4000 or len(raw['description']) > 40000 or
                           len(raw['link']) > 4000 or len(raw['guid']) > 4000 or
                           not source_adapters.article_url(adapter, url) or p.path.endswith('/rss.xml')):
            reason = 'invalid_item'
        if reason:
            counts[reason] += 1
            exclusions.append(dict(index=index, reason=reason))
            continue
        # www and bare official aliases denote the same article identity.
        url = article_key(url)
        if url in urls:
            counts['duplicate_url'] += 1
            exclusions.append(dict(index=index, reason='duplicate_url'))
            continue
        urls.add(url)
        if raw['guid'] and raw['guid'] in guids:
            counts['duplicate_guid'] += 1
        guids.add(raw['guid'])
        fields = dict(kind='other', title=title, url=url, published_on=published.isoformat(), source_id=source_id)
        if adapter['kinds'] == {'journal'}:
            fields.pop('source_id')
            fields['serial_id'] = source_id
        if raw.get('authors'):
            fields['authors'] = raw['authors']
        description = intake.plain(raw['description'], 40000)
        entry_id = hashlib.sha256((adapter['feed']+':'+url).encode()).hexdigest()
        evidence = dict(format=adapter['format'], version=1, adapter=adapter['id'], source_id=source_id,
                        feed_url=adapter['feed'], column_url=adapter['column'], retrieved_at=retrieved_at, window=window,
                        raw=raw, description=description, fields=fields, authors=[], entry_id=entry_id,
                        provenance=dict(title='item.title', url='item.link', published_on='item.pubDate', description='item.description'))
        if previously_seen is not None:
            evidence['selection'] = 'previously_admitted' if url in admitted_urls else 'newly_discovered'
            evidence['outside_reference_window'] = published < start
        item = dict(index=index, type='待人工确认类别', fields=fields, description=description,
                          authors=[], warnings=['署名、语言与摘要未取得；来源公开描述可能只是系列介绍。'],
                          errors=[], file_duplicates=[], candidates=dict(authors=[], sources=[]), evidence=evidence)
        if actor is not None:
            item['token'] = _signer().dumps(dict(actor_id=actor['id'], evidence=evidence))
        items.append(item)
    earliest = min(dates).isoformat() if dates else None
    warnings = ['仅列当前 RSS 返回的内容；该订阅通常只返回最近 20 条，不代表栏目全部覆盖。'] if adapter['id'] == 'liia-opinions-v1' else [adapter['scope']]
    if not dates or min(dates) >= start or len(nodes) >= 20 or any(counts.values()) or dates != sorted(dates, reverse=True):
        warnings.append('当前结果可能遗漏窗口内内容：订阅截断、日期或条目异常、乱序及最早日期均需人工核对。')
    result = dict(format='discovery', source_id=source_id, filename=adapter['name']+' 近期发现', sha256=hashlib.sha256(content).hexdigest(),
                source_name=adapter['name'], entry_type=adapter['mode'],
                date_basis='rss_online' if adapter['kinds'] == {'journal'} else 'published',
                feed_url=adapter['feed'], column_url=adapter['column'], retrieved_at=retrieved_at, window=window, returned=len(nodes),
                earliest=earliest, counts=counts, exclusions=exclusions, warnings=warnings, items=items)
    result['window_role'] = ('RSS 上线／发布标签的日期窗口；不替代原文发表日期、引用年份或首次入库时间' if adapter['kinds']=={'journal'} else
                             '首次发表日期窗口') if previously_seen is None else '参考日期窗口；本轮按新发现与已纳入身份取得，可包含较早文章'
    if actor is None:
        result['observed_urls'] = sorted({article_key(node.findtext('link','')) for node in nodes if article_key(node.findtext('link',''))})
    return result


def register(app, ctx):
    @app.post('/api/sources/<sid>/discovery')
    def discovery_preview(sid):
        data = ctx.body()
        if data:
            abort(400, '固定来源发现不接受网址或适配器参数。')
        source = source_for(ctx.db(), sid)
        adapter = source_adapters.for_source(source)
        if not intake._slots.acquire(blocking=False):
            abort(429, '当前取得请求较多，请稍后重试。')
        try:
            document = fetch_listing(adapter)
            result = _parse(document['bytes'], store.now(), source['id'], ctx.user(), adapter=adapter)
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


def fetch_listing(adapter):
    aliases = {adapter['feed']}
    if adapter['id'] == 'liia-opinions-v1':
        aliases = FEEDS
    document = intake.fetch_document(adapter['feed'], time.monotonic()+intake.MAX_SECONDS,
                                     **({'fixed_feed': aliases} if adapter['mode'] == 'rss' else {}))
    if document['url'] not in aliases:
        raise intake.AcquisitionError('发现响应离开固定官方入口，未纳入。')
    return document
