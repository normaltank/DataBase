"""Frozen, public-only metadata and independent historical translation excerpts.

This is a new-preview initializer, never a database exporter or a translation runner.
"""
import hashlib
import json
from pathlib import Path
from contextlib import closing

FIXTURE_SHA256 = '503873c448ccb581f4a290990d6756d1ff9f6d3596df35b46fbb487a8affc651'
BATCH = 'cee86-20261030-v1'


def load_fixture(read=None):
    raw = read('portable/samples/cee17-preview.json') if read else (Path(__file__).parent / 'samples/cee17-preview.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError('Public preview fixture differs from the reviewed whitelist.')
    return json.loads(raw)


def seed_public_batch(app):
    from portable.demo_seed import call, login
    from platform_app.store import connect, now, save_revision
    from platform_app.translations import digest
    fixture = load_fixture()
    reader, admin = login(app, 'researcher'), login(app, 'admin')
    # Only the intact fictional initializer can reach this seam. No existing library imports.
    if reader.get('/api/records?size=100').json['total'] != 6 or reader.get('/api/sources').json['total'] != 3:
        raise RuntimeError('Public batch requires the newly generated fictional preview.')
    sources = {}
    for source in sorted(fixture['sources'], key=lambda x: x['kind'] == 'journal'):
        evidence = '\n'.join(source['evidence_urls'])
        values = {'name': source['name'], 'original_name': source['original_name'], 'kind': source['kind'],
                  'country': source['institution_country'] or '', 'website': source['website'],
                  'catalogue_url': source['catalogue_url'], 'issn': source['issn'],
                  'notes': '历史17国有界公开样本；待核对；本包不执行采集。\n' + evidence + '\n' + '\n'.join(source['limitations'])}
        if source['kind'] == 'journal':
            values.update(host_id=' | '.join(sources[x] for x in source['host_ids']),
                          publisher_id=' | '.join(sources[x] for x in source['publisher_ids']),
                          host_country_status='pending' if source['journal_country_status'] == 'pending' else 'auto',
                          international_status=source['international_status'], international_evidence=evidence,
                          host_evidence=evidence)
        sources[source['id']] = call(reader, '/api/sources', values)['id']
    articles = {}
    with closing(connect(Path(app.config['DATA_DIR']) / 'platform.sqlite3')) as db:
        for article in fixture['articles']:
            abstract = article['abstract_original_preview']
            values = {'kind': 'journal_article' if article['serial_id'] else 'report',
                      'title': article['original_title'], 'original_title': article['original_title'],
                      'authors': article['authors_raw'], 'published_on': article['date'], 'language': article['language'],
                      'source_id': sources.get(article['source_id'], ''), 'serial_id': sources.get(article['serial_id'], ''),
                      'publication_title': article['publication_title'], 'volume': article['volume'],
                      'issue': article['issue'], 'pages': article['pages'], 'issn': article['issn'],
                      'doi': article['doi'], 'url': article['url'], 'abstract': abstract,
                      'countries': article['research_subject_countries'],
                      'visibility': 'shared', 'sharing_confirmed': True}
            rid = call(reader, '/api/records', values)['id']
            articles[article['id']] = rid
            # The API has no historical-result import endpoint. Write only this fresh preview's
            # derived display version; do not run/mimic a provider or copy its paid-attempt ledger.
            jid = 'PREVIEW-CEE86-' + article['translation_id']
            input_hash = digest(article['original_title'], abstract)
            provenance = {'format': 'portable-historical-machine-v1', 'batch': BATCH,
                          'source_record_id': article['id'], 'source_job_id': article['translation_id'],
                          'source_version': article['translation_source_version'],
                          'acquisition_path': article['acquisition_path'], 'acquisition_limitation': article['acquisition_limitation'],
                          'source_input_hash': article['translation_input_hash'],
                          'excerpt_input_hash': input_hash,
                          'excerpt_output_hash': digest(article['machine_title'], article['abstract_machine_preview']),
                          'alignment': 'independent_truncation', 'local_calls': 0, 'full_content_excluded': True,
                          'abstract_mode': 'excerpt' if abstract else 'missing',
                          'original_truncated': article['abstract_original_preview_truncated'],
                          'machine_truncated': article['abstract_machine_preview_truncated']}
            raw = {'portable_preview_import': {jid: provenance}}
            with db:
                db.execute('UPDATE records SET raw_json=? WHERE id=?', (json.dumps(raw, ensure_ascii=False), rid))
                db.execute('''INSERT INTO translation_jobs
                    (id,record_id,actor_id,request_id,source_version,input_title,input_abstract,input_hash,
                     source_url,source_doi,status,attempts,output_title,output_abstract,model,provider,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'succeeded',0,?,?,?,?,?)''',
                    (jid, rid, 'researcher', jid, 1, article['original_title'], abstract, input_hash,
                     article['url'], article['doi'], article['machine_title'], article['abstract_machine_preview'],
                     article['translation_model'], article['translation_provider'], now()))
                save_revision(db, 'record', rid, '导入公开题录及历史机器节选；本包无调用、未人工校订', 'researcher')
    collection = call(reader, '/api/collections', {'name': '历史17国公开资料样本',
        'visibility': 'shared', 'notes': '38核心来源、56资料；23原译独立节选、33仅译题名。未人工校订，本包不采集或调用AI。'})['id']
    for rid in articles.values():
        call(reader, '/api/collections/' + collection + '/items', {'record_id': rid})
    call(admin, '/api/admin/ai/pause', {'paused': True})
    return {'batch': BATCH, 'fixture_sha256': FIXTURE_SHA256, 'source_ids': list(sources.values()),
            'core_source_ids': [sources[s['id']] for s in fixture['sources'] if s['role'] == 'core'],
            'article_ids': list(articles.values()), 'source_map': sources, 'article_map': articles, 'collection_id': collection}
