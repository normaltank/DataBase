"""Account reading and Chinese discovery at the public HTTP/recovery seams."""
import csv
import tempfile
import io
import json
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from platform_app.web import create_app


class ReadingFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reading-feed-')
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / 'data'
        self.app = create_app(self.data_dir, testing=True)
        self.client = self.app.test_client()
        self.login()

    def login(self, name='researcher'):
        return self.call('/api/login', {'username': name, 'password': 'LocalDemo2026!'})

    def call(self, path, body=None, method='POST', status=200):
        token = self.client.get('/api/session').json['csrf']
        result = self.client.open(path, method=method, json=body or {}, headers={'X-CSRF-Token': token})
        self.assertEqual(result.status_code, status, result.json)
        return result.json

    def record(self, **values):
        return self.call('/api/records', {'title': 'Original', 'kind': 'report', **values}, status=201)

    def test_chinese_title_and_abstract_are_public_search_and_list_fields(self):
        record = self.record(title='Original title', abstract='Original abstract',
                             chinese_title='波罗的海政策', chinese_abstract='跨境能源安全')
        for word in ['波罗的海', '能源安全', 'Original']:
            result = self.client.get('/api/records', query_string={'q': word}).json
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['items'][0]['display_title'], '波罗的海政策')
            self.assertEqual(result['items'][0]['display_abstract'], '跨境能源安全')
            self.assertEqual(result['items'][0]['translation_origin'], 'human')
            self.assertEqual(result['items'][0]['title'], 'Original title')
        self.assertEqual(self.client.get('/api/records/' + record['id']).json['display_title'], '波罗的海政策')

    def test_new_batch_is_stable_and_only_explicit_filtered_confirmation_advances(self):
        with patch('platform_app.record_revisions.now', return_value='2026-01-01T00:00:00+00:00'):
            old = self.record(title='Old publication collected long ago', countries='爱沙尼亚')
        first = self.record(title='Recently collected old paper', published_on='2004', countries='拉脱维亚')
        second = self.record(title='Second new article', countries='爱沙尼亚')
        batch = self.call('/api/reading-batches')
        self.assertEqual(batch['reason'], 'first_visit')
        query = {'batch': batch['id'], 'batch_scope': 'recent', 'size': 1}
        initial = self.client.get('/api/records', query_string=query).json
        self.assertEqual(initial['total'], 2)
        ids = [initial['items'][0]['id']]
        late = self.record(title='Arrived while reading')
        self.call('/api/records/' + first['id'], {'version': 1, 'chinese_title': '稍后补译'}, method='PUT')
        ids += [self.client.get('/api/records', query_string={**query, 'page': 2}).json['items'][0]['id']]
        self.assertEqual(set(ids), {first['id'], second['id']})
        self.assertEqual(self.call('/api/reading-batches')['id'], batch['id'])
        self.assertEqual(self.client.get('/api/records', query_string={**query, 'batch_scope': 'all'}).json['total'], 3)
        self.call('/api/reading-batches/' + batch['id'] + '/finish',
                  {'conditions': {**query, 'country': '拉脱维亚'}})
        next_batch = self.call('/api/reading-batches')
        remaining = self.client.get('/api/records', query_string={'batch': next_batch['id'], 'batch_scope': 'all'}).json
        self.assertEqual({x['id'] for x in remaining['items']}, {old['id'], second['id'], late['id']})
        self.login('colleague')
        self.assertEqual(self.client.get('/api/records', query_string=query).status_code, 404)
        own = self.call('/api/reading-batches')
        self.assertEqual(own['pending_total'], 4)

    def test_combined_multiselects_use_article_subject_not_source_country_and_live_permissions(self):
        source = self.call('/api/sources', {'name': 'Latvian source', 'kind': 'institution', 'country': '拉脱维亚'}, status=201)
        a = self.record(title='Estonian research', source_id=source['id'], countries='爱沙尼亚;立陶宛',
                        keywords='能源;社会', language='en', body_html='<p>Actual body</p>')
        self.record(title='Unknown subject', source_id=source['id'], language='lv')
        self.record(title='Secret', countries='秘密国家', keywords='秘密主题', visibility='restricted')
        self.login('colleague')
        result = self.client.get('/api/records', query_string={'country': '爱沙尼亚|芬兰', 'source_country': '拉脱维亚',
                    'kind': 'report|policy', 'language': 'en|zh', 'topic': '能源', 'availability': 'body'}).json
        self.assertEqual([x['id'] for x in result['items']], [a['id']])
        self.assertEqual(self.client.get('/api/records?country=拉脱维亚').json['total'], 0)
        self.assertEqual(self.client.get('/api/records?country=__unknown__').json['total'], 1)
        facets = self.client.get('/api/records').json['facets']
        self.assertNotIn('秘密国家', [x['value'] for x in facets['country']])
        self.assertNotIn('秘密主题', [x['value'] for x in facets['topic']])
        self.assertEqual(self.client.get('/api/records?date_field=collected&from=2020-01-01').json['total'], 2)
        self.assertEqual(self.client.get('/api/records?from=2020-01-01').json['total'], 0)
        saved = self.call('/api/saved-searches', {'name': '组合关注', 'conditions': {'country': '爱沙尼亚|芬兰',
                                'kind': 'report|policy', 'date_field': 'collected', 'availability': 'body'}}, status=201)
        self.assertEqual(self.client.get('/api/records?saved_search='+saved['id']).json['total'], 1)

    def test_country_selection_matches_whole_entries_in_list_batch_and_exports(self):
        guinea = self.record(title='Guinea research', countries='几内亚')
        papua = self.record(title='Papua New Guinea research', countries='巴布亚新几内亚')
        selected = self.client.get('/api/records', query_string={'country':'几内亚'}).json
        self.assertEqual(selected['total'], 1)
        self.assertEqual([row['id'] for row in selected['items']], [guinea['id']])
        self.assertEqual(selected['facets']['country'], [{'value':'几内亚','count':1}])
        batch = self.call('/api/reading-batches')
        query = {'batch':batch['id'], 'batch_scope':'all', 'country':'几内亚'}
        self.assertEqual([row['id'] for row in self.client.get('/api/records', query_string=query).json['items']], [guinea['id']])
        export = self.client.get('/api/export', query_string=query)
        rows = list(csv.DictReader(io.StringIO(export.data.decode('utf-8-sig'))))
        self.assertEqual([row['稳定编号'] for row in rows], [guinea['id']])
        package = self.client.get('/api/export/content', query_string=query)
        with zipfile.ZipFile(io.BytesIO(package.data)) as archive:
            rows = json.loads(archive.read('content.json'))['records']
            self.assertEqual([row['id'] for row in rows], [guinea['id']])
        confirmed = self.call('/api/reading-batches/'+batch['id']+'/finish', {'conditions':query})
        self.assertEqual(confirmed['confirmed'], 1)
        following = self.call('/api/reading-batches')
        remaining = self.client.get('/api/records', query_string={'batch':following['id'], 'batch_scope':'all'}).json
        self.assertEqual([row['id'] for row in remaining['items']], [papua['id']])

    def test_country_whole_entries_keep_multicountry_or_unknown_and_casefold(self):
        guinea = self.record(title='Guinea', countries='几内亚')
        self.record(title='Papua New Guinea', countries='巴布亚新几内亚')
        multiple = self.record(title='Multiple subjects', countries=' LATVIA；Finland,几内亚，Estonia|Lithuania ')
        unknown = self.record(title='No subject entries', countries=' ;；,，| ')
        for selection in ['几内亚|latvia', ' 几内亚 | LaTvIa ']:
            rows = self.client.get('/api/records', query_string={'country':selection}).json
            self.assertEqual({row['id'] for row in rows['items']}, {guinea['id'],multiple['id']})
        for selection in ['Finland','Estonia','Lithuania','LATVIA']:
            rows = self.client.get('/api/records', query_string={'country':selection}).json
            self.assertEqual([row['id'] for row in rows['items']], [multiple['id']])
        rows = self.client.get('/api/records', query_string={'country':'__unknown__|latvia'}).json
        self.assertEqual({row['id'] for row in rows['items']}, {multiple['id'],unknown['id']})
        rows = self.client.get('/api/records', query_string={'country':'__unknown__'}).json
        self.assertEqual([row['id'] for row in rows['items']], [unknown['id']])
        self.assertEqual(rows['facets']['country'], [{'value':'__unknown__','count':1}])
        self.assertEqual(self.client.get('/api/records', query_string={'country':'Fin'}).json['total'], 0)

    def test_source_multi_selection_includes_unknown_without_expanding_to_other_sources(self):
        source = self.call('/api/sources', {'name':'Selected source', 'kind':'institution'}, status=201)
        other = self.call('/api/sources', {'name':'Other source', 'kind':'institution'}, status=201)
        known = self.record(title='Selected', source_id=source['id'])
        unknown = self.record(title='Unregistered source')
        self.record(title='Excluded source', source_id=other['id'])
        rows = self.client.get('/api/records', query_string={'source':source['id']+'|__unknown__'}).json
        self.assertEqual({r['id'] for r in rows['items']}, {known['id'],unknown['id']})

    @patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'synthetic-only', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com'})
    def test_matching_machine_projection_is_searchable_but_never_overrides_human_or_stale_input(self):
        record = self.record(title='Original input', abstract='Source abstract')
        job = self.call('/api/records/'+record['id']+'/translations', {'version': 1, 'request_id': 'synthetic'}, status=201)
        provider = MagicMock()
        provider.__enter__.return_value = provider
        provider.geturl.return_value = 'https://api.deepseek.com/chat/completions'
        provider.read.return_value = json.dumps({'choices': [{'message': {'content': json.dumps({'title': '机器能源译题', 'abstract': '中文处理摘要'})}}]}).encode()
        with patch('urllib.request.OpenerDirector.open', return_value=provider):
            self.call('/api/translations/'+job['id']+'/run')
        result = self.client.get('/api/records?q=中文处理').json
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['translation_origin'], 'machine')
        self.assertEqual(result['items'][0]['chinese_title'], '')
        with zipfile.ZipFile(io.BytesIO(self.client.get('/api/export/content?q=机器能源').data)) as package:
            exported=json.loads(package.read('content.json'))['records'][0]
            self.assertEqual(exported['display_title'],'机器能源译题')
            self.assertEqual(exported['translation_origin'],'machine')
            self.assertEqual(exported['display_abstract'],'中文处理摘要')
            self.assertEqual(exported['reading_translation_id'],job['id'])
            self.assertIn('机器能源译题',package.read(exported['path']).decode())
        csv_row = next(csv.DictReader(io.StringIO(self.client.get('/api/export?q=机器能源').data.decode('utf-8-sig'))))
        self.assertEqual(csv_row['当前阅读题名'], '机器能源译题')
        self.assertEqual(csv_row['当前阅读摘要'], '中文处理摘要')
        self.assertEqual(csv_row['阅读版本类型'], '机器中文，未人工校订')
        self.call('/api/records/'+record['id'], {'version': 1, 'chinese_title': '人工优先'}, method='PUT')
        result = self.client.get('/api/records/'+record['id']).json
        self.assertEqual(result['display_title'], '人工优先')
        self.assertEqual(result['display_abstract'], 'Source abstract')
        self.assertEqual(result['abstract_is_chinese'], False)
        self.assertEqual(result['reading_translation_id'], '')
        self.call('/api/records/'+record['id'], {'version': 2, 'title': 'Changed input', 'chinese_title': ''}, method='PUT')
        self.assertEqual(self.client.get('/api/records?q=机器能源').json['total'], 0)
        self.assertEqual(self.client.get('/api/records/'+record['id']).json['translation_origin'], 'original')

    def test_original_chinese_is_readable_without_a_translation_job(self):
        record = self.record(title='原始中文研究', abstract='原始中文摘要', language='zh-CN')
        result = self.client.get('/api/records?availability=chinese').json
        self.assertEqual([r['id'] for r in result['items']], [record['id']])
        self.assertTrue(result['items'][0]['has_chinese'])
        self.assertTrue(result['items'][0]['abstract_is_chinese'])
        self.assertEqual(result['items'][0]['translation_origin'], 'original')
        self.assertEqual(result['items'][0]['reading_translation_id'], '')
        self.assertEqual(self.client.get('/api/records?availability=translation_pending').json['total'], 0)

    def test_batch_and_chinese_content_restore_to_new_directory_and_permissions_stay_live(self):
        from platform_app.maintenance import create_backup, restore_backup
        record = self.record(chinese_title='中文恢复依据', chinese_abstract='恢复后的原译对应')
        batch = self.call('/api/reading-batches')
        self.login('colleague')
        other_batch = self.call('/api/reading-batches')
        self.login()
        saved = self.call('/api/saved-searches', {'name':'持久关注', 'conditions':{'q':'中文恢复', 'feed':'new'}}, status=201)
        self.login('admin')
        archive = create_backup(self.data_dir)
        restored = restore_backup(archive, Path(self.temp.name)/'restored')
        self.client = create_app(restored, testing=True).test_client()
        self.login()
        self.assertEqual(self.call('/api/reading-batches')['id'], batch['id'])
        self.assertEqual(self.client.get('/api/records', query_string={'batch':batch['id'], 'q':'中文恢复'}).json['total'], 1)
        self.assertEqual(self.client.get('/api/saved-searches/'+saved['id']).json['conditions'], {'q':'中文恢复', 'feed':'new'})
        for transient in ['batch', 'batch_scope', 'ids', 'page']:
            self.call('/api/saved-searches', {'name':'不能保存瞬时结果', 'conditions':{transient:batch['id']}}, status=400)
        export = self.client.get('/api/export/content?q=中文恢复')
        with zipfile.ZipFile(io.BytesIO(export.data)) as package:
            item = next(r for r in json.loads(package.read('content.json'))['records'] if r['id']==record['id'])
            self.assertEqual(item['chinese_title'], '中文恢复依据')
            self.assertIn('中文恢复依据', package.read(item['path']).decode())
        self.call('/api/records/'+record['id'], {'version':1, 'visibility':'restricted'}, method='PUT')
        self.login('colleague')
        query = {'batch':other_batch['id'], 'batch_scope':'all'}
        self.assertEqual(self.client.get('/api/records', query_string=query).json['total'], 0)
        self.assertEqual(self.call('/api/reading-batches')['pending_total'], 0)
        self.assertEqual(self.call('/api/reading-batches/'+other_batch['id']+'/finish', {'conditions':query})['confirmed'], 0)
        self.login()
        self.call('/api/records/'+record['id'], {'version':2, 'visibility':'shared'}, method='PUT')
        self.login('colleague')
        returned = self.call('/api/reading-batches')
        self.assertEqual(returned['pending_total'], 1)

    def test_long_absence_recent_start_keeps_all_unconfirmed_material(self):
        self.record(title='Existing')
        with patch('platform_app.reading_feed.now', return_value='2026-01-01T00:00:00+00:00'):
            first = self.call('/api/reading-batches')
            self.call('/api/reading-batches/'+first['id']+'/finish', {'conditions':{'batch_scope':'all'}})
        with patch('platform_app.record_revisions.now', return_value='2026-02-01T00:00:00+00:00'):
            old = self.record(title='Older unconfirmed')
        recent = self.record(title='Recent unconfirmed')
        batch = self.call('/api/reading-batches')
        self.assertEqual(batch['reason'], 'long_absence')
        self.assertEqual(self.client.get('/api/records', query_string={'batch':batch['id']}).json['total'], 1)
        all_rows = self.client.get('/api/records', query_string={'batch':batch['id'],'batch_scope':'all'}).json
        self.assertEqual({r['id'] for r in all_rows['items']}, {old['id'],recent['id']})

    def test_nonempty_old_library_has_preupgrade_backup_and_recovers_after_failed_increment(self):
        import sqlite3
        from contextlib import closing
        from platform_app.maintenance import create_backup, restore_backup
        fixtures=Path(__file__).parent/'fixtures'
        legacy=Path(self.temp.name)/'legacy-v11'
        legacy.mkdir()
        with closing(sqlite3.connect(legacy/'platform.sqlite3')) as db:
            db.executescript((fixtures/'collection_scope_v11.sql').read_text(encoding='utf-8'))
        expected=json.loads((fixtures/'collection_scope_v11.json').read_text(encoding='utf-8'))
        upgraded=restore_backup(create_backup(legacy),Path(self.temp.name)/'upgraded')
        self.client=create_app(upgraded,testing=True).test_client()
        self.login('colleague')
        rid=expected['record_id']
        before=self.client.get('/api/records/'+rid).json
        self.assertEqual(before['id'],rid)
        # Locate the migration artifact; all content/recovery assertions use HTTP.
        with closing(sqlite3.connect(upgraded/'platform.sqlite3')) as db:
            backup=Path(db.execute("SELECT value FROM settings WHERE key='reading_migration_backup'").fetchone()[0])
        failed=restore_backup(backup,Path(self.temp.name)/'before-v16')
        with closing(sqlite3.connect(failed/'platform.sqlite3')) as db:
            db.execute("CREATE TRIGGER reject_reading_upgrade BEFORE UPDATE ON settings WHEN NEW.value='16' BEGIN SELECT RAISE(ABORT,'synthetic upgrade failure'); END")
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            create_app(failed,testing=True)
        # Recovery accepts the rolled-back old schema and its complete material.
        recovered=restore_backup(create_backup(failed),Path(self.temp.name)/'recovered-after-failure')
        with closing(sqlite3.connect(recovered/'platform.sqlite3')) as db:
            db.execute('DROP TRIGGER reject_reading_upgrade')
            db.commit()
        self.client=create_app(recovered,testing=True).test_client()
        self.login('colleague')
        after=self.client.get('/api/records/'+rid).json
        for key in ['title','body_html','countries','visibility','version','chinese_title','chinese_abstract','attachment_ids']:
            self.assertEqual(after[key],before[key],key)
        self.assertEqual(self.client.get('/api/records/'+rid+'/translations').status_code,200)
        self.assertGreaterEqual(self.call('/api/reading-batches')['pending_total'],1)


if __name__ == '__main__':
    unittest.main()
