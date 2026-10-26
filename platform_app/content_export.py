"""Readable projections and person pages for the shared offline content exporter.

Identity event snapshots remain restore data. Only the member-facing projection
is admitted here; records and files still pass the ordinary reading boundary.
"""
import hashlib
import html
import json
from urllib.parse import urlsplit

from flask import abort

from . import affiliations, identity, note_subjects, person_identity
from .people import PersonProfiles
from .record_revisions import RECORD_FIELDS


def record_projection(db, item, visible):
    fields = {*RECORD_FIELDS, "id", "version", "created_at", "updated_at", "status", "author_name",
              "owner_name", "last_modifier", "related_source_ids", "attachments", "evidence_citations",
              "evidence_snapshot", "evidence_version", "linked_records", "cited_by", "excerpts", "previous_ids", "research_subjects", "intake_evidence"}
    result = identity.readable_record(db, {key: value for key, value in item.items() if key in fields}, visible)
    result.pop("evidence_snapshot_json", None)
    for key in ["linked_records", "cited_by", "excerpts"]:
        result[key] = [identity.readable_record(db, row, visible) for row in item[key]]
    return result


def person_scope(ctx, requested_id):
    if not requested_id.strip():
        abort(400, "请选择要导出的人物档案。")
    db, actor, access = ctx.db(), ctx.user(), ctx.records()
    profiles = PersonProfiles(db, actor, ctx.data_dir)
    profile = profiles.detail(requested_id)
    pid = profile["id"]
    service = person_identity.PersonIdentity(db, actor, ctx.data_dir, access, ctx.record_summary)
    relations = service.public_relations(service.state(pid, pid))
    profile["history"] = [{"person_id": old, "items": profiles.history(old)} for old in [pid, *profile["previous_ids"]]]
    profile["identity_history"] = service.history(requested_id)
    profile["employments"] = affiliations.Employments(db, actor).detail(pid)
    profile["employment_history"] = affiliations.Employments(db, actor).history(pid)
    profile["works"] = []
    for work in relations["works"]:
        rows = [row for row in work["bylines"] if row["target_type"] == "person" and row["target_id"] == pid
                and row["status"] == "confirmed" and not row["removed_at"]]
        if rows:
            profile["works"].append({**work, "bylines": rows})
    profile["research_notes"], profile["research_notes_pending"] = [], []
    for note in relations["notes"]:
        subjects = note_subjects.read(db, note["id"], access.visible)
        for status, key in [("confirmed", "research_notes"), ("needs_review", "research_notes_pending")]:
            rows = [row for row in subjects if row["subject_type"] == "person" and row["subject_id"] == pid and row["status"] == status]
            if rows:
                profile[key].append({**note, "subjects": rows})
    profile["relationship_history"] = relations
    selected = {row["id"] for key in ["works", "research_notes", "research_notes_pending"] for row in profile[key]}
    related = set(selected)
    for group in [relations, *(event["relationships"] for event in profile["identity_history"])]:
        related.update(row["id"] for key in ["works", "notes"] for row in group[key])
        related.update(row["record"]["id"] for row in group["affiliations"])
    return profile, selected, related


def source_ids(people, records):
    found = set()
    for record in records.values():
        found.update([record["source_id"], record["serial_id"], *record["related_source_ids"]])
        found.update(row["subject_id"] for row in record.get("research_subjects", []) if row["subject_type"] != "person")
        found.update(row["target_id"] for row in record.get("bylines", {}).get("items", []) if row["target_type"] == "institution")
        found.update(row["institution_id"] for row in record.get("affiliations", {}).get("items", []))
    for person in people:
        groups = [person["relationship_history"], *(event["relationships"] for event in person["identity_history"])]
        for group in groups:
            found.update(row["institution_id"] for row in group["employments"] + group["affiliations"])
            found.update(row["subject_id"] for note in group["notes"] for row in note["subjects"] if row["subject_type"] != "person")
    return found


def prepare_people(db, people):
    """Assign local paths to public current/historical avatars, and return files."""
    avatars = {}

    def local_avatar(profile):
        avatar = profile.get("avatar")
        if not avatar:
            return
        row = dict(db.execute("SELECT * FROM person_avatars WHERE id=?", (avatar["id"],)).fetchone())
        path = "avatars/" + row["stored_name"]
        profile["avatar"] = {key: value for key, value in avatar.items() if key != "url"}
        profile["avatar"]["path"] = path
        avatars[row["id"]] = {**row, "path": path}

    for person in people:
        person["path"] = "people/" + hashlib.sha256(person["id"].encode()).hexdigest()[:20] + ".html"
        local_avatar(person)
        for history in person["history"]:
            for revision in history["items"]:
                local_avatar(revision["snapshot"])
        for event in person["identity_history"]:
            for profile in event["people_before"]:
                local_avatar(profile)
    return avatars


def person_html(person, prose, paths, source_paths):
    def link(rid, label, mapping=paths):
        return ('<a href="../' + mapping[rid] + '">' + html.escape(label) + '</a>') if rid in mapping else html.escape(label)

    def image(profile):
        avatar = profile.get("avatar")
        return ('<img class="person-avatar" width="160" height="160" alt="人物头像" src="../' + avatar["path"] + '">' +
                prose("头像来源", profile.get("avatar_source"))) if avatar else "<p>未登记头像。</p>"

    def relationships(group):
        content = ""
        for work in group["works"]:
            content += "<section><h3>" + link(work["id"], work["title"]) + "</h3>"
            for row in work["bylines"]:
                status = "已移除" if row["removed_at"] else "已确认" if row["status"] == "confirmed" else "待确认"
                content += prose("作品署名 · " + status, f"{row['raw_name']} · 顺序 {row['position']}\n关系编号：{row['id']} · 版本 {row['version']}\n依据：{row['evidence']}\n当前人物／机构：{(row.get('target') or {}).get('name', row['target_id'] or '未选择')} · {row['target_id'] or ''}")
            content += "</section>"
        for note in group["notes"]:
            content += "<section><h3>" + link(note["id"], note["title"]) + "</h3>"
            for row in note["subjects"]:
                status = {"confirmed": "已确认", "needs_review": "研究对象待复核", "removed": "已移除"}[row["status"]]
                text = f"{row['subject_name']} · {status}\n研究对象编号：{row['subject_id']}\n关系编号：{row['id']} · 版本 {row['version']}\n原研究对象：{row.get('original_subject_name', row['original_subject_id'])}"
                if row.get("identity_change"):
                    text += "\n身份更正依据：" + row["identity_change"]["evidence"]
                content += prose("笔记研究对象", text)
            content += "</section>"
        for row in group["employments"]:
            content += '<section><h3>' + link(row["institution_id"], row["institution"]["name"], source_paths) + '</h3>'
            content += prose("任职经历" + (" · 已移除" if row["removed_at"] else ""), f"人物：{row['person']['name']} · {row['person_id']}\n{row['role']} · {row['start_date'] or '起始不详'} 至 {row['end_date'] or '结束不详'}\n依据：{row['evidence']}\n关系编号：{row['id']} · 版本 {row['version']}") + '</section>'
        for row in group.get("affiliations", []):
            content += prose("文章署名单位" + (" · 已移除" if row["removed_at"] else ""), f"{row['byline']['raw_name']} · {row['institution']['name']}\n作品：{row['record']['title']}\n依据：{row['evidence']}")
        return content

    content = '<p><a href="../index.html">返回目录</a></p>' + image(person)
    content += prose("姓名写法与身份", f"原名：{person['original_name']}\n中文名：{person['chinese_name']}\n其他写法：{person['aliases']}\n稳定编号：{person['id']} · 版本 {person['version']}")
    if person["requested_id"] != person["id"]:
        content += prose("旧入口去向", person["requested_id"] + " 已合并至 " + person["id"])
    content += '<section><h2>人物介绍</h2>' + person["introduction_html"] + '</section>' + prose("参考出处", person["sources"])
    content += '<h2>当前任职经历</h2>' + relationships({"works": [], "notes": [], "employments": person["employments"]["items"]})
    content += '<h2>已确认作品</h2>' + (relationships({"works": person["works"], "notes": [], "employments": []}) or '<p>暂未关联已确认作品。</p>')
    content += '<h2>已确认研究笔记</h2>' + (relationships({"works": [], "notes": person["research_notes"], "employments": []}) or '<p>暂未关联已确认笔记。</p>')
    if person["research_notes_pending"]:
        content += '<h2>研究对象待复核</h2><p>以下关联保留原对象及更正依据，尚未计入已确认研究笔记。</p>' + relationships({"works": [], "notes": person["research_notes_pending"], "employments": []})
    content += '<h2>关系来历（含已移除及待确认关系）</h2>' + relationships(person["relationship_history"])
    content += '<h2>身份整理历史</h2>'
    for event in person["identity_history"]:
        content += prose("合并" if event["event_type"] == "merge" else "拆回", f"{event['id']} · {event['created_at']} · {event['actor_name']}\n保留人物：{event['keep_id']}\n另一人物：{event['duplicate_id']}\n状态：{event['status']}\n依据：{event['evidence']}")
        for profile in event["people_before"]:
            content += prose("当时人物身份", f"{profile['name']} · {profile['id']} · 版本 {profile['version']}\n{profile['original_name']}\n{profile['chinese_name']}\n{profile['aliases']}") + image(profile)
        content += '<details><summary>当时可读的关系与依据</summary>' + relationships(event["relationships"]) + '</details>'
    content += '<h2>公共档案修改历史</h2>'
    for history in person["history"]:
        for revision in history["items"]:
            profile = revision["snapshot"]
            content += '<details><summary>' + html.escape(f"{profile['name']} · 版本 {revision['version']} · {revision['actor_name']} · {revision['created_at']}") + '</summary>'
            content += prose("维护依据", profile["change_note"]) + prose("姓名写法与出处", '\n'.join(profile[key] for key in ["original_name", "chinese_name", "aliases", "sources"])) + image(profile) + profile["introduction_html"] + '</details>'
    return content


def record_relations_html(item, prose, source_paths, people):
    def target(kind, rid, name):
        paths = {person["id"]: person["path"] for person in people} if kind == "person" else source_paths
        label = '<a href="../' + paths[rid] + '">' + html.escape(name) + '</a>' if rid in paths else html.escape(name)
        return label + (' <small>（' + html.escape(rid) + '）</small>' if rid else '')

    content = ""
    if item.get("bylines", {}).get("items"):
        content += '<section><h2>作品署名关联</h2><table><thead><tr><th>顺序／原始写法</th><th>身份与确认情况</th><th>依据与版本</th></tr></thead><tbody>'
        for row in item["bylines"]["items"]:
            name = row["target"]["name"] if row["target"] else "未指定身份"
            content += '<tr><td>' + html.escape(f"{row['position']} · {row['raw_name']}") + '</td><td>'
            content += target(row["target_type"], row["target_id"], name) + (' · 已确认' if row["status"] == "confirmed" else ' · 待确认') + '</td><td>'
            content += html.escape(f"{row['evidence']}\n{row['id']} · 版本 {row['version']}") + '</td></tr>'
        content += '</tbody></table></section>'
    for row in item.get("affiliations", {}).get("items", []):
        content += '<section><h2>文章署名单位</h2>' + target("institution", row["institution_id"], row["institution"]["name"])
        content += prose("署名与依据", f"{row['byline']['raw_name']}\n依据：{row['evidence']}\n{row['id']} · 版本 {row['version']}") + '</section>'
    if item.get("research_subjects"):
        content += '<section><h2>笔记研究对象</h2>'
        for row in item["research_subjects"]:
            content += '<h3>' + target(row["subject_type"], row["subject_id"], row["subject_name"]) + '</h3>'
            status = "已确认" if row["status"] == "confirmed" else "研究对象待复核"
            text = f"{status} · {row['id']} · 版本 {row['version']}\n原研究对象：{row['original_subject_name']}"
            if row.get("identity_change"):
                text += "\n身份更正依据：" + row["identity_change"]["evidence"]
            content += prose("关系与依据", text)
        content += '</section>'
    return content


def evidence_coverage(records, attachments):
    """Describe only the permission-filtered export projection, never raw history."""
    def retained(snapshot, original):
        aid = snapshot.get('evidence_attachment_id')
        attachment = attachments.get(aid)
        body = bool(original.get('body_html'))
        has_original = bool(original or snapshot.get('evidence_record_id') or snapshot.get('evidence_url') or aid)
        return {
            'original_metadata': bool(original),
            'original_body': body,
            'original_abstract': bool(original.get('abstract')),
            'original_version': snapshot.get('evidence_version'),
            'quote': bool(snapshot.get('quote')),
            'translation': bool(snapshot.get('translation')),
            'interpretation': bool(snapshot.get('interpretation')),
            'locator': snapshot.get('locator') or '',
            'external_url': snapshot.get('evidence_url') or '',
            'attachment': ({'id': aid, 'path': attachment['path']} if attachment else None),
            'notice': (('保存了历史正文；是否为完整原文需人工核实。' if body else '未保存引用时原文正文。')
                      + ('已纳入明确指定的引用附件。' if attachment else '未保存引用时原件附件。')
                      + '当前资料正文及其他附件不代表引用时原件。') if has_original else '未建立固定原文依据；所列内容仅为该笔记的采用版本。',
        }

    rows = []
    for item in records.values():
        row = {'id': item['id'], 'title': item['title'], 'path': item['path'],
               'current': {'version': item['version'], 'metadata': True, 'body': bool(item.get('body_html')),
                           'external_url': item.get('url') or '', 'doi': item.get('doi') or '',
                           'attachments': [{'id': a['id'], 'path': attachments[a['id']]['path']}
                                           for a in item['attachments'] if a['id'] in attachments]},
               'evidence': retained(item, item.get('evidence_snapshot') or {}), 'citations': []}
        if not any(item.get(key) for key in ['evidence_record_id', 'evidence_url', 'evidence_snapshot', 'evidence_attachment_id']):
            row['evidence']['notice'] = ('普通笔记未建立固定原文依据；笔记正文不代表原文固定快照。'
                                         if item['kind'] == 'research_note' else '本条未登记固定原文依据。')
        for citation in item['evidence_citations']:
            snap = citation['snapshot']
            row['citations'].append({'excerpt_id': citation['excerpt_id'], 'excerpt_version': citation['excerpt_version'],
                                    **retained(snap, json.loads(snap.get('evidence_snapshot_json') or '{}'))})
        rows.append(row)
    return {'format': 'research-evidence-coverage-v1', 'records': rows}


def coverage_html(coverage):
    content = '<p><a href="index.html">返回目录</a></p>'
    content += '<p>本清单仅说明本次权限范围内导出的内容，不枚举不可见资料。固定引用与当前资料分别列示；外部链接不表示网页已留存。普通笔记可能没有原文固定快照。</p>'
    content += '<p>manifest.json 的 SHA-256 与字节数仅用于包内一致性核查，不能证明材料真实、作者身份或研究结论成立，也不能证明文件未被连同清单一起重写。可使用由其他可信渠道取得的整个 ZIP SHA-256 另行比对。</p>'
    content += '<p>离线校验：从源码仓库根目录运行 python scripts/verify_content_export.py 导出ZIP路径；可选 --sha256 可信渠道提供的摘要。校验脚本仅读取 ZIP，不解压或执行包内代码。</p>'
    content += '<p><a href="evidence-coverage.json">结构化核查清单</a> · <a href="manifest.json">文件校验清单</a></p>'
    for row in coverage['records']:
        content += '<section><h2><a href="' + row['path'] + '">' + html.escape(row['title']) + '</a></h2>'
        content += '<p>当前资料版本 ' + str(row['current']['version']) + '：含题录；' + ('含网页正文，是否为完整原文需人工核实。' if row['current']['body'] else '无网页正文。') + '</p>'
        url = row['current']['external_url']
        if url:
            try:
                parsed = urlsplit(url)
                linkable = parsed.scheme.lower() in {'http', 'https'} and bool(parsed.netloc)
            except ValueError:
                linkable = False
            label = html.escape(url)
            content += '<p>当前外部链接（不表示网页已留存）：' + ('<a href="' + html.escape(url, quote=True) + '">' + label + '</a>' if linkable else label) + '</p>'
        if row['current']['doi']:
            content += '<p>当前 DOI：' + html.escape(row['current']['doi']) + '</p>'
        for attachment in row['current']['attachments']:
            content += '<p><a href="' + attachment['path'] + '">当前附件</a></p>'
        for label, evidence in [('该条记录的原文依据', row['evidence']), *[('固定采用笔记 ' + c['excerpt_id'] + ' · 版本 ' + str(c['excerpt_version']), c) for c in row['citations']]]:
            content += '<h3>' + html.escape(label) + '</h3><p>' + html.escape(evidence['notice']) + '</p>'
            if evidence['original_version'] is not None:
                content += '<p>所据原文版本：' + html.escape(str(evidence['original_version'])) + '</p>'
            if evidence['locator']:
                content += '<p>原文定位：' + html.escape(evidence['locator']) + '</p>'
            content += '<p>' + '；'.join(label + ('：有' if evidence[key] else '：无') for key, label in [('original_metadata', '原文题录快照'), ('original_body', '历史正文'), ('original_abstract', '历史摘要'), ('quote', '摘录'), ('translation', '译文'), ('interpretation', '研究员解释')]) + '</p>'
            if evidence['attachment']:
                content += '<p><a href="' + evidence['attachment']['path'] + '">明确指定的引用附件</a></p>'
        content += '</section>'
    return content
