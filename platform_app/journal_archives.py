"""Versioned journal facts, original issues and selected compilation content.

Source and record identities, content policy and original files remain owned by
their existing modules. These small documents add structure without converting
legacy free text, creating authors, or changing an article's bibliography.
"""
import copy
import hashlib
import html
import json
import re
import sqlite3
import uuid
from pathlib import Path

from flask import abort, jsonify, request, send_file

from . import identity, workflow
from .record_revisions import snapshot as record_snapshot
from .store import connect, now

SCHEMA_VERSION = 31

PROFILE_FIELDS = ('founded', 'frequency', 'frequency_evidence', 'print_issn', 'electronic_issn',
                  'publisher_text', 'publisher_evidence', 'indexing')
ISSUE_FIELDS = ('label', 'year', 'volume', 'number', 'published_on', 'special_note',
                'catalogue_evidence', 'checked_on', 'coverage_note')
ENTRY_FIELDS = ('title', 'chinese_title', 'authors', 'affiliations', 'doi', 'url', 'pages',
                'article_number', 'kind', 'record_id', 'relation_evidence', 'conflict_note')
CONTENT_KINDS = {'abstract_translation', 'editor_summary', 'unverified_extract', 'original_abstract'}
TABLES = {'profile': 'journal_profiles', 'issue': 'journal_issues', 'compilation': 'journal_compilations'}


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        version = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
        if version >= SCHEMA_VERSION:
            return
        if version != SCHEMA_VERSION - 1:
            raise ValueError('期刊档案迁移需要已完成的上一数据库版本。')
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            create_tables(db)
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES('journal_archives_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def create_tables(db):
    """Called only by the journal migration, after the preceding real version."""
    for kind, table in TABLES.items():
        reference = 'REFERENCES sources(id)' if kind == 'profile' else 'REFERENCES records(id)' if kind == 'compilation' else ''
        db.execute(f'''CREATE TABLE {table} (
            id TEXT PRIMARY KEY {reference}, source_id TEXT NOT NULL REFERENCES sources(id),
            version INTEGER NOT NULL, data_json TEXT NOT NULL,
            actor_id TEXT NOT NULL REFERENCES users(id), updated_at TEXT NOT NULL)''')
        db.execute(f'CREATE INDEX idx_{table}_source ON {table}(source_id)')
    db.execute('''CREATE TABLE journal_archive_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target_id TEXT NOT NULL,
        source_id TEXT NOT NULL REFERENCES sources(id), version INTEGER NOT NULL,
        actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL)''')
    db.execute('CREATE INDEX idx_journal_archive_history ON journal_archive_history(kind,target_id,id)')
    db.execute('''CREATE TABLE journal_covers (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), name TEXT NOT NULL,
        stored_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL, created_at TEXT NOT NULL)''')


def text(data, key, limit=4000):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        abort(400, '字段格式或长度不正确：' + key)
    return value.strip()


def rows(data, key, limit=200):
    result = data.get(key, [])
    if not isinstance(result, list) or len(result) > limit or any(not isinstance(row, dict) for row in result):
        abort(400, '条目格式或数量不正确：' + key)
    return result


def stable_id(data, seen):
    value = text(data, 'id') or uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value) or value in seen:
        abort(400, '条目编号重复或无效。')
    seen.add(value)
    return value


def document(row, fallback_id='', source_id=''):
    if not row:
        return {'id': fallback_id, 'source_id': source_id, 'version': 0}
    return {**json.loads(row['data_json']), 'id': row['id'], 'source_id': row['source_id'],
            'version': row['version'], 'actor_id': row['actor_id'], 'updated_at': row['updated_at']}


class JournalArchives:
    def __init__(self, db, actor, records, data_dir):
        self.db, self.actor, self.records, self.data_dir = db, actor, records, Path(data_dir)

    def source(self, sid):
        row = identity.resolve(self.db, 'sources', sid)
        if not row or row['kind'] != 'journal':
            abort(404, '期刊档案不存在。')
        return row

    def can_edit(self, sid):
        return sid not in self.actor.get('trial_sample_journals', [])

    def get(self, kind, sid, did, required=False):
        sid = self.source(sid)['id']
        row = self.db.execute(f'SELECT * FROM {TABLES[kind]} WHERE id=? AND source_id=?', (did, sid)).fetchone()
        if not row and self.db.execute(f'SELECT 1 FROM {TABLES[kind]} WHERE id=?', (did,)).fetchone():
            abort(409, '该内容已归属另一份期刊档案，请核对原有关系。')
        if not row and required:
            abort(404, '档案内容不存在。')
        return document(row, did, sid)

    def cover(self, sid, data):
        if not data:
            return {}
        if not isinstance(data, dict):
            abort(400, '封面信息格式不正确。')
        result = {key: text(data, key) for key in ['file_id', 'attachment_id', 'external_url', 'evidence', 'note', 'issue_id']}
        result['illustrative'] = data.get('illustrative', False)
        if type(result['illustrative']) is not bool or not result['evidence']:
            abort(400, '封面需要注明出处及示意用途。')
        if sum(bool(result[key]) for key in ['file_id', 'attachment_id', 'external_url']) != 1:
            abort(400, '请选择一份已保存封面或一条外部图片线索。')
        if result['external_url'] and not workflow.safe_link(result['external_url']):
            abort(400, '外部封面线索需要有效网址。')
        if result['file_id'] and not self.db.execute('SELECT 1 FROM journal_covers WHERE id=? AND source_id=?', (result['file_id'], sid)).fetchone():
            abort(400, '封面文件不属于本期刊。')
        if result['attachment_id']:
            attached = self.db.execute('SELECT * FROM attachments WHERE id=?', (result['attachment_id'],)).fetchone()
            if not attached:
                abort(404, '封面附件不存在。')
            self.records.get(attached['record_id'])
        if result['issue_id']:
            self.get('issue', sid, result['issue_id'], True)
        return result

    def visible_cover(self, sid, cover):
        result = copy.deepcopy(cover or {})
        if result.get('file_id'):
            item = self.db.execute('SELECT * FROM journal_covers WHERE id=? AND source_id=?', (result['file_id'], sid)).fetchone()
            if item:
                result['file'] = {key: item[key] for key in ['id', 'name', 'bytes', 'sha256', 'mime_type']}
                result['url'] = f'/api/journals/{sid}/covers/{item["id"]}'
        if result.get('attachment_id'):
            item = self.db.execute('SELECT a.*,r.visibility FROM attachments a JOIN records r ON r.id=a.record_id WHERE a.id=?', (result['attachment_id'],)).fetchone()
            current = identity.resolve(self.db, 'records', item['record_id']) if item else None
            if not current or not self.records.visible(current):
                return {'unavailable': True}
            result['attachment_name'] = item['name']
            result['url'] = f'/api/journals/{sid}/cover-attachments/{item["id"]}'
        return result

    def profile_values(self, sid, data):
        result = {key: text(data, key) for key in PROFILE_FIELDS}
        result['cover'] = self.cover(sid, data.get('cover'))
        result['metrics'], result['rankings'] = [], []
        seen = set()
        for item in rows(data, 'metrics'):
            metric = {key: text(item, key) for key in ['kind', 'name', 'value', 'year', 'released_year', 'evidence', 'raw_label', 'note']}
            metric['id'] = stable_id(item, seen)
            if metric['kind'] not in {'impact_factor', 'five_year', 'original'} or not metric['name'] or not metric['evidence']:
                abort(400, '指标需要名称、口径和出处。')
            if metric['value'] and not re.fullmatch(r'\d+(?:\.\d+)?', metric['value']):
                abort(400, '指标数值请填非负数字；原始混合文字另记。')
            result['metrics'].append(metric)
        for item in rows(data, 'rankings'):
            ranking = {key: text(item, key) for key in ['year', 'edition', 'evidence', 'raw_label', 'note']}
            ranking.update(id=stable_id(item, seen), subjects=[])
            if not ranking['evidence']:
                abort(400, '分区版本需要出处。')
            for sub in rows(item, 'subjects'):
                subject = {key: text(sub, key) for key in ['level', 'original_name', 'chinese_name', 'quartile', 'evidence']}
                if subject['level'] not in {'major', 'minor'} or not (subject['original_name'] or subject['chinese_name']):
                    abort(400, '分区需要大类／小类与学科名称。')
                if subject['quartile'] not in {'', '1', '2', '3', '4'}:
                    abort(400, '分区为1—4或留空待核实。')
                ranking['subjects'].append(subject)
            result['rankings'].append(ranking)
        return result

    def issue_values(self, sid, data):
        result = {key: text(data, key) for key in ISSUE_FIELDS}
        result['coverage'] = text(data, 'coverage') or 'unverified'
        if not any(result[key] for key in ['label', 'year', 'volume', 'number', 'coverage_note']):
            abort(400, '请填写原刊标识或已知覆盖范围。')
        if result['coverage'] not in {'complete', 'partial', 'unverified'}:
            abort(400, '请选择目次覆盖范围。')
        if result['coverage'] == 'complete' and not result['catalogue_evidence']:
            abort(400, '完整目次需要原目录依据。')
        result['cover'] = self.cover(sid, data.get('cover'))
        result['sections'], seen = [], set()
        for section in rows(data, 'sections', 100):
            group = {'id': stable_id(section, seen), 'title': text(section, 'title'), 'entries': []}
            for row in rows(section, 'entries', 500):
                entry = {key: text(row, key) for key in ENTRY_FIELDS}
                entry['id'] = stable_id(row, seen)
                if not entry['title']:
                    abort(400, '目次原文题名必填。')
                if entry['url'] and not workflow.safe_link(entry['url']):
                    abort(400, '原文地址无效。')
                if entry['record_id']:
                    original = self.records.get(entry['record_id'])
                    entry['record_id'] = original['id']
                    if original['kind'] in workflow.CONTENT_KINDS:
                        abort(400, '目次应关联原始资料，不能关联中心编译成果。')
                    conflicts = []
                    if entry['doi'] and original['doi'] and entry['doi'].casefold() != original['doi'].casefold():
                        conflicts.append('DOI不同')
                    for key, original_key in [('volume', 'volume'), ('number', 'issue')]:
                        if result[key] and original[original_key] and result[key].casefold() != original[original_key].casefold():
                            conflicts.append(f'{"卷号" if key == "volume" else "期号"}: {result[key]} / {original[original_key]}')
                    if original['serial_id'] and original['serial_id'] != sid:
                        conflicts.append('期刊身份不同')
                    if result['year'] and original['published_on'] and re.match(r'^\d{4}$', result['year']) and original['published_on'][:4] != result['year']:
                        conflicts.append('出版年份不同')
                    if conflicts and not entry['conflict_note']:
                        abort(409, '所选资料题录与原刊卷期冲突，当前输入请保留；核对后填写差异说明再保存。' + '；'.join(conflicts))
                    if not entry['relation_evidence']:
                        abort(400, '关联资料需要登记本期归属依据。')
                group['entries'].append(entry)
            result['sections'].append(group)
        if sum(len(s['entries']) for s in result['sections']) > 1000:
            abort(400, '一期目次不能超过1000条。')
        return result

    def compilation_values(self, sid, rid, data, old):
        record = self.records.get(rid, edit=True)
        for saved in old.get('selections', []):
            if saved['basis'].get('record_id'):
                self.records.get(saved['basis']['record_id'])
        if record['kind'] not in {'directory_translation', 'compilation', 'research_report'}:
            abort(400, '请选择目录译稿或现有个人编译成果。')
        if type(data.get('record_version')) is not int or data['record_version'] != record['version']:
            abort(409, '译稿正文或授权已经变化，请对照最新版本；当前输入请保留。')
        result = {key: text(data, key) for key in ['compiled_on', 'released_on', 'credits', 'coverage_note']}
        result['record_snapshot'] = {key: record[key] for key in ['id', 'kind', 'title', 'authors', 'coverage', 'body_html', 'version']}
        result['record_snapshot']['attachment_ids'] = json.loads(record['attachment_ids'])
        issue_ids = data.get('issue_ids', [])
        if not isinstance(issue_ids, list) or len(issue_ids) > 200 or any(not isinstance(i, str) for i in issue_ids):
            abort(400, '所关联原刊卷期格式不正确。')
        result['issue_ids'] = list(dict.fromkeys(issue_ids))
        for iid in result['issue_ids']:
            self.get('issue', sid, iid, True)
        result['selections'], seen = [], set()
        previous = {item['id']: item for item in old.get('selections', [])}
        for row in rows(data, 'selections', 500):
            item = {key: text(row, key, 40000 if key == 'original_abstract' else 4000) for key in ['issue_id', 'entry_id', 'kind', 'compiler', 'original_abstract']}
            item['id'] = stable_id(row, seen)
            if item['kind'] not in CONTENT_KINDS or not item['compiler']:
                abort(400, '选编内容需要类别和编译／录入署名。')
            try:
                item['body_html'], item['body_text'] = workflow.clean_rich(row.get('body_html', ''))
            except ValueError as error:
                abort(400, str(error))
            if not item['body_text']:
                abort(400, '选编正文不能为空。')
            issue = self.get('issue', sid, item['issue_id'], True)
            if item['issue_id'] not in result['issue_ids']:
                abort(400, '选编条目必须属于本译稿关联的原刊卷期。')
            entry = next((e for s in issue.get('sections', []) for e in s['entries'] if e['id'] == item['entry_id']), None)
            if not entry:
                abort(400, '所选目次条目不存在。')
            basis = row.get('basis', {})
            if not isinstance(basis, dict):
                abort(400, '原文依据格式不正确。')
            requested = {key: text(basis, key) for key in ['record_id', 'url', 'source_version', 'locator']}
            requested['record_version'] = basis.get('record_version')
            before = previous.get(item['id'], {}).get('basis', {})
            same = before and all(before.get(key) == value for key, value in requested.items())
            if same:
                frozen = copy.deepcopy(before)
                if frozen.get('record_id'):
                    self.records.get(frozen['record_id'])
            elif requested['record_id']:
                original = self.records.get(requested['record_id'])
                if entry['record_id'] and entry['record_id'] != original['id']:
                    abort(400, '所据资料与目次关联不同，请先核对归属。')
                version = requested['record_version']
                if type(version) is not int or version < 1:
                    abort(400, '请选择实际所据资料版本。')
                if version == original['version']:
                    snapshot = record_snapshot(self.db, original['id'])
                else:
                    history = self.db.execute("SELECT snapshot_json FROM revisions WHERE target_type='record' AND target_id=? AND json_extract(snapshot_json,'$.version')=? ORDER BY id DESC LIMIT 1", (original['id'], version)).fetchone()
                    if not history:
                        abort(400, '未找到所据原文版本。')
                    snapshot = json.loads(history[0])
                frozen = {**requested, 'record_id': original['id'], 'snapshot': {key: snapshot.get(key, '') for key in ['id', 'title', 'original_title', 'authors', 'abstract', 'body_html', 'url', 'doi', 'version', 'attachment_ids']}}
                frozen['snapshot']['attachment_ids'] = json.loads(snapshot['attachment_ids']) if isinstance(snapshot.get('attachment_ids'), str) else snapshot.get('attachment_ids', [])
                from .fulltext import material
                frozen['snapshot']['original_material'] = material(snapshot)
                frozen['snapshot']['saved_originals'] = [{key: file[key] for key in ['id', 'attachment_id', 'sha256', 'bytes', 'retrieved_at', 'extraction_json']} for file in self.db.execute('SELECT * FROM saved_originals WHERE record_id=?', (original['id'],)) if file['attachment_id'] in frozen['snapshot']['attachment_ids']]
            else:
                if requested['record_version'] is not None:
                    abort(400, '没有入库资料时不能填写资料版本号。')
                if not requested['url'] or not workflow.safe_link(requested['url']) or not (requested['source_version'] or requested['locator']):
                    abort(400, '未入库原文需注明网址及来源版本或位置。')
                frozen = {**requested, 'snapshot': {'abstract': item['original_abstract']}}
            if item['kind'] == 'abstract_translation' and not frozen.get('snapshot', {}).get('abstract'):
                abort(400, '没有所据原文摘要，不能标为摘要译文；可改选编者概述。')
            item['basis'] = frozen
            item['entry_snapshot'] = copy.deepcopy(previous[item['id']]['entry_snapshot'] if same and previous[item['id']]['entry_id'] == item['entry_id'] else entry)
            result['selections'].append(item)
        return result

    def public(self, kind, value):
        value = copy.deepcopy(value)
        sid = value['source_id']
        if 'cover' in value:
            value['cover'] = self.visible_cover(sid, value['cover'])
        if kind == 'issue':
            for section in value.get('sections', []):
                for entry in section['entries']:
                    if entry.get('record_id'):
                        original = identity.resolve(self.db, 'records', entry['record_id'])
                        if not original or not self.records.visible(original):
                            entry['record_id'] = ''
                            entry['record_unavailable'] = True
                        else:
                            entry['record'] = {'id': original['id'], 'title': original['title'], 'version': original['version']}
        if kind == 'compilation':
            record = self.records.get(value['id'])
            value['can_edit'] = self.records.editable(record)
            if not value['can_edit']:
                value.pop('record_snapshot', None)
            value['record_version'] = record['version']
            visible = []
            for item in value.get('selections', []):
                basis = item['basis']
                original = identity.resolve(self.db, 'records', basis.get('record_id', '')) if basis.get('record_id') else None
                if basis.get('record_id') and (not original or not self.records.visible(original)):
                    visible.append({'id': item['id'], 'unavailable': True})
                    value['can_edit'] = False
                    continue
                item['needs_review'] = bool(original and original['version'] != basis['record_version'])
                item['current_record_version'] = original['version'] if original else None
                basis['snapshot']['attachments'] = []
                for aid in basis['snapshot'].get('attachment_ids', []):
                    attached = self.db.execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
                    if attached:
                        basis['snapshot']['attachments'].append({key: attached[key] for key in ['id', 'name', 'bytes', 'sha256']})
                        basis['snapshot']['attachments'][-1]['url'] = f'/api/journals/{sid}/compilations/{value["id"]}/basis/{item["id"]}/attachments/{aid}?archive_version={value["version"]}'
                visible.append(item)
            value['selections'] = visible
        return value

    def save(self, kind, sid, did, data, creating=False):
        sid = self.source(sid)['id']
        if not self.can_edit(sid):
            abort(403, '公共期刊演示只供阅读，请建立自己的练习档案。')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.get(kind, sid, did, required=kind != 'profile' and not creating)
            if type(data.get('version')) is not int or data['version'] != old['version']:
                abort(409, '已有成员保存了新版本；当前输入请保留并对照最新版本。')
            if kind == 'profile':
                values = self.profile_values(sid, data)
            elif kind == 'issue':
                values = self.issue_values(sid, data)
            else:
                values = self.compilation_values(sid, did, data, old)
            version, stamp = old['version'] + 1, now()
            self.db.execute(f'''INSERT INTO {TABLES[kind]} VALUES (?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET version=excluded.version,data_json=excluded.data_json,
                actor_id=excluded.actor_id,updated_at=excluded.updated_at''',
                (did, sid, version, json.dumps(values, ensure_ascii=False), self.actor['id'], stamp))
            saved = {**values, 'id': did, 'source_id': sid, 'version': version, 'actor_id': self.actor['id'], 'updated_at': stamp}
            self.db.execute('INSERT INTO journal_archive_history(kind,target_id,source_id,version,actor_id,created_at,snapshot_json) VALUES (?,?,?,?,?,?,?)',
                            (kind, did, sid, version, self.actor['id'], stamp, json.dumps(saved, ensure_ascii=False)))
        return self.public(kind, saved)

    def history(self, kind, sid, did):
        self.get(kind, sid, did, True)
        if kind == 'compilation':
            self.records.get(did, edit=True)
        return [{**{key: row[key] for key in ['id', 'version', 'actor_id', 'actor_name', 'created_at']}, 'snapshot': self.public(kind, json.loads(row['snapshot_json']))} for row in self.db.execute(
            '''SELECT h.id,h.version,h.actor_id,u.name AS actor_name,h.created_at,h.snapshot_json
               FROM journal_archive_history h JOIN users u ON u.id=h.actor_id
               WHERE h.kind=? AND h.target_id=? ORDER BY h.id DESC''', (kind, did))]

    def detail(self, sid):
        sid = self.source(sid)['id']
        profile = self.get('profile', sid, sid)
        issues = [self.public('issue', document(row)) for row in self.db.execute('SELECT * FROM journal_issues WHERE source_id=? ORDER BY updated_at DESC,id', (sid,))]
        compilations = []
        for row in self.db.execute('SELECT c.*,r.title,r.coverage,r.kind FROM journal_compilations c JOIN records r ON r.id=c.id WHERE c.source_id=? ORDER BY c.updated_at DESC', (sid,)):
            record = identity.resolve(self.db, 'records', row['id'])
            if record and self.records.visible(record):
                compilations.append({**self.public('compilation', document(row)), 'title': row['title'], 'coverage': row['coverage'], 'kind': row['kind']})
        return {'id': sid, 'can_edit': self.can_edit(sid), 'profile': self.public('profile', profile), 'issues': issues, 'compilations': compilations}


def validate_source_type(db, sid, kind):
    if kind == 'journal' or not db.execute("SELECT 1 FROM sqlite_master WHERE name='journal_profiles'").fetchone():
        return
    if any(db.execute(f'SELECT 1 FROM {table} WHERE source_id=? LIMIT 1', (sid,)).fetchone() for table in TABLES.values()):
        abort(409, '本档案已有期刊信息、卷期或选编依据，不能改成非期刊对象。请保留原档案并核对身份。')


def validate_backup(db, manifest):
    """Validate current documents, their complete revision chain and saved files."""
    required = {*TABLES.values(), 'journal_archive_history', 'journal_covers'}
    if not required <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        raise ValueError('备份缺少期刊档案结构。')

    def check_cover(value, sid):
        if not value:
            return
        if not isinstance(value, dict) or not value.get('evidence') or type(value.get('illustrative')) is not bool:
            raise ValueError('期刊封面依据或用途不完整。')
        if sum(bool(value.get(k)) for k in ['file_id', 'attachment_id', 'external_url']) != 1:
            raise ValueError('期刊封面引用无效。')
        if value.get('file_id') and not db.execute('SELECT 1 FROM journal_covers WHERE id=? AND source_id=?', (value['file_id'], sid)).fetchone():
            raise ValueError('期刊历史封面文件引用缺失。')
        if value.get('attachment_id') and not db.execute('SELECT 1 FROM attachments WHERE id=?', (value['attachment_id'],)).fetchone():
            raise ValueError('期刊封面附件缺失。')
        if value.get('external_url') and not workflow.safe_link(value['external_url']):
            raise ValueError('期刊封面线索无效。')

    def check(kind, value, did, sid, version):
        if value['id'] != did or value['source_id'] != sid or type(value['version']) is not int or value['version'] != version or version < 1:
            raise ValueError('期刊档案对象或版本不一致。')
        if not db.execute("SELECT 1 FROM sources WHERE id=? AND kind='journal'", (sid,)).fetchone():
            raise ValueError('期刊档案身份缺失。')
        check_cover(value.get('cover'), sid)
        if kind == 'profile':
            if did != sid or any(not isinstance(value[k], str) for k in PROFILE_FIELDS):
                raise ValueError('期刊基本信息不完整。')
            if not isinstance(value['metrics'], list) or not isinstance(value['rankings'], list):
                raise ValueError('期刊年度指标缺失。')
            for m in value['metrics']:
                if not m['name'] or not m['evidence'] or m['kind'] not in {'impact_factor', 'five_year', 'original'}:
                    raise ValueError('期刊指标出处或口径缺失。')
                if m['value'] and not re.fullmatch(r'\d+(?:\.\d+)?', m['value']):
                    raise ValueError('期刊指标数值无效。')
            for ranking in value['rankings']:
                if not ranking['evidence'] or not isinstance(ranking['subjects'], list):
                    raise ValueError('期刊分区版本依据不完整。')
                for sub in ranking['subjects']:
                    if sub['level'] not in {'major', 'minor'} or sub['quartile'] not in {'', '1', '2', '3', '4'}:
                        raise ValueError('期刊学科分区无效。')
        elif kind == 'issue':
            if value['coverage'] not in {'complete', 'partial', 'unverified'} or (value['coverage'] == 'complete' and not value['catalogue_evidence']):
                raise ValueError('原刊目次覆盖依据缺失。')
            seen = set()
            for section in value['sections']:
                if section['id'] in seen:
                    raise ValueError('期刊目次顺序编号重复。')
                seen.add(section['id'])
                for entry in section['entries']:
                    if not entry['title'] or entry['id'] in seen:
                        raise ValueError('期刊目次题名或编号无效。')
                    seen.add(entry['id'])
                    if entry['record_id'] and not db.execute('SELECT 1 FROM records WHERE id=?', (entry['record_id'],)).fetchone():
                        raise ValueError('期刊目次资料关联缺失。')
        else:
            if not db.execute("SELECT 1 FROM records WHERE id=? AND kind IN ('directory_translation','compilation','research_report')", (did,)).fetchone():
                raise ValueError('期刊编译成果身份缺失。')
            parent = value['record_snapshot']
            if parent['id'] != did or type(parent['version']) is not int or parent['version'] < 1 or not isinstance(parent['body_html'], str):
                raise ValueError('选编保存时的整体译稿版本缺失。')
            for aid in parent['attachment_ids']:
                if not db.execute('SELECT 1 FROM attachments WHERE id=? AND record_id=?', (aid, did)).fetchone():
                    raise ValueError('整体译稿历史附件缺失。')
            for iid in value['issue_ids']:
                if not db.execute('SELECT 1 FROM journal_issues WHERE id=? AND source_id=?', (iid, sid)).fetchone():
                    raise ValueError('跨期编译的原刊卷期缺失。')
            for item in value['selections']:
                basis = item['basis']
                if item['kind'] not in CONTENT_KINDS or item['issue_id'] not in value['issue_ids'] or not item['entry_snapshot']['title']:
                    raise ValueError('选编内容与目次关系无效。')
                if basis['record_id']:
                    if not db.execute('SELECT 1 FROM records WHERE id=?', (basis['record_id'],)).fetchone() or basis['snapshot']['id'] != basis['record_id'] or basis['snapshot']['version'] != basis['record_version']:
                        raise ValueError('选编所据原文版本不完整。')
                    for aid in basis['snapshot'].get('attachment_ids', []):
                        if not db.execute('SELECT 1 FROM attachments WHERE id=? AND record_id=?', (aid, basis['record_id'])).fetchone():
                            raise ValueError('选编所据历史附件缺失。')
                elif not workflow.safe_link(basis['url']) or not (basis['source_version'] or basis['locator']):
                    raise ValueError('未入库选编依据缺失。')
                if item['kind'] == 'abstract_translation' and not basis['snapshot'].get('abstract'):
                    raise ValueError('摘要译文缺少所据原文摘要。')

    try:
        for table in TABLES.values():
            db.execute(f'SELECT id,source_id,version,data_json,actor_id,updated_at FROM {table} LIMIT 0')
        db.execute('SELECT id,kind,target_id,source_id,version,actor_id,created_at,snapshot_json FROM journal_archive_history LIMIT 0')
        db.execute('SELECT id,source_id,name,stored_name,mime_type,bytes,sha256,created_at FROM journal_covers LIMIT 0')
        for kind, table in TABLES.items():
            for row in db.execute(f'SELECT * FROM {table}'):
                current = document(row)
                check(kind, current, row['id'], row['source_id'], row['version'])
                revisions = db.execute('SELECT * FROM journal_archive_history WHERE kind=? AND target_id=? ORDER BY version', (kind, row['id'])).fetchall()
                if [r['version'] for r in revisions] != list(range(1, row['version'] + 1)):
                    raise ValueError('期刊档案历史版本链不完整。')
                for event in revisions:
                    snapshot = json.loads(event['snapshot_json'])
                    check(kind, snapshot, row['id'], row['source_id'], event['version'])
                    if snapshot['actor_id'] != event['actor_id'] or snapshot['updated_at'] != event['created_at']:
                        raise ValueError('期刊档案历史操作者不一致。')
                if json.loads(revisions[-1]['snapshot_json']) != current:
                    raise ValueError('期刊档案当前版本与留档不一致。')
        for row in db.execute('SELECT * FROM journal_archive_history'):
            if row['kind'] not in TABLES or not db.execute(f'SELECT 1 FROM {TABLES[row["kind"]]} WHERE id=? AND source_id=?', (row['target_id'], row['source_id'])).fetchone():
                raise ValueError('期刊档案历史缺少所属对象。')
        for row in db.execute('SELECT * FROM journal_covers'):
            path = 'journal-covers/' + row['stored_name']
            if not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png|webp)', row['stored_name']) or manifest['files'].get(path) != {'sha256': row['sha256'], 'bytes': row['bytes']}:
                raise ValueError('期刊封面与备份文件不一致。')
        expected_files = {'journal-covers/' + row[0] for row in db.execute('SELECT stored_name FROM journal_covers')}
        if {name for name in manifest['files'] if name.startswith('journal-covers/')} != expected_files:
            raise ValueError('备份包含未登记的期刊封面。')
    except (KeyError, TypeError, IndexError, sqlite3.Error, json.JSONDecodeError) as error:
        raise ValueError('期刊档案备份结构不完整。') from error


def export_projection(service, source_ids, record_ids):
    result = []
    for sid in source_ids:
        source = service.db.execute("SELECT 1 FROM sources WHERE id=? AND kind='journal'", (sid,)).fetchone()
        if not source:
            continue
        item = service.detail(sid)
        item['compilations'] = [doc for doc in item['compilations'] if doc['id'] in record_ids]
        item['history'] = []
        objects = [('profile', item['profile'])] if item['profile']['version'] else []
        objects += [('issue', doc) for doc in item['issues']]
        objects += [('compilation', doc) for doc in item['compilations']]
        for kind, doc in objects:
            if kind == 'compilation' and not doc.get('can_edit'):
                continue
            item['history'].append({'kind': kind, 'id': doc['id'], 'items': service.history(kind, sid, doc['id'])})
        if objects:
            result.append(item)
    return result


def export_html(item, record_paths, relative='../'):
    labels = {**dict(zip(PROFILE_FIELDS, ['创刊时间', '发行周期', '周期依据', '纸本ISSN', '电子ISSN', '出版方原词', '出版方依据', '收录信息'])),
              'metrics': '影响因子记录', 'rankings': '中科院分区版本', 'subjects': '学科', 'kind': '类别', 'name': '名称', 'value': '数值', 'year': '指标／出版年度', 'released_year': '发布年份', 'evidence': '出处', 'raw_label': '原始标注', 'note': '核对说明', 'edition': '版本', 'level': '大类／小类', 'original_name': '学科原名', 'chinese_name': '学科中文名', 'quartile': '分区', 'label': '原刊卷期', 'volume': '卷', 'number': '期', 'published_on': '原刊出版日期', 'coverage': '目次覆盖', 'catalogue_evidence': '原目次出处', 'checked_on': '核对时间', 'sections': '有序栏目', 'entries': '有序目次', 'title': '原文题名', 'chinese_title': '中文译题', 'authors': '原始署名', 'affiliations': '署名单位', 'record_id': '资料编号', 'relation_evidence': '本期归属依据', 'conflict_note': '题录差异说明', 'selections': '选编内容', 'basis': '所据原文版本', 'snapshot': '采用时原文', 'abstract': '采用时原文摘要', 'record_version': '采用资料版本', 'source_version': '来源／样稿版本', 'locator': '位置', 'compiler': '编译署名', 'compiled_on': '编译时间', 'released_on': '中心发布日期', 'credits': '编译／审校署名', 'coverage_note': '覆盖说明', 'version': '版本', 'issue_ids': '所关联原刊卷期', 'cover': '有据封面', 'illustrative': '示意用途'}

    def render(value):
        if isinstance(value, list):
            return '<ol>' + ''.join('<li>' + render(row) + '</li>' for row in value) + '</ol>'
        if isinstance(value, dict):
            content = ''
            if value.get('unavailable'):
                return '<p>当前账号不可读，已按权限收起。</p>'
            if value.get('file', {}).get('path'):
                content += '<img style="max-width:160px" alt="期刊封面" src="' + relative + html.escape(value['file']['path']) + '">'
            if value.get('path', '').startswith('attachments/'):
                content += '<a href="' + relative + html.escape(value['path']) + '">' + html.escape(value.get('name', '所据历史附件')) + '</a>'
            if value.get('record_id') in record_paths:
                content += '<a href="' + relative + record_paths[value['record_id']] + '">打开资料</a>'
            for key, data in value.items():
                if key in {'snapshot_json', 'body_text', 'file', 'record', 'entry_snapshot'}:
                    continue
                if key == 'body_html':
                    content += workflow.clean_rich(data)[0]
                elif data not in (None, '', [], {}):
                    content += '<dt>' + html.escape(labels.get(key, key)) + '</dt><dd>' + render(data) + '</dd>'
            return '<dl>' + content + '</dl>'
        if isinstance(value, str) and workflow.safe_link(value):
            return '<a href="' + html.escape(value, quote=True) + '">' + html.escape(value) + '</a>'
        return '<span style="white-space:pre-wrap">' + html.escape(str(value)) + '</span>'
    content = '<h2>期刊深档案与年度指标</h2>' + render(item['profile'])
    content += '<h2>原刊卷期与有序目次</h2>' + render(item['issues'])
    content += '<h2>跨期译稿与选编依据</h2>' + render(item['compilations'])
    for group in item['history']:
        content += '<details><summary>修改历史 · ' + html.escape(group['kind'] + ' · ' + group['id']) + '</summary>' + render(group['items']) + '</details>'
    return content


def prepare_export_files(db, archives, attachments):
    covers = {}
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if value.get('file_id'):
                row = db.execute('SELECT * FROM journal_covers WHERE id=?', (value['file_id'],)).fetchone()
                if row:
                    item = {**dict(row), 'path': 'journal-covers/' + row['stored_name']}
                    covers[row['id']] = item
                    value['file'] = {**value.get('file', {}), 'path': item['path']}
            if value.get('snapshot', {}).get('attachment_ids'):
                value['snapshot']['files'] = []
                for aid in value['snapshot']['attachment_ids']:
                    row = db.execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
                    if row:
                        attachments[aid] = {**dict(row), 'path': 'attachments/' + row['stored_name']}
                        value['snapshot']['files'].append({'id': aid, 'name': row['name'], 'path': attachments[aid]['path']})
            if value.get('record_snapshot', {}).get('attachment_ids'):
                value['record_snapshot']['files'] = []
                for aid in value['record_snapshot']['attachment_ids']:
                    row = db.execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
                    if row:
                        attachments[aid] = {**dict(row), 'path': 'attachments/' + row['stored_name']}
                        value['record_snapshot']['files'].append({'id': aid, 'name': row['name'], 'path': attachments[aid]['path']})
            if value.get('attachment_id') and not value.get('unavailable'):
                aid = value['attachment_id']
                row = db.execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
                if row:
                    attachments[aid] = {**dict(row), 'path': 'attachments/' + row['stored_name']}
            for key, item in list(value.items()):
                if key != 'snapshot_json':
                    visit(item)
    visit(archives)
    return covers


def register(app, ctx):
    def service():
        return JournalArchives(ctx.db(), ctx.user(), ctx.records(), ctx.data_dir)

    @app.get('/api/journals/<sid>')
    def journal_archive(sid):
        return jsonify(service().detail(sid))

    @app.put('/api/journals/<sid>/profile')
    def journal_profile_save(sid):
        svc = service()
        canonical = svc.source(sid)['id']
        return jsonify(svc.save('profile', canonical, canonical, ctx.body()))

    @app.post('/api/journals/<sid>/issues')
    def journal_issue_create(sid):
        data = ctx.body()
        return jsonify(service().save('issue', sid, 'JI-' + uuid.uuid4().hex, data, True)), 201

    @app.get('/api/journals/<sid>/issues/<iid>')
    def journal_issue(sid, iid):
        svc = service()
        return jsonify(svc.public('issue', svc.get('issue', sid, iid, True)))

    @app.put('/api/journals/<sid>/issues/<iid>')
    def journal_issue_save(sid, iid):
        return jsonify(service().save('issue', sid, iid, ctx.body()))

    @app.get('/api/journals/<sid>/compilations/<rid>')
    def journal_compilation(sid, rid):
        svc = service()
        svc.records.get(rid)
        return jsonify(svc.public('compilation', svc.get('compilation', sid, rid)))

    @app.put('/api/journals/<sid>/compilations/<rid>')
    def journal_compilation_save(sid, rid):
        svc = service()
        svc.records.get(rid, edit=True)
        return jsonify(svc.save('compilation', sid, rid, ctx.body(), True))

    @app.get('/api/journals/<sid>/compilations/<rid>/basis/<selection_id>/attachments/<aid>')
    def journal_adopted_attachment(sid, rid, selection_id, aid):
        svc = service()
        svc.records.get(rid)
        doc = svc.get('compilation', sid, rid, True)
        requested = request.args.get('archive_version', str(doc['version']))
        if not requested.isdigit():
            abort(400, '采用版本格式不正确。')
        if int(requested) != doc['version']:
            svc.records.get(rid, edit=True)
            row = ctx.db().execute("SELECT snapshot_json FROM journal_archive_history WHERE kind='compilation' AND target_id=? AND source_id=? AND version=?", (rid, doc['source_id'], int(requested))).fetchone()
            if not row:
                abort(404, '未找到所据编译历史版本。')
            doc = json.loads(row['snapshot_json'])
        selected = next((item for item in doc['selections'] if item['id'] == selection_id), None)
        if not selected or aid not in selected['basis']['snapshot'].get('attachment_ids', []):
            abort(404, '附件不属于这条采用依据。')
        original = svc.records.get(selected['basis']['record_id'])
        attached = ctx.db().execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
        if not attached or svc.records.get(attached['record_id'])['id'] != original['id']:
            abort(404)
        from .attachment_search import original_path
        path = original_path(ctx.data_dir, attached)
        if path is None:
            abort(404, '采用的原附件文件缺失。')
        return send_file(path, as_attachment=True, download_name=attached['name'])

    @app.get('/api/journals/<sid>/<kind>/<did>/history')
    def journal_archive_history(sid, kind, did):
        key = {'issues': 'issue', 'compilations': 'compilation'}.get(kind)
        if not key:
            abort(404)
        return jsonify(items=service().history(key, sid, did))

    @app.get('/api/journals/<sid>/profile/history')
    def journal_profile_history(sid):
        svc = service()
        canonical = svc.source(sid)['id']
        return jsonify(items=svc.history('profile', canonical, canonical))

    @app.post('/api/journals/<sid>/covers')
    def journal_cover_upload(sid):
        from .people import validated_image
        svc = service()
        sid = svc.source(sid)['id']
        if not svc.can_edit(sid):
            abort(403, '公共期刊演示只供阅读。')
        upload = request.files.get('file')
        if not upload:
            abort(400, '请选择封面图片。')
        content, extension, mime = validated_image(upload)
        fid = uuid.uuid4().hex
        folder = ctx.data_dir / 'journal-covers'
        folder.mkdir(exist_ok=True)
        path = folder / (fid + '.' + extension)
        try:
            path.write_bytes(content)
            with ctx.db():
                ctx.db().execute('INSERT INTO journal_covers VALUES (?,?,?,?,?,?,?,?)', (fid, sid, Path(upload.filename).name, path.name, mime, len(content), hashlib.sha256(content).hexdigest(), now()))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return jsonify(id=fid, name=upload.filename), 201

    @app.get('/api/journals/<sid>/covers/<fid>')
    def journal_cover_read(sid, fid):
        svc = service()
        sid = svc.source(sid)['id']
        row = ctx.db().execute('SELECT * FROM journal_covers WHERE id=? AND source_id=?', (fid, sid)).fetchone()
        if not row:
            abort(404)
        return send_file(ctx.data_dir / 'journal-covers' / row['stored_name'], mimetype=row['mime_type'], download_name=row['name'])

    @app.get('/api/journals/<sid>/cover-attachments/<aid>')
    def journal_cover_attachment(sid, aid):
        svc = service()
        sid = svc.source(sid)['id']
        if not ctx.db().execute("SELECT 1 FROM journal_archive_history WHERE source_id=? AND json_extract(snapshot_json,'$.cover.attachment_id')=? LIMIT 1", (sid, aid)).fetchone():
            abort(404, '没有本期刊的封面附件依据。')
        attached = ctx.db().execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
        if not attached:
            abort(404)
        svc.records.get(attached['record_id'])
        from .attachment_search import original_path
        path = original_path(ctx.data_dir, attached)
        if path is None:
            abort(404, '封面附件文件缺失。')
        return send_file(path, as_attachment=True, download_name=attached['name'])
