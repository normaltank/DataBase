import json
import tempfile
import unittest
from pathlib import Path

from platform_app.source_catalog import initial_metadata
from platform_app.store import connect, initialize, save_revision


class SourceTypeTests(unittest.TestCase):
    def tags(self, classification, name='', original_name=''):
        return json.loads(initial_metadata(dict(kind='institution', classification=classification,
                                               name=name, original_name=original_name, raw_json='{}'))['institution_types'])

    def test_subunits_do_not_inherit_university_type(self):
        cases = [
            ('大学内部科研单位', '', '', ['research_institute']),
            ('大学人文社会科学研究单位', '拉脱维亚大学经济与社会科学学院',
             'Faculty of Economics and Social Sciences, University of Latvia', ['faculty']),
            ('大学历史研究单位候选', '拉脱维亚大学拉脱维亚历史研究所',
             'Institute of Latvian History, University of Latvia', ['research_institute']),
            ('大学全球研究中心', '里加斯特拉金什大学全球研究中心', '', ['research_institute']),
            ('大学文化研究中心', '', '', ['research_institute']),
            ('大学内部学院', '', '', ['faculty']),
            ('大学结构学院/期刊门户', '', '', ['faculty']),
            ('高等教育研究中心', '', '', ['research_institute']),
        ]
        for label, name, original, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(self.tags(label, name, original), expected)

    def test_explicit_higher_education_and_ambiguous_identity(self):
        for label in ['公立大学', '公立应用科学大学', '艺术类高校',
                      '位于拉脱维亚的国际高等教育/研究机构', '高等教育与法律研究机构',
                      '私立高等教育与研究机构候选', '国家高等教育/防务研究机构']:
            with self.subTest(label=label):
                self.assertIn('university', self.tags(label))
        for label in ['科学院/学术组织', '未独立核验的合作出版方候选']:
            with self.subTest(label=label):
                self.assertEqual(self.tags(label), ['other'])

    def test_historical_identity_and_named_think_tank_survive_fresh_defaults(self):
        row = dict(kind='institution', classification='历史高校/RTU 现行结构单位',
                   name='利耶帕亚大学', scope_status='historical', raw_json='{}')
        self.assertEqual(json.loads(initial_metadata(row)['institution_types']), ['university'])
        self.assertEqual(row['scope_status'], 'historical')
        self.assertEqual(set(self.tags('大学附属研究所（经济生产力与政策研究）',
                                      '拉脱维亚大学生产力研究所（LV PEAK 智库）',
                                      'Productivity Research Institute, University of Latvia')), {'research_institute', 'think_tank'})
        self.assertIn('think_tank', self.tags('大学附属研究所', '', 'University of Latvia Think Tank LV PEAK'))

    def test_correction_preserves_reviewed_types_manual_edits_and_history(self):
        from scripts.correct_source_types import apply, MIGRATION_ACTION, EVIDENCE_ACTION
        from platform_app.maintenance import restore_backup
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / 'data'
            initialize(data)
            db = connect(data / 'platform.sqlite3')
            examples = [
                ('FACULTY', '大学内部学院', '学院', ['university'], ['university', 'faculty']),
                ('PEAK', '大学附属研究所', '生产力研究所', ['research_institute'], ['research_institute', 'think_tank']),
                ('MANUAL', '大学文化研究中心', '文化研究中心', ['university', 'research_institute'], ['university', 'research_institute']),
            ]
            with db:
                for sid, label, name, generated, current in examples:
                    db.execute("INSERT INTO sources(id,name,kind,classification,institution_types,notes,raw_json,created_at,updated_at,version) VALUES (?,?,'institution',?,?,'保留人工备注','{}','old','old',2)",
                               (sid, name, label, json.dumps(generated)))
                    save_revision(db, 'source', sid, MIGRATION_ACTION, 'admin')
                    db.execute('UPDATE sources SET institution_types=?,version=3 WHERE id=?', (json.dumps(current), sid))
                    save_revision(db, 'source', sid, '人工编辑' if sid == 'MANUAL' else EVIDENCE_ACTION, 'admin')
            before = {r['id']: dict(r) for r in db.execute('SELECT * FROM sources')}
            old_history = [tuple(r) for r in db.execute('SELECT * FROM revisions ORDER BY id')]
            db.close()
            report = apply(data)
            self.assertEqual([r['id'] for r in report['changed']], ['FACULTY'])
            self.assertEqual([r['id'] for r in report['skipped']], ['MANUAL'])
            self.assertTrue(apply(data)['already_applied'])
            db = connect(data / 'platform.sqlite3')
            after = {r['id']: dict(r) for r in db.execute('SELECT * FROM sources')}
            self.assertEqual(json.loads(after['FACULTY']['institution_types']), ['faculty'])
            for sid in ['PEAK', 'MANUAL']:
                self.assertEqual(after[sid], before[sid])
            for key in before['FACULTY']:
                if key not in {'institution_types', 'version', 'updated_at', 'status'}:
                    self.assertEqual(after['FACULTY'][key], before['FACULTY'][key])
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM revisions ORDER BY id')][:-1], old_history)
            db.close()
            restored = restore_backup(report['backup'], Path(folder) / 'restored')
            db = connect(restored / 'platform.sqlite3')
            self.assertEqual({r['id']: dict(r) for r in db.execute('SELECT * FROM sources')}, before)
            db.close()


if __name__ == '__main__':
    unittest.main()
