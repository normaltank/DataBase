"""Canonical current bibliographic fields; raw exchange evidence is never replayed."""
import io
import json
import re

from flask import abort, send_file

from . import workflow


def download(db, rows):
    lines = []

    def tag(key, value):
        # A field is always one tag value, including text pasted with RIS boundaries.
        value = re.sub(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]+', ' ', value or '').strip()
        if value:
            lines.append(key + '  - ' + value)

    for row in rows:
        if row['kind'] in workflow.CONTENT_KINDS or row['kind'] in {'research_note', 'excerpt', 'reading_note'} or row['evidence_record_id']:
            abort(422, '选中项包含不支持 RIS 的研究内容或个人成果，请调整选择；可使用内容包导出。')
        kind = {'journal_article': 'JOUR', 'report': 'RPRT'}.get(row['kind'], 'GEN')
        if row['kind'] == 'other':
            evidence = json.loads(row['raw_json'] or '{}').get('ris_evidence', [])
            if any(item.get('original_type') in {'WEB', 'ELEC'} for item in evidence):
                kind = 'WEB'
        tag('TY', kind)
        tag('TI', row['title'])
        tag('TT', row['chinese_title'])
        if row['original_title'] and row['original_title'] != row['title']:
            tag('N1', 'Original title: ' + row['original_title'])
        authors = [item['raw_name'] for item in db.execute(
            'SELECT raw_name FROM record_bylines WHERE record_id=? AND removed_at IS NULL ORDER BY position,created_at,id', (row['id'],))]
        if not authors or '; '.join(authors) != row['authors']:
            authors = [row['authors']] if row['authors'] else []
        for author in authors:
            tag('AU', author)
        for key, field in [('JF', 'publication_title'), ('PY', 'published_on'), ('VL', 'volume'), ('IS', 'issue'),
                           ('SP', 'pages'), ('DO', 'doi'), ('UR', 'url'), ('AB', 'abstract'), ('LA', 'language')]:
            tag(key, row[field])
        for key, field in [('SN', 'issn'), ('KW', 'keywords')]:
            for value in row[field].split(';'):
                tag(key, value)
        lines.extend(['ER  - ', ''])
    return send_file(io.BytesIO(('\r\n'.join(lines)).encode('utf-8')),
                     mimetype='application/x-research-info-systems; charset=utf-8',
                     as_attachment=True, download_name='research-selected-records.ris')
