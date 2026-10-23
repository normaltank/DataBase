"""Independent public-API acceptance against synthetic UX fixtures only."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app

DEST = ROOT / 'tests' / 'artifacts' / 'ux-root'
ids = json.loads((DEST/'fixtures.json').read_text(encoding='utf-8'))
app = create_app(DEST/'data', testing=True)
checks = []


def check(name, condition):
    checks.append({'check': name, 'passed': bool(condition)})


def client(uid):
    c = app.test_client()
    token = c.get('/api/session').json['csrf']
    r = c.post('/api/login', json={'username': uid, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': token})
    assert r.status_code == 200
    return c


researcher, colleague = client('researcher'), client('colleague')
check('anonymous_copy_requires_login', app.test_client().get('/api/records/'+ids['original']+'/copy-text').status_code == 401)
detail = researcher.get('/api/records/'+ids['original']).json
access = detail.get('reading_access', {})
check('current_original_link', access.get('original_url') == 'https://example.org/article-v2')
official = access.get('official_files', [])
check('official_links_deduplicated_and_safe', [f['url'] for f in official] == ['https://example.org/article.pdf'])
check('platform_attachment_and_body_truthful', len(access.get('platform_files', [])) == 1 and access.get('has_body') is True)
if access.get('platform_files'):
    file_response = researcher.get(access['platform_files'][0]['url'])
    check('platform_file_download_works', file_response.status_code == 200 and '样本'.encode() in file_response.data)
bare = researcher.get('/api/records/'+ids['metadata_only']).json.get('reading_access', {})
check('metadata_not_marked_fulltext', bare.get('has_body') is False and not bare.get('original_url') and not bare.get('platform_files') and not bare.get('official_files'))
items = researcher.get('/api/records?q=界面验收').json['items']
check('summary_reading_access_present', bool(items) and all('reading_access' in x for x in items))
work = researcher.get('/api/dashboard').json.get('my_work', [])
check('my_work_only_confirmed_self', bool(work) and len(work) <= 4 and all(x['author_id'] == 'researcher' and x['author_confirmed'] and x['can_edit'] for x in work))
check('unconfirmed_proxy_not_my_work', ids['unconfirmed'] not in [x['id'] for x in work])
note = researcher.get('/api/records/'+ids['reading_note']).json
check('reading_note_attributed_and_author_permissions', note['author_id'] == 'colleague' and not note['can_edit'] and not note['evidence_record_id'] and any(x['id'] == ids['original'] for x in note['linked_records']))
copy = researcher.get('/api/records/'+ids['original']+'/copy-text')
check('citation_current_record', copy.status_code == 200 and copy.json['mode'] == 'citation' and '原文现用题名' in copy.json['text'] and '10.0000/ux-example' in copy.json['text'])
report = researcher.get('/api/records/'+ids['report']+'/copy-text')
text = report.json.get('text', '') if report.is_json else ''
check('report_uses_adopted_note_v1', report.status_code == 200 and report.json['mode'] == 'references' and '采用时的原文摘录 V1' in text and '后来修改的摘录 V2' not in text)
check('report_uses_adopted_original_v1', '拉脱维亚语言教育政策：比较研究' in text and '原文现用题名（第二版）' not in text and 'https://example.org/article-v2' not in text)
excerpt = researcher.get('/api/records/'+ids['excerpt']+'/copy-text')
check('excerpt_current_text_original_snapshot', excerpt.status_code == 200 and '后来修改的摘录 V2' in excerpt.json['text'] and '第 3 页，第 2 段' in excerpt.json['text'] and '原文现用题名（第二版）' not in excerpt.json['text'])
restricted = colleague.get('/api/records/'+ids['mixed_report']+'/copy-text')
check('copy_excludes_hidden_original_evidence', restricted.status_code == 200 and all(s not in restricted.json['text'] for s in ['隐藏原文不可泄漏', '隐藏摘录不可泄漏', '隐藏引文不可泄漏', ids['private_original'], ids['private_excerpt']]))
check('private_record_copy_denied', colleague.get('/api/records/'+ids['private_original']+'/copy-text').status_code == 404)
plain = colleague.get('/api/records/'+ids['reading_note']+'/copy-text')
check('ordinary_note_plaintext_with_current_association', plain.status_code == 200 and plain.json['mode'] == 'note' and '值得读的部分' in plain.json['text'] and '<p>' not in plain.json['text'] and '原文现用题名' in plain.json['text'])
result = {'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks)}
(DEST/'api-acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if all(c['passed'] for c in checks) else 1)
