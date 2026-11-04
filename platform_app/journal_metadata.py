"""Three fixed Crossref journals: one bounded response per durable run."""
import base64
import hashlib
import json
import time
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode

from . import intake, store, workflow

JOURNALS = (
    ('eep', 'East European Politics', '东欧政治', '2159-9165', '2159-9173', 'www.tandfonline.com', '/journals/fjcs21'),
    ('jbnes', 'Journal of Balkan and Near Eastern Studies', '巴尔干与近东研究', '1944-8953', '1944-8961', 'www.tandfonline.com', '/journals/cjsb20'),
    ('eup', 'European Union Politics', '欧盟政治', '1465-1165', '1741-2757', 'journals.sagepub.com', '/home/eup'),
)
ADAPTERS = tuple(dict(id=key+'-crossref-v1', name=name, chinese_name=zh, kinds={'journal'},
    hosts={host, host.removeprefix('www.')}, roots={path, path+'/'}, issns=(paper, online),
    website='https://'+host+path, feed='https://api.crossref.org/journals/'+paper+'/works',
    column='https://'+host+path, article=r'(?!)', format='Crossref journal JSON', mode='crossref',
    scope='Crossref公开题录及实际提供的摘要；仅所列窗口与分页，不代表全文、完整目次或全历史')
    for key, name, zh, paper, online, host, path in JOURNALS)
ROWS = 25


def request_plan(config, sample=0):
    today = datetime.fromisoformat(store.now()).date()
    previous = json.loads(config['cursor']) if config['cursor'] else {}
    if sample:
        params = dict(filter='type:journal-article,until-online-pub-date:'+today.isoformat(),
                      sort='published-online', order='desc', rows=sample)
        return params, dict(start='', end=today.isoformat(), basis='published-online'), {}
    if previous.get('pending'):
        start, end, position = previous['start'], previous['end'], previous['next_cursor']
        processed = previous.get('processed', 0)
    else:
        # Date-granular inclusive overlap admits later-indexed old articles and
        # corrections. Publication date does not exclude an indexed work.
        start = previous.get('end') or (today-timedelta(days=config['backfill_days']-1)).isoformat()
        end, position, processed = today.isoformat(), '*', 0
    params = dict(filter=f'type:journal-article,from-index-date:{start},until-index-date:{end}',
                  sort='indexed', order='asc', rows=ROWS, cursor=position)
    return params, dict(start=start, end=end, basis='indexed'), dict(processed=processed)


def recover_rejected_cursor(config, failure):
    """Only an actual rejected follow-up request permits replay, never a TTL.

    The 2026 Crossref cursor contract has no expiration and no stable snapshot.
    Preserve every query parameter and the original bounded indexed window.
    """
    previous=json.loads(config['cursor']) if config['cursor'] else {}
    if (isinstance(failure,intake.AcquisitionError) and failure.http_status==400
            and previous.get('kind')=='crossref_indexed' and previous.get('pending') and previous.get('next_cursor')!='*'):
        return dict(previous,next_cursor='*',processed=0,recovery_reason='后续分页返回HTTP400；保留原索引窗口重新读取')
    return None


def metadata(item, adapter):
    doi = intake.normalize_doi(item.get('DOI'))
    if (not doi or item.get('type') != 'journal-article' or
            not set(item.get('ISSN', [])) & set(adapter['issns'])):
        raise intake.AcquisitionError('题录缺少DOI、文章类别或本刊ISSN依据。')
    document = dict(text=json.dumps({'message': item}, ensure_ascii=False))
    fields, authors, identifiers, hints, provenance, raw, warnings = intake.registry_metadata(document, doi, 'Crossref')
    fields.update(kind='journal_article')
    # Keep the original publication precision; online/print/issued remain in raw.
    for key in ('published-on', 'published-online', 'published-print', 'published', 'issued'):
        if key in item:
            raw.setdefault('date_fields', {})[key] = item[key]
    return dict(fields=fields, authors=authors, identifiers=identifiers, hints=hints,
                provenance=provenance, raw=raw, warnings=warnings)


def snapshot(document, adapter, doi, retrieved_at):
    try:
        payload = json.loads(document['bytes'])
        items = payload['message']['items']
        matches = [item for item in items if intake.normalize_doi(item.get('DOI')) == doi]
        if not matches or any(item!=matches[0] for item in matches[1:]):
            raise ValueError()
        meta = metadata(matches[0], adapter)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise intake.AcquisitionError('Crossref原响应与单篇DOI无法绑定。') from None
    content = document['bytes']
    sha = hashlib.sha256(content).hexdigest()
    html, text = workflow.clean_rich('<p>'+escape(meta['fields'].get('abstract', ''))+'</p>' if meta['fields'].get('abstract') else '')
    return dict(id=sha, url=document['url'], retrieved_at=retrieved_at, sha256=sha, bytes=len(content),
                raw_base64=base64.b64encode(content).decode(), content_type='application/json', encoding='utf-8',
                adapter=adapter['id'], page_html=html, page_text=text, metadata=meta, pdf_links=[],
                sidebar_credit=meta['fields'].get('authors',''), sidebar_credit_raw=meta['fields'].get('authors',''),
                content_kind='bibliographic_metadata', work_body_available=False, work_body=None, work_body_basis='',
                doi=doi, reason='Crossref公开JSON题录；摘要仅在实际返回时保存，未取得论文全文。')


def fetch_page(adapter, config, source_id, sample=0):
    params, window, progress = request_plan(config, sample)
    url = adapter['feed']+'?'+urlencode(params)
    document = intake.fetch_document(url, time.monotonic()+intake.MAX_SECONDS)
    if document['url'] != url or document['content_type'] not in {'application/json', 'application/vnd.crossref-api-message+json'}:
        raise intake.AcquisitionError('Crossref响应离开固定JSON入口。')
    stamp = store.now()
    try:
        payload = json.loads(document['bytes'])
        message = payload['message']
        items = message['items']
        if payload.get('status') != 'ok' or not isinstance(items, list) or len(items) > params['rows']:
            raise ValueError()
        total = message.get('total-results')
        if type(total) is not int or total < len(items):
            raise ValueError()
        result, dois, excluded = [], set(), []
        for index, item in enumerate(items):
            meta = metadata(item, adapter)
            fields = dict(meta['fields'], serial_id=source_id)
            doi = fields['doi']
            if doi in dois:
                excluded.append(dict(index=index, reason='duplicate_doi'))
                continue
            dois.add(doi)
            entry_id = hashlib.sha256((adapter['id']+':'+doi).encode()).hexdigest()
            # The actual byte response is stored once on the run, then bound to
            # each record snapshot during the existing entry-save transaction.
            evidence = dict(format=adapter['format'], version=1, adapter=adapter['id'], source_id=source_id,
                            feed_url=adapter['feed'], column_url=adapter['column'], retrieved_at=stamp,
                            window=window, raw=item, fields=fields, authors=meta['authors'],
                            description=fields.get('abstract',''), entry_id=entry_id, provenance=meta['provenance'])
            result.append(dict(fields=fields, evidence=evidence))
        processed = progress.get('processed', 0)+len(items)
        pending = not sample and len(items) == params['rows'] and processed < total
        position = message.get('next-cursor', '')
        if pending and (not isinstance(position, str) or not position or len(position)>20000 or position == params.get('cursor')):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise intake.AcquisitionError('Crossref题录结构或分页位置无效；未推进水位。') from None
    cursor = {} if sample else dict(kind='crossref_indexed', **window, pending=bool(pending),
        processed=processed if pending else 0, next_cursor=position if pending else '*')
    return document, dict(items=result, returned=len(items), total_results=total, window=window,
        request_url=url, retrieved_at=stamp, sha256=hashlib.sha256(document['bytes']).hexdigest(),
        earliest=min((x['fields'].get('published_on','') for x in result), default=''),
        exclusions=excluded, warnings=[adapter['scope']], scope=adapter['scope'],
        coverage_complete=False, window_complete=not pending and not sample,
        sample_only=bool(sample), cursor=cursor, backfill_days=config['backfill_days'])
