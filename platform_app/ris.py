"""Bounded UTF-8 RIS preview and member-bound per-entry provenance.

No resource named by an imported tag is ever opened. Tags and raw entry bytes
remain evidence; only the explicit field map enters the record editor.
"""
import hashlib
import json
import re
from difflib import SequenceMatcher

from flask import abort, current_app, jsonify, request
from itsdangerous import BadSignature, URLSafeSerializer

from . import identity, intake, publication_dates
from .store import now

MAX_BYTES = 1024 * 1024
MAX_ITEMS = 100
TYPES = {'JOUR': 'journal_article', 'RPRT': 'report', 'WEB': 'other', 'ELEC': 'other', 'GEN': 'other'}
MAPPING = {'title': ['TI', 'T1'], 'publication_title': ['JF', 'JO', 'T2'],
           'published_on': ['PY', 'Y1', 'DA'], 'volume': ['VL'], 'issue': ['IS'],
           'doi': ['DO'], 'url': ['UR'], 'abstract': ['AB', 'N2'], 'language': ['LA']}
MAPPED_TAGS = {'TY', 'ER', 'AU', 'A1', 'SP', 'EP', 'SN', 'KW'} | {tag for tags in MAPPING.values() for tag in tags}
TAG = re.compile(r'^([A-Z0-9]{2})  - ?(.*)$')


def _signer():
    return URLSafeSerializer(current_app.secret_key, salt='ris-entry-evidence-v1')


def duplicate_hints(db, access, fields):
    found = intake.duplicates(db, access, fields)
    title = re.sub(r'\s+', ' ', fields.get('title', '')).strip().casefold()
    if title:
        ids = {d['id'] for d in found}
        for row in db.execute('SELECT * FROM records WHERE merged_into IS NULL'):
            candidate = re.sub(r'\s+', ' ', row['title']).strip().casefold()
            similar = title == candidate or (min(len(title), len(candidate)) > 12 and SequenceMatcher(None, title, candidate).ratio() >= .94)
            if access.visible(row) and row['id'] not in ids and similar:
                found.append(dict(id=row['id'], title=row['title'], basis='相近题名，仅为线索'))
    return found


def read_token(token, actor):
    if not isinstance(token, str) or len(token) > 5 * MAX_BYTES:
        abort(400, 'RIS 依据格式不正确，请重新预览。')
    try:
        payload = _signer().loads(token)
    except (BadSignature, ValueError):
        abort(400, 'RIS 依据无效，请重新预览；当前输入可以保留。')
    if not isinstance(payload, dict) or payload.get('actor_id') != actor['id']:
        abort(403, 'RIS 依据不属于当前账号，请重新预览。')
    return payload['evidence']


def saved_record(db, entry_id):
    """Resolve a submitted entry through manual merges, including archived evidence."""
    for row in db.execute('SELECT id,raw_json FROM records'):
        if any(e.get('entry_id') == entry_id for e in json.loads(row['raw_json'] or '{}').get('ris_evidence', [])):
            return identity.resolve(db, 'records', row['id'])
    return None


def _entries(text):
    entries, lines, tags, errors = [], [], [], []
    start = 0
    def finish():
        entries.append((start, ''.join(lines), tags[:], errors[:]))
        if len(entries) > MAX_ITEMS:
            abort(422, 'RIS 文件最多包含 100 条题录。')
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        value = line.rstrip('\r\n')
        match = TAG.fullmatch(value)
        if match and match[1] == 'TY':
            if lines:
                abort(422, '第 %s 行在 ER 之前出现新的 TY，无法可靠分段；请修正文件。' % number)
            start, lines, tags, errors = number, [line], [{'tag': 'TY', 'value': match[2]}], []
        elif lines:
            lines.append(line)
            if match:
                tags.append({'tag': match[1], 'value': match[2]})
                if match[1] == 'ER':
                    if match[2].strip():
                        errors.append('第 %s 行 ER 不应含有值。' % number)
                    finish()
                    lines, tags, errors = [], [], []
            elif not value.strip():
                continue
            elif value[:1].isspace() and tags:
                tags[-1]['value'] += '\n' + value.strip()
            else:
                errors.append('第 %s 行不是有效标签或缩进续行。' % number)
        elif value.strip():
            abort(422, '第 %s 行位于 TY/ER 条目之外，无法可靠分段；请修正后重试。' % number)
    if lines:
        errors.append('文件末尾缺少 ER 结束标签。')
        finish()
    if not entries:
        abort(422, '没有找到 TY/ER 题录条目。')
    return entries


def _map(tags, errors):
    grouped, warnings, fields = {}, [], {}
    for item in tags:
        grouped.setdefault(item['tag'], []).append(item['value'].strip())
    original_type = grouped['TY'][0].upper()
    supported = original_type in TYPES
    if not supported:
        errors.append('未支持 RIS 类型 %s；请跳过本条。' % original_type)
    else:
        fields['kind'] = TYPES[original_type]
    for field, aliases in MAPPING.items():
        available = [(tag, value) for tag in aliases for value in grouped.get(tag, []) if value]
        if available:
            fields[field] = available[0][1]
            if any(value != available[0][1] for _, value in available[1:]):
                warnings.append('%s 按 %s 优先级采用首值；冲突原值保留在依据中。' % (field, '/'.join(aliases)))
    authors = [{'raw_name': t['value'].strip(), 'identifiers': {}, 'affiliations': []}
               for t in tags if t['tag'] in {'AU', 'A1'} and t['value'].strip()]
    if authors:
        fields['authors'] = '; '.join(a['raw_name'] for a in authors)
    if len(authors) > 100:
        errors.append('本条署名超过 100 项，不能完整保存。')
    for field, tag in [('issn', 'SN'), ('keywords', 'KW')]:
        if any(grouped.get(tag, [])):
            fields[field] = '; '.join(v for v in grouped[tag] if v)
    first, last = grouped.get('SP', [''])[0], grouped.get('EP', [''])[0]
    if first or last:
        fields['pages'] = first + ('-' + last if first and last and first != last else '' if first else last)
    for tag, values in grouped.items():
        if len(values) > 1:
            warnings.append('%s 重复 %s 次；原顺序及所有值均保留。' % (tag, len(values)))
    unmapped = sorted(set(grouped) - MAPPED_TAGS)
    if unmapped:
        warnings.append('未映射标签仅保留为原始依据，不执行链接或路径：' + ', '.join(unmapped))
    if original_type in {'WEB', 'ELEC', 'GEN'}:
        warnings.append('原类型 %s 暂存为“其他”，请人工核对外部资料类别。' % original_type)
    if fields.get('doi'):
        normalized = intake.normalize_doi(fields['doi'])
        if normalized:
            fields['doi'] = normalized
        else:
            warnings.append('DOI 无法规范化，请人工核对。')
    if fields.get('url') and not intake.normalize_url(fields['url']):
        warnings.append('UR 不是可保存的 HTTP(S) 网址；原值保留在依据中，请修改后保存。')
        fields.pop('url')
    if fields.get('published_on'):
        original = fields['published_on']
        match = re.fullmatch(r'(\d{4})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?/*', original)
        candidate = match[1] + ''.join('-%02d' % int(v) for v in match.groups()[1:] if v) if match else ''
        if candidate and publication_dates.interval(candidate):
            fields['published_on'] = candidate
        else:
            warnings.append('日期无法解析：%s；请核对并手填，原值保留。' % original)
            fields.pop('published_on')
    if not fields.get('title'):
        warnings.append('缺少题名，请填写后保存。')
    for field, value in fields.items():
        limit = 40000 if field == 'abstract' else 4000
        if len(value) > limit:
            errors.append('%s 超过 %s 字符限制；本条拒绝保存，不截断。' % (field, limit))
    for item in tags:
        if len(item['value']) > (40000 if item['tag'] in {'AB', 'N2'} else 4000):
            errors.append('原始标签 %s 超过字段长度限制。' % item['tag'])
    return original_type, supported, fields, authors, warnings, unmapped


def register(app, ctx):
    @app.post('/api/ris/preview')
    def ris_preview():
        upload = request.files.get('file')
        if not upload:
            abort(400, '请选择 UTF-8 RIS 文件。')
        content = upload.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            abort(422, 'RIS 文件不能超过 1 MiB。')
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            abort(422, 'RIS 文件必须为 UTF-8 编码（可以带 BOM）。')
        if '\x00' in text:
            abort(422, 'RIS 文件含有无效空字符。')
        filename = (upload.filename or 'import.ris').replace('\\', '/').rsplit('/', 1)[-1][:255]
        digest, imported_at, items = hashlib.sha256(content).hexdigest(), now(), []
        for index, (line, raw, tags, errors) in enumerate(_entries(text), 1):
            original_type, supported, fields, authors, warnings, unmapped = _map(tags, errors)
            evidence = dict(format='RIS', version=1, file_name=filename, file_sha256=digest, entry_index=index,
                            raw_entry=raw, tags=tags, original_type=original_type, fields=fields, authors=authors,
                            imported_at=imported_at, warnings=warnings, unmapped_tags=unmapped)
            evidence['requires_date_review'] = any(w.startswith('日期无法解析') for w in warnings)
            # Stable across repeated previews of identical input by this member.
            entry_id = hashlib.sha256(('%s:%s:%s' % (ctx.user()['id'], digest, index)).encode()).hexdigest()
            evidence['entry_id'] = entry_id
            found = duplicate_hints(ctx.db(), ctx.records(), fields)
            items.append(dict(index=index, line=line, type=original_type, supported=supported, errors=errors,
                warnings=warnings, fields=fields, authors=authors, evidence=evidence, duplicates=found,
                candidates=intake.candidates(ctx.db(), ctx.records(), fields, authors, {'issn': fields.get('issn', '').split('; ')}),
                token=_signer().dumps(dict(actor_id=ctx.user()['id'], evidence=evidence)) if not errors else '', file_duplicates=[]))
        for item in items:
            for other in items:
                if item is other:
                    continue
                a, b = item['fields'], other['fields']
                if ((a.get('doi') and a.get('doi') == b.get('doi')) or
                    (intake.normalize_url(a.get('url')) and intake.normalize_url(a.get('url')) == intake.normalize_url(b.get('url'))) or
                    (a.get('title') and a.get('title').casefold() == b.get('title', '').casefold())):
                    item['file_duplicates'].append(other['index'])
        return jsonify(filename=filename, sha256=digest, items=items)

    @app.post('/api/ris/status')
    def ris_status():
        data = ctx.body()
        evidence = read_token(data.get('token'), ctx.user())
        fields = data.get('fields', evidence['fields'])
        if not isinstance(fields, dict) or any(not isinstance(fields.get(k, ''), str) or len(fields.get(k, '')) > 4000 for k in ['doi', 'url', 'title']):
            abort(400, '重复核对字段格式不正确。')
        # An unreadable match is deliberately indistinguishable from absence.
        row = saved_record(ctx.db(), evidence['entry_id'])
        if row is not None and ctx.records().visible(row):
            return jsonify(saved=True, id=row['id'], title=row['title'])
        return jsonify(saved=False, duplicates=duplicate_hints(ctx.db(), ctx.records(), fields))
