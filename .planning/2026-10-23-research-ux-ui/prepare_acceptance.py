"""Create synthetic, isolated UX acceptance data; never uses the real library."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from platform_app.web import create_app
from platform_app.store import connect

DEST = ROOT / 'tests' / 'artifacts' / 'ux-root'
DATA = DEST / 'data'
if (DATA / 'platform.sqlite3').exists():
    raise SystemExit('Existing acceptance database preserved; do not reseed it.')
DEST.mkdir(parents=True, exist_ok=True)
app = create_app(DATA, testing=True)
clients = {}
for uid in ['researcher', 'colleague', 'admin']:
    client = app.test_client()
    csrf = client.get('/api/session').json['csrf']
    response = client.post('/api/login', json={'username': uid, 'password': 'LocalDemo2026!'}, headers={'X-CSRF-Token': csrf})
    assert response.status_code == 200
    clients[uid] = client


def call(path, payload, uid='researcher', method='POST', file=None):
    c = clients[uid]
    args = {'headers': {'X-CSRF-Token': c.get('/api/session').json['csrf']}}
    if file:
        args['data'] = {'data': json.dumps(payload), 'file': (io.BytesIO(file[1]), file[0])}
    else:
        args['json'] = payload
    result = c.open(path, method=method, **args)
    assert result.status_code in (200, 201), (path, result.status_code, result.json)
    return result.json


def record(title, kind='research_article', **fields):
    return call('/api/records', {'title': title, 'kind': kind, **fields})['id']


ids = {}
ids['original'] = call('/api/records', {
    'title': '界面验收｜拉脱维亚语言教育政策：比较研究', 'original_title': 'Language education policy in Latvia — comparative reading',
    'kind': 'journal_article', 'authors': 'Sample Author', 'language': '英语', 'published_on': '2026-10-10',
    'publication_title': 'Sample Research Journal', 'url': 'https://example.org/article', 'doi': '10.0000/ux-example',
    'abstract': '这是隔离验收材料，用于检查阅读入口、署名阅读说明与引用时版本，不是真实研究结论。',
    'body_html': '<h2>阅读内容示例</h2><p>第一段讨论语言教育政策的比较维度。</p><table><tr><th>维度</th><th>观察</th></tr><tr><td>政策</td><td>保持来源、引文和个人判断的区别。</td></tr></table>',
    'sharing_confirmed': True,
}, file=('界面验收原文.txt', '仅用于界面验收的示例原文。\n样本不包含真实研究数据。'.encode('utf-8')))['id']
with connect(DATA / 'platform.sqlite3') as db:
    db.execute('UPDATE records SET raw_json=? WHERE id=?', (json.dumps({'imported_attachments': [
        {'url': 'https://example.org/article.pdf', 'type': 'pdf', 'name': '官方链接样本.pdf', 'sharing_status': 'not_migrated'},
        {'url': 'https://example.org/article.pdf', 'type': 'pdf'},
        {'url': 'javascript:alert(1)', 'type': 'pdf'},
        {'url': 'file:///C:/private/sample.pdf', 'type': 'pdf'},
        {'url': 'https://secret:password@example.org/file', 'type': 'pdf'},
    ]}), ids['original']))
ids['metadata_only'] = record('界面验收｜只有题录的材料', authors='Sample Author', abstract='无原文链接、无附件。应诚实说明可用入口。')
ids['external_only'] = record('界面验收｜仅有外部网页', url='https://example.org/external', authors='Sample Author')
ids['excerpt'] = record('界面验收｜语言教育摘录', kind='research_note', authors='林（验收样本）', evidence_record_id=ids['original'], quote='采用时的原文摘录 V1。', translation='采用时的中文译文 V1。', interpretation='研究说明 V1。', locator='第 3 页，第 2 段')
ids['report'] = record('界面验收｜阶段报告', kind='research_report', authors='林（验收样本）', body_html='<h2>阶段判断</h2><p>本报告采用摘录第一版，后续笔记修改不会悄悄改变依据。</p>', evidence_ids=[ids['excerpt']])
call('/api/records/' + ids['excerpt'], {'version': 1, 'quote': '后来修改的摘录 V2。', 'translation': '后来修改的译文 V2。'}, method='PUT')
call('/api/records/' + ids['original'], {'version': 1, 'title': '界面验收｜原文现用题名（第二版）', 'url': 'https://example.org/article-v2'}, method='PUT')
ids['reading_note'] = call('/api/records', {'title': '阅读说明｜适合比较研究的切入点', 'kind': 'research_note', 'authors': '周（验收样本）', 'linked_ids': [ids['original']], 'body_html': '<p>值得读的部分是不同政策维度的比较；局限是样本范围有限。这是研究员阅读说明，不是原文摘要。</p>'}, uid='colleague')['id']
ids['private_original'] = record('隐藏原文不可泄漏', visibility='restricted')
ids['private_excerpt'] = record('隐藏摘录不可泄漏', kind='research_note', evidence_record_id=ids['private_original'], quote='隐藏引文不可泄漏', locator='第 1 页', visibility='shared')
ids['mixed_report'] = record('界面验收｜含权限变化的引用清单', kind='research_report', evidence_ids=[ids['excerpt'], ids['private_excerpt']])
ids['unconfirmed'] = call('/api/records', {'title': '界面验收｜代交待作者确认', 'kind': 'research_report', 'author_id': 'researcher'}, uid='colleague')['id']
ids['topic'] = call('/api/collections', {'name': '界面验收｜语言与社会研究', 'visibility': 'shared', 'description': '汇集资料、阅读记录和阶段成果。', 'research_question': '语言政策如何影响教育实践？', 'comparison_html': '<table><tr><th>维度</th><th>原文观察</th><th>研究员解释</th></tr><tr><td>教育</td><td>资料中的证据</td><td>待进一步比较</td></tr></table>', 'stage_judgment': '先完善资料阅读，再比较不同观点。'})['id']
for name in ['original', 'excerpt', 'reading_note', 'report']:
    call('/api/collections/' + ids['topic'] + '/items', {'record_id': ids[name]})
for n in range(5):
    record(f'界面验收｜比较阅读材料 {n+1}：长题名、出处及检索状态的核查', authors='Sample Author', language='拉脱维亚语', published_on=f'2026-09-{10+n}', url=f'https://example.org/sample-{n}', abstract='这是仅用于隔离验收的资料。')
(DEST / 'fixtures.json').write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'data_dir': str(DATA), 'fixture_file': str(DEST/'fixtures.json'), 'sample_count': len(ids)}, ensure_ascii=False))
