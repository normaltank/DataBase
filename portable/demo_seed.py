"""Create only fictional, labeled examples through existing authenticated APIs.

Called once on a new temporary database. Existing data is never seeded or reset.
"""
import hashlib
import io
import json
from pathlib import Path

PASSWORD = 'LocalDemo2026!'
SOURCE_NAMES = ['演示｜北岸公共研究所', '演示｜河港社会研究中心', '演示｜波罗的海协作评论']
PEOPLE_NAMES = ['演示｜安娜·河港', '演示｜马丁·北岸']
ARTICLE_TITLES = ['演示｜邻里公共空间的协作记录', '演示｜社区阅读与志愿服务', '演示｜河港文化活动的组织方式']
COMPLETE_THEME = '演示｜公共空间与地方协作（已汇总）'
ACTIVE_THEME = '演示｜青年阅读与社区（进行中）'


def login(app, username):
    client = app.test_client()
    csrf = client.get('/api/session').json['csrf']
    result = client.post('/api/login', json={'username': username, 'password': PASSWORD},
                         headers={'X-CSRF-Token': csrf})
    if result.status_code != 200:
        raise RuntimeError('Synthetic account login failed: ' + username)
    return client


def call(client, path, data=None, file=None, method='POST'):
    options = {'headers': {'X-CSRF-Token': client.get('/api/session').json['csrf']}}
    if file:
        options['data'] = {'data': json.dumps(data or {}, ensure_ascii=False),
                           'file': (io.BytesIO(file[1]), file[0])}
    else:
        options['json'] = data or {}
    result = client.open(path, method=method, **options)
    result.request.close()
    if result.status_code not in (200, 201):
        raise RuntimeError(f'Synthetic API {path}: {result.status_code} {result.json}')
    return result.json


def txt(name, text):
    return name, ('【完全虚构的演示样例，不是研究结论】\n' + text + '\n').encode('utf-8')


def seed(app):
    researcher, lead, admin = [login(app, name) for name in ('researcher', 'colleague', 'admin')]
    # These are the documented public initialization accounts from store.py.
    members = admin.get('/api/members').json['items']
    if {m['username'] for m in members} != {'researcher', 'colleague', 'admin'}:
        raise RuntimeError('Seed is allowed only for the untouched public demo accounts.')
    if researcher.get('/api/records').json['items'] or researcher.get('/api/sources').json['items']:
        raise RuntimeError('Seed requires an empty database.')
    q = next(x for x in admin.get('/api/collaboration/qualifications').json['items'] if x['id'] == 'colleague')
    call(admin, '/api/collaboration/qualifications/colleague', {'version': q['version'], 'enabled': True}, method='PUT')
    sources = []
    for i, name in enumerate(SOURCE_NAMES):
        sources.append(call(researcher, '/api/sources', {
            'name': name, 'kind': 'journal' if i == 2 else 'institution',
            'country': '拉脱维亚', 'website': f'https://example.invalid/demo/source-{i+1}',
            'notes': '从零合成的虚构演示身份；国别只用于操作示例，不是事实记录。',
            'host_id': sources[0] if i == 2 else ''})['id'])
    people = []
    for name in PEOPLE_NAMES:
        people.append(call(researcher, '/api/people', {'name': name,
            'introduction_html': '<p>虚构演示人物，不对应真实作者或成员。</p>',
            'sources': 'https://example.invalid/demo/authors', 'change_note': '从零合成演示档案'})['id'])
    # Pillow is a required application dependency; the seed exercises its encoder and the real avatar API.
    from PIL import Image
    picture = io.BytesIO()
    Image.new('RGB', (96, 96), '#407985').save(picture, format='PNG')
    call(researcher, '/api/people/' + people[0], {'version': 1,
        'change_note': '合成纯色头像，非真人照片', 'avatar_source': '程序生成的演示纯色图'},
        file=('演示头像.png', picture.getvalue()), method='PUT')
    articles = []
    files = []

    def remember(client, url, expected=None):
        with client.get(url) as response:
            if response.status_code != 200 or (expected is not None and response.data != expected):
                raise RuntimeError('Synthetic download mismatch: ' + url)
            files.append({'url': url, 'sha256': hashlib.sha256(response.data).hexdigest(), 'bytes': len(response.data)})

    pdf = Path(__file__).with_name('samples') / 'fictional-article.pdf'
    for i, title in enumerate(ARTICLE_TITLES):
        file = ('演示原文.pdf', pdf.read_bytes()) if i == 0 else txt(f'演示资料{i+1}.txt',
            f'DEMO original {i+1}. This fictional text illustrates archiving only.\n中文阅读说明：仅用于操作，不代表实际观察。')
        rid = call(researcher, '/api/records', {'kind': 'journal_article' if i == 2 else 'report', 'title': title,
            'original_title': 'DEMO fictional community article ' + str(i+1),
            'authors': PEOPLE_NAMES[i % 2], 'source_id': sources[i] if i < 2 else sources[0],
            'serial_id': sources[2] if i == 2 else '', 'language': 'English',
            'published_on': '2026-10-01', 'countries': '拉脱维亚',
            'abstract': 'Fictional abstract for a local demonstration. No research claim.',
            'chinese_title': title, 'chinese_abstract': '合成中文摘要：演示资料保存、阅读与出处追溯，不含真实研究结论。',
            'body_html': '<p>DEMO: fictional source text created for this preview.</p><p>中文说明：所有来源、观点及身份均为虚构。</p>',
            'url': f'https://example.invalid/demo/article-{i+1}',
            'visibility': 'shared', 'sharing_confirmed': True}, file=file)['id']
        articles.append(rid)
        byline = researcher.get('/api/records/' + rid + '/bylines').json
        call(researcher, '/api/records/' + rid + '/bylines', {
            'version': byline['version'], 'record_version': byline['record_version'],
            'change_note': '虚构原文署名与合成作者档案的演示关联，不代表真实身份核实',
            'items': [{'raw_name': PEOPLE_NAMES[i % 2], 'status': 'confirmed',
                'target_type': 'person', 'target_id': people[i % 2],
                'evidence': f'本包从零生成的合成原文及档案：https://example.invalid/demo/article-{i+1}'}]}, method='PUT')
        detail = researcher.get('/api/records/' + rid).json
        for attachment in detail['attachments']:
            remember(researcher, '/api/attachments/' + attachment['id'], file[1])
            if attachment['index']['status'] != 'ready':
                raise RuntimeError('Bundled attachment parser did not index demo file: ' + str(attachment['index']))
    tid = call(lead, '/api/collaboration/topics', {'theme': COMPLETE_THEME,
        'participant_ids': ['researcher'], 'due_on': '2026-11-15'})['id']
    prefix = '/api/collaboration/topics/' + tid
    candidate = call(researcher, prefix + '/candidates', {'request_id': 'demo-candidate-1',
        'version': 0, 'topic_version': 1, 'note': '虚构候选报告第1项对应已入库资料'},
        file=txt('演示选题报告.txt', '候选第1项：邻里公共空间的协作记录。\n出处：https://example.invalid/demo/article-1'))['id']
    call(lead, prefix + '/meetings', {'request_id': 'demo-meeting-1', 'version': 0, 'topic_version': 1,
        'note': '虚构选题会：采用第1项，由研究员·林编译。', 'assignments': [{
            'title': ARTICLE_TITLES[0], 'source': 'https://example.invalid/demo/article-1',
            'record_id': articles[0], 'candidate_id': candidate, 'candidate_item': '第1项，第1页',
            'author_id': 'researcher', 'country': '拉脱维亚'}]},
        file=txt('演示会议决定.txt', '采用候选报告第1项；仅演示版本追溯。'))
    aid = researcher.get(prefix + '/workflow').json['assignments'][0]['id']
    assignment = prefix + '/assignments/' + aid
    first = call(researcher, assignment + '/submissions', {'request_id': 'demo-draft-1', 'version': 0,
        'topic_version': 1, 'meeting_version': 1, 'note': '初稿，供演示退回'},
        file=txt('演示编译稿-v1.txt', '初稿：公共空间协作的虚构说明，出处定位待补。'))['id']
    call(lead, assignment + '/returns', {'request_id': 'demo-return-1', 'submission_id': first,
        'topic_version': 1, 'meeting_version': 1, 'note': '演示意见：请补充出处定位，区分原文与说明。'})
    second = call(researcher, assignment + '/submissions', {'request_id': 'demo-draft-2', 'version': 1,
        'topic_version': 1, 'meeting_version': 1, 'note': '按演示审稿意见补齐出处'},
        file=txt('演示编译稿-v2.txt', '返修稿：原文第1段为虚构材料。研究员说明另列。\n出处：https://example.invalid/demo/article-1'))['id']
    final = call(lead, assignment + '/finals', {'request_id': 'demo-final-1', 'submission_id': second,
        'version': 2, 'topic_version': 1, 'meeting_version': 1, 'status': 'pending',
        'note': '确认演示v2原件；不表示研究质量验收', 'visibility': 'shared', 'sharing_confirmed': True})
    call(researcher, '/api/records/' + final['record_id'] + '/author', {'version': 1, 'confirm': True})
    call(researcher, prefix + '/summaries', {'request_id': 'demo-summary-1', 'version': 0,
        'topic_version': 1, 'author_id': 'researcher', 'final_ids': [final['id']],
        'note': '整期汇总固定采用v2定稿；原件可独立下载'},
        file=txt('演示整期汇总.txt', '本合成汇总采用演示编译稿v2。\n全部观点均为演示，不用于研究判断。'))
    active = call(lead, '/api/collaboration/topics', {'theme': ACTIVE_THEME,
        'participant_ids': ['researcher'], 'due_on': '2026-12-01'})['id']
    call(researcher, '/api/collaboration/topics/' + active + '/candidates', {
        'request_id': 'demo-active-candidate', 'version': 0, 'topic_version': 1,
        'note': '可用研究员账号继续上传下一版，再由负责人记录会议'},
        file=txt('演示进行中选题报告.txt', '候选：社区阅读与志愿服务，尚未开会决定。'))
    wid = call(researcher, '/api/collaboration/journals', {'journal_id': sources[2],
        'journal_name': SOURCE_NAMES[2], 'coverage': '2026年第1—2期（虚构）',
        'source_clue': 'https://example.invalid/demo/journal', 'content_kind': 'directory_translation'})['id']
    journal = '/api/collaboration/journals/' + wid
    for version in (1, 2):
        submitted = call(researcher, journal + '/submissions', {'version': version,
            'request_id': f'demo-journal-{version}', 'material_kind': 'product' if version == 2 else 'manuscript',
            'note': '独立期刊工作，不依附主题'},
            file=txt(f'演示期刊概览-v{version}.txt', f'虚构跨期目录概览v{version}。\n示例条目：河港文化活动的组织方式。'))
    call(researcher, journal + '/product', {'version': 3, 'submission_id': submitted['id'],
        'note': '明确采用演示期刊概览v2为当前成品'})
    workflow = researcher.get(prefix + '/workflow').json
    for row in workflow['assignments']:
        for sub in row['submissions']:
            remember(researcher, sub['file_url'])
    for row in workflow['meetings'] + workflow['summaries']:
        if row.get('file_url'):
            remember(researcher, row['file_url'])
    for topic in (tid, active):
        for row in researcher.get('/api/collaboration/topics/' + topic + '/candidates').json['items']:
            remember(researcher, row['file_url'])
    for sub in researcher.get(journal).json['submissions']:
        remember(researcher, sub['file_url'])
    payload = {'format': 1, 'synthetic': True, 'accounts': ['researcher', 'colleague', 'admin'],
        'source_ids': sources, 'person_ids': people, 'article_ids': articles,
        'complete_topic': tid, 'active_topic': active, 'journal': wid, 'files': files}
    (Path(app.config['DATA_DIR']) / 'demo-seed.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate the fictional preview through public APIs in a new directory. No collectors or AI workers.')
    parser.add_argument('--data-dir', required=True, type=Path)
    args = parser.parse_args()
    target = args.data_dir.resolve()
    if target.exists():
        parser.error('Use a new, nonexistent data directory; existing data is never reset.')
    from platform_app.web import create_app
    payload = seed(create_app(target))
    print(json.dumps({'data_dir': str(target), 'synthetic': True, 'articles': len(payload['article_ids']),
                      'sources': len(payload['source_ids']), 'people': len(payload['person_ids'])}))
