"""Local research collections, member administration and permission-aware export."""
import hashlib
import base64
import html
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from flask import abort, jsonify, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import workflow, identity, content_export, bylines, affiliations, reading, reviews, collection_scope, saved_searches
from .store import now, save_revision

COLLECTION_FIELDS = ["name", "description", "visibility", "research_question", "comparison_html", "comparison_text", "stage_judgment"]


def collection_values(data, base=None):
    values = {}
    for key in COLLECTION_FIELDS:
        value = data.get(key, base[key] if base else "")
        if not isinstance(value, str) or len(value) > (500000 if key.startswith("comparison_") else 40000):
            abort(400, "资料夹字段格式不正确或内容过长。")
        values[key] = value.strip()
    if not values["name"] or values["visibility"] not in {"private", "shared"}:
        abort(400, "请填写资料夹名称并选择共享范围。")
    try:
        values["comparison_html"], values["comparison_text"] = workflow.clean_rich(values["comparison_html"])
    except ValueError as error:
        abort(400, str(error))
    log = data.get("scope_log", data.get("scope_log_json", base["scope_log_json"] if base else []))
    if isinstance(log, str):
        try:
            log = json.loads(log)
        except ValueError:
            abort(400, "排查日志格式不正确。")
    values["scope_log_json"] = json.dumps(collection_scope.search_log(log), ensure_ascii=False)
    if len(values["scope_log_json"]) > 500000:
        abort(400, "排查日志内容过长。")
    return values


def password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 200:
        abort(400, "密码需要 12—200 个字符。")
    return generate_password_hash(value)


def register(app, ctx):
    db, user, body = ctx.db, ctx.user, ctx.body

    @app.get("/api/collections/<cid>")
    def collection_detail(cid):
        row = ctx.get_collection(cid)
        items = [{**ctx.record_summary(r), "disposition": r["disposition"], "rationale": r["rationale"]} for r in db().execute("SELECT r.*,i.disposition,i.rationale FROM records r JOIN collection_items i ON i.record_id=r.id WHERE i.collection_id=? AND r.merged_into IS NULL ORDER BY r.updated_at DESC", (cid,)) if ctx.visible(r)]
        return jsonify(**dict(row), scope_log=json.loads(row["scope_log_json"]), items=[r for r in items if r["disposition"] == "included"], excluded_items=[r for r in items if r["disposition"] == "excluded"], can_edit=True, can_manage_visibility=row["owner_id"] == user()["id"])

    @app.put("/api/collections/<cid>")
    def edit_collection(cid):
        db().execute("BEGIN IMMEDIATE")
        row, data = ctx.get_collection(cid, edit=True), body()
        ctx.check_version(data, row)
        values = collection_values(data, row)
        if values["visibility"] != row["visibility"] and row["owner_id"] != user()["id"]:
            abort(403, "只有资料夹创建者可以调整可见范围。")
        with db():
            if not db().execute("SELECT 1 FROM revisions WHERE target_type='collection' AND target_id=?", (cid,)).fetchone():
                save_revision(db(), "collection", cid, "资料夹修订前版本", user()["id"])
            values.update(version=row["version"] + 1, updated_at=now())
            db().execute(f"UPDATE collections SET {','.join(k+'=?' for k in values)} WHERE id=?", [*values.values(), cid])
            save_revision(db(), "collection", cid, "修订资料夹及已有内容", user()["id"])
        return jsonify(id=cid)

    @app.get("/api/collections/<cid>/history")
    def collection_history(cid):
        ctx.get_collection(cid)
        rows = db().execute("SELECT r.*,u.name AS actor_name FROM revisions r JOIN users u ON u.id=r.actor_id WHERE target_type='collection' AND target_id=? ORDER BY r.id DESC", (cid,))
        return jsonify(items=[{"id": r["id"], "version": json.loads(r["snapshot_json"])["version"], "actor_name": r["actor_name"], "created_at": r["created_at"], "action": r["action"]} for r in rows])

    @app.post("/api/collections/<cid>/restore/<int:revision_id>")
    def restore_collection(cid, revision_id):
        db().execute("BEGIN IMMEDIATE")
        row, data = ctx.get_collection(cid, edit=True), body()
        ctx.check_version(data, row)
        revision = db().execute("SELECT * FROM revisions WHERE id=? AND target_type='collection' AND target_id=?", (revision_id, cid)).fetchone()
        if not revision:
            abort(404)
        snapshot = json.loads(revision["snapshot_json"])
        snapshot["visibility"] = row["visibility"]
        snapshot.setdefault("scope_log_json", "[]")
        values = collection_values(snapshot, row)
        records = {}
        for item in snapshot.get("item_details", [{"record_id": rid} for rid in snapshot.get("item_ids", [])]):
            rid = ctx.get_record(item["record_id"])["id"]
            decision = collection_scope.decision(item)
            if rid in records and records[rid] != decision:
                abort(409, "历史资料夹条目已合并，但纳入／排除理由不同，请先人工整理。")
            records[rid] = decision
        with db():
            values.update(version=row["version"] + 1, updated_at=now())
            db().execute(f"UPDATE collections SET {','.join(k+'=?' for k in values)} WHERE id=?", [*values.values(), cid])
            db().execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
            db().executemany("INSERT INTO collection_items(collection_id,record_id,disposition,rationale) VALUES (?,?,?,?)", [(cid, rid, *decision) for rid, decision in records.items()])
            save_revision(db(), "collection", cid, "恢复资料夹版本 " + str(snapshot["version"]), user()["id"])
        return jsonify(id=cid)

    @app.get("/api/members")
    def members():
        ctx.admin()
        return jsonify(items=[dict(r) for r in db().execute("SELECT id,username,name,role,active FROM users WHERE role<>'system' ORDER BY active DESC,name")])

    @app.post("/api/members")
    def new_member():
        ctx.admin()
        db().execute("BEGIN IMMEDIATE")
        ctx.admin()
        data = body()
        username, name, role = data.get("username", ""), data.get("name", ""), data.get("role", "researcher")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username) or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or role not in {"admin", "researcher"}:
            abort(400, "请填写姓名、3—64 位字母数字账号及有效角色。")
        if db().execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            abort(409, "账号已存在。")
        hashed = password(data.get("password"))
        uid = "member-" + uuid.uuid4().hex[:12]
        with db():
            db().execute("INSERT INTO users(id,username,name,password_hash,role) VALUES (?,?,?,?,?)", (uid, username, name.strip(), hashed, role))
            db().execute("INSERT INTO member_events(actor_id,member_id,action,created_at) VALUES (?,?,?,?)", (user()["id"], uid, "创建成员", now()))
        return jsonify(id=uid), 201

    @app.put("/api/members/<uid>")
    def edit_member(uid):
        ctx.admin()
        actor = user()["id"]
        db().execute("BEGIN IMMEDIATE")
        ctx.admin()
        row, data = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(), body()
        if not row:
            abort(404)
        if row['role'] == 'system':
            abort(403,'系统处理主体不属于成员账号，不能启用、重置或改写。')
        values = {}
        for key in ["name", "role", "active"]:
            if key in data:
                values[key] = data[key]
        if "name" in values and (not isinstance(values["name"], str) or not 1 <= len(values["name"].strip()) <= 100):
            abort(400, "姓名格式不正确。")
        if "role" in values and values["role"] not in {"admin", "researcher"}:
            abort(400, "角色不正确。")
        if "active" in values and type(values["active"]) is not bool:
            abort(400, "请指定是否启用。")
        if row["active"] and row["role"] == "admin" and (not values.get("active", True) or values.get("role", row["role"]) != "admin"):
            if db().execute("SELECT count(*) FROM users WHERE active=1 AND role='admin'").fetchone()[0] <= 1:
                abort(409, "必须保留至少一位有效管理员。")
        if "password" in data:
            values["password_hash"] = password(data["password"])
        if not values:
            abort(400, "没有要修改的成员信息。")
        if any(key in values for key in ["active", "role", "password_hash"]):
            values["credential_version"] = row["credential_version"] + 1
        with db():
            db().execute(f"UPDATE users SET {','.join(key+'=?' for key in values)} WHERE id=?", [*values.values(), uid])
            action = "重置凭据" if "password_hash" in values else "停用成员" if values.get("active") is False else "维护成员信息"
            db().execute("INSERT INTO member_events(actor_id,member_id,action,created_at) VALUES (?,?,?,?)", (actor, uid, action, now()))
        return jsonify(id=uid, reauthenticate=uid == actor and "credential_version" in values)

    @app.post("/api/account/password")
    def own_password():
        db().execute("BEGIN IMMEDIATE")
        uid, data = user()["id"], body()
        row = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        old = data.get("old_password", "")
        if not isinstance(old, str) or not check_password_hash(row["password_hash"], old):
            abort(403, "当前密码不正确。")
        hashed = password(data.get("new_password"))
        with db():
            db().execute("UPDATE users SET password_hash=?,credential_version=credential_version+1 WHERE id=?", (hashed, uid))
            db().execute("INSERT INTO member_events(actor_id,member_id,action,created_at) VALUES (?,?,?,?)", (uid, uid, "本人修改密码", now()))
        session["credential_version"] = row["credential_version"] + 1
        return jsonify(ok=True)

    @app.get("/api/export/content")
    def export_content():
        selected, _ = ctx.filtered_records(request.args)
        people, associated = [], set()
        if "person" in request.args:
            person, selected_ids, associated = content_export.person_scope(ctx, request.args["person"])
            people.append(person)
            selected = [row for row in selected if row["id"] in selected_ids]
        # Include accessible referenced evidence and originals so local links remain useful.
        export_args = saved_searches.resolve(db(), user()["id"], request.args)
        scope_id = export_args.get("collection")
        exclusions = []
        if scope_id:
            ctx.get_collection(scope_id)
            exclusions = [r["id"] for r in db().execute("SELECT r.* FROM records r JOIN collection_items i ON r.id=i.record_id WHERE i.collection_id=? AND i.disposition='excluded' AND r.merged_into IS NULL", (scope_id,)) if ctx.visible(r)]
        records, pending = {}, [r["id"] for r in selected] + sorted(associated) + exclusions
        while pending:
            rid = pending.pop()
            if rid in records:
                continue
            item = content_export.record_projection(db(), ctx.record_detail(rid).get_json(), ctx.visible)
            if item["kind"] not in workflow.CONTENT_KINDS:
                item["bylines"] = bylines.Bylines(db(), user(), ctx.records()).detail(item["id"])
                item["affiliations"] = affiliations.ArticleAffiliations(db(), user(), ctx.records()).detail(item["id"])
            records[item["id"]] = item
            pending.extend(r["id"] for r in item["linked_records"] if r["id"] not in records)
            pending.extend(c["excerpt_id"] for c in item["evidence_citations"] if c["excerpt_id"] not in records)
            for citation in item["evidence_citations"]:
                if citation["snapshot"].get("evidence_record_id"):
                    pending.append(ctx.get_record(citation["snapshot"]["evidence_record_id"])["id"])
            if item["evidence_record_id"]:
                pending.append(ctx.get_record(item["evidence_record_id"])["id"])
        collections = []
        for row in db().execute("SELECT * FROM collections"):
            if row["visibility"] == "private" and row["owner_id"] != user()["id"]:
                continue
            item = dict(row)
            item["item_details"] = [dict(r) for r in db().execute("SELECT record_id,disposition,rationale FROM collection_items WHERE collection_id=? ORDER BY record_id", (row["id"],)) if r["record_id"] in records]
            item["item_ids"] = [r["record_id"] for r in item["item_details"]]
            item["scope_log"] = json.loads(item["scope_log_json"])
            if item["item_ids"] or scope_id == row["id"] or not export_args:
                collections.append(item)
        relevant_sources = content_export.source_ids(people, records) if people else None
        sources = [{key: value for key, value in dict(r).items() if key != "raw_json"}
                   for r in db().execute("SELECT * FROM sources WHERE merged_into IS NULL")
                   if relevant_sources is None or r["id"] in relevant_sources]
        for source in sources:
            source.update(reviews.summary(db(), "source", source["id"]))
        paths = {rid: "records/" + hashlib.sha256(rid.encode()).hexdigest()[:20] + ".html" for rid in records}
        source_paths = {s["id"]: "sources/" + hashlib.sha256(s["id"].encode()).hexdigest()[:20] + ".html" for s in sources}
        for rid, item in records.items():
            item["path"] = paths[rid]
        attachments = {}
        for item in records.values():
            aids = [a["id"] for a in item["attachments"]]
            if item["evidence_attachment_id"]:
                aids.append(item["evidence_attachment_id"])
            for citation in item["evidence_citations"]:
                if citation["snapshot"].get("evidence_attachment_id"):
                    aids.append(citation["snapshot"]["evidence_attachment_id"])
            for aid in aids:
                a = db().execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
                if a:
                    original = identity.resolve(db(), "records", a["record_id"])
                    if original and ctx.visible(original):
                        attachments[aid] = {**dict(a), "path": "attachments/" + a["stored_name"]}
        avatars = content_export.prepare_people(db(), people)
        from . import topic_finals
        final_files = topic_finals.prepare_export(db(), records)
        from . import journal_collaboration
        journal_works = journal_collaboration.export_projection(db(),ctx.records(),set(records))
        payload = {"format": "research-content-v1", "exported_at": now(), "selected_ids": [r["id"] for r in selected],
                   "records": list(records.values()), "sources": sources, "collections": collections, "attachments": list(attachments.values()),
                   "people": people, "avatars": list(avatars.values()), "journal_works": journal_works}
        coverage = content_export.evidence_coverage(records, attachments, sources)
        output = io.BytesIO()
        style = "body{font:16px/1.7 system-ui,sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#202f42}a{color:#234e78}pre{font:inherit;white-space:pre-wrap}section{margin:28px 0}"
        style += (Path(app.static_folder) / "reading.css").read_text(encoding="utf-8")

        def page(title, content):
            # Presentation wrappers belong only to the export, never to stored content.
            content = re.sub(r"<table\b[^>]*>", lambda match: '<div class="reading-table" role="region" aria-label="内容表格" tabindex="0">' + match.group(), content, flags=re.I)
            content = re.sub(r"</table\s*>", "</table></div>", content, flags=re.I)
            return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + html.escape(title) + '</title><style>' + style + '</style><body class="reading-content"><h1>' + html.escape(title) + '</h1>' + content + '</body></html>'

        def prose(label, value):
            return "<section><h2>" + html.escape(label) + "</h2><pre>" + html.escape(str(value or "")) + "</pre></section>" if value else ""

        def original_snapshot(snapshot):
            if not snapshot:
                return ""
            fields = [("title", "题名"), ("original_title", "原题名"), ("authors", "署名"), ("published_on", "日期"), ("id", "编号"), ("version", "版本"), ("url", "原文链接"), ("doi", "DOI")]
            details = "\n".join(label + "：" + str(snapshot[key]) for key, label in fields if snapshot.get(key) not in (None, ""))
            from .attachment_anchor import description as anchor_description
            details += "\n\n" + anchor_description(snapshot.get("attachment_anchor"))
            return '<section><h2>引用时的原始资料快照</h2><pre>' + html.escape(details) + '</pre>' + (snapshot.get("body_html") or "") + prose("原摘要", snapshot.get("abstract")) + '</section>'

        scope_html = ""
        outcomes = {"found": "找到结果", "zero_results": "无结果", "access_blocked": "访问受阻"}
        for collection in collections:
            scope_html += "<section><h2>专题：" + html.escape(collection["name"]) + "</h2>"
            for disposition, label in [("included", "已纳入"), ("excluded", "已排查并排除")]:
                scope_html += "<h3>" + label + "</h3><ul>"
                for entry in collection["item_details"]:
                    if entry["disposition"] == disposition:
                        rid = entry["record_id"]
                        scope_html += '<li><a href="' + paths[rid] + '">' + html.escape(records[rid]["title"]) + '</a>' + ("；理由：" + html.escape(entry["rationale"]) if entry["rationale"] else "") + "</li>"
                scope_html += "</ul>"
            scope_html += "<h3>检索覆盖日志</h3>"
            if not collection["scope_log"]:
                scope_html += "<p>未登记检索。</p>"
            for entry in collection["scope_log"]:
                scope_html += prose(outcomes[entry["outcome"]], "\n".join(label + "：" + entry[key] for key, label in [("source", "来源"), ("query", "检索词"), ("time_range", "时间范围"), ("language", "语种"), ("searched_on", "实际检索日期"), ("notes", "说明")]))
            scope_html += "</section>"

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("evidence-coverage.json", json.dumps(coverage, ensure_ascii=False, indent=2))
            archive.writestr("review.html", page("研究复核与证据留存范围", content_export.coverage_html(coverage) + scope_html))
            archive.writestr("content.json", json.dumps(payload, ensure_ascii=False, indent=2))
            index = "<p>包括当前可见正文、附件、来源、专题和引用时的证据快照。账户凭据不在此导出中；全部历史的系统恢复使用完整备份。</p><ul>"
            index = '<p><a href="review.html">研究复核与证据留存范围</a></p>' + index
            for person in people:
                index += '<li><a href="' + person["path"] + '">人物档案：' + html.escape(person["name"]) + '</a></li>'
                archive.writestr(person["path"], page(person["name"], content_export.person_html(person, prose, paths, source_paths)))
            for item in records.values():
                rid = item["id"]
                index += '<li><a href="' + paths[rid] + '">' + html.escape(item["title"]) + "</a></li>"
                content = '<p><a href="../index.html">返回目录</a></p>' + prose("出版题录", reading.citation(item)) + prose("身份与出处", f"编号：{rid}\n署名：{item['authors']}\n日期：{item['published_on']}\n版本：{item['version']}\n覆盖范围：{item['coverage']}\n原目录出处：{item['original_catalogue']}\n原文链接：{item['url']}")
                content += reviews.html(item)
                for work in item.get("collaboration_works", []):
                    content += prose("编译工作与采用依据", json.dumps(work, ensure_ascii=False, indent=2))
                    content += '<p><a href="../' + html.escape(work["path"]) + '">已留档原件：' + html.escape(work["name"]) + '</a></p>'
                    for adopted in work.get("adoptions", []):
                        content += '<p><a href="../' + html.escape(adopted["path"]) + '">采用定稿 v' + str(adopted["version"]) + '：' + html.escape(adopted["name"]) + '</a></p>'
                content += prose("当前阅读题名（" + {'human':'人工中文','machine':'机器中文，未人工校订','original':'原始信息'}.get(item.get('translation_origin'), '原始信息') + "）", item.get('display_title'))
                preview = item.get('preview_excerpt', {})
                content += prose('历史机器节选说明', preview.get('notice'))
                suffix = '节选' if preview.get('abstract_mode') == 'excerpt' else ''
                content += prose("当前阅读摘要" + (suffix if item.get('translation_origin') != 'human' else ''), item.get('display_abstract'))
                content += prose("人工中文题名", item.get("chinese_title")) + prose("人工中文摘要", item.get("chinese_abstract"))
                content += prose("机器译文版本、原文输入与出处（非核对结论）", json.dumps(item.get("translations", []), ensure_ascii=False, indent=2) if item.get("translations") else "")
                content += prose("人工中文修订历史", json.dumps(item.get("translation_history", []), ensure_ascii=False, indent=2) if item.get("translation_history") else "")
                content += prose('机器概述（非原摘要，未人工核对）', item.get('machine_summary',{}).get('summary','') if item.get('machine_summary') else '')
                content += prose('机器概述原文与定位、分类及处理版本',json.dumps({k:item[k] for k in ['machine_summary_basis','machine_classification','automatic_tasks'] if item.get(k)},ensure_ascii=False,indent=2) if item.get('automatic_tasks') else '')
                content += prose("原摘要节选" if suffix else "摘要与说明", item["abstract"]) + "<section><h2>正文</h2>" + item["body_html"] + "</section>"
                if item.get("intake_evidence"):
                    content += prose("辅助录入取得依据（题录，非全文或核对结论）", json.dumps(item["intake_evidence"], ensure_ascii=False, indent=2))
                if item.get("ris_evidence"):
                    content += prose("RIS 交换依据（仅本条题录，非全文或核对结论）", json.dumps(item["ris_evidence"], ensure_ascii=False, indent=2))
                if item.get("discovery_evidence"):
                    content += prose("来源发现依据（公开描述非已核实摘要）", json.dumps(item["discovery_evidence"], ensure_ascii=False, indent=2))
                if item.get('automatic_acquisition'):
                    content += prose('自动取得状态','系统处理，未人工核对；中文待处理；网页说明与作品实质正文分别保留。')
                    for snapshot in item['automatic_acquisition']['snapshots']:
                        if snapshot['path'] not in archive.namelist():
                            archive.writestr(snapshot['path'],base64.b64decode(snapshot['raw_base64']))
                        content += prose('网页说明快照（未验证作品全文）',snapshot['page_text'])
                        content += prose('快照出处与版本',snapshot['url']+'\n'+snapshot['retrieved_at']+'\nSHA256: '+snapshot['sha256']+'\n'+snapshot['reason'])
                        content += '<p>原始响应字节：'+html.escape(snapshot['path'])+'（仅供下载核对，含未执行的原站代码）</p>'
                content += content_export.record_relations_html(item, prose, source_paths, people)
                for key, label in [("quote", "原文摘录"), ("translation", "译文"), ("interpretation", "研究员说明"), ("locator", "原文定位")]:
                    content += prose(label, item[key])
                content += original_snapshot(item["evidence_snapshot"])
                for a in item["attachments"]:
                    if a["id"] in attachments:
                        content += '<p><a href="../attachments/' + attachments[a["id"]]["stored_name"] + '">' + html.escape(a["name"]) + '</a></p>'
                if item["evidence_attachment_id"] in attachments:
                    attached = attachments[item["evidence_attachment_id"]]
                    content += '<p><a href="../attachments/' + attached["stored_name"] + '">引用时附件：' + html.escape(attached["name"]) + '</a></p>'
                from .evidence import citation_description, citation_scope_notice, STANCE_LABELS
                content += prose("引用登记范围", citation_scope_notice(item["evidence_citations"]))
                previous_stance = None
                for citation in sorted(item["evidence_citations"], key=lambda c: list(STANCE_LABELS).index(c["stance"])):
                    if citation["stance"] != previous_stance:
                        content += "<h2>引用用途：" + STANCE_LABELS[citation["stance"]] + "</h2>"
                        previous_stance = citation["stance"]
                    snap = citation["snapshot"]
                    content += '<section><h2>引用证据 · 版本 ' + str(citation["excerpt_version"]) + '</h2>'
                    content += prose("引用用途与变化提示（导出时）", citation_description(citation))
                    content += prose("笔记题名", snap.get("title")) + (snap.get("body_html") or "")
                    content += prose("摘录／译文／说明／定位", "\n\n".join(str(snap.get(k, "")) for k in ["quote", "translation", "interpretation", "locator"]))
                    content += original_snapshot(json.loads(snap.get("evidence_snapshot_json") or "{}"))
                    if citation["excerpt_id"] in paths:
                        content += '<a href="../' + paths[citation["excerpt_id"]] + '">返回证据笔记</a>'
                    if snap.get("evidence_record_id"):
                        original_id = ctx.get_record(snap["evidence_record_id"])["id"]
                        if original_id in paths:
                            content += '<p><a href="../' + paths[original_id] + '">查看当前原文（非引用时正文）</a></p>'
                    if snap.get("evidence_attachment_id") in attachments:
                        attached = attachments[snap["evidence_attachment_id"]]
                        content += '<p><a href="../attachments/' + attached["stored_name"] + '">采用版本的原文附件：' + html.escape(attached["name"]) + '</a></p>'
                    content += "</section>"
                for original in item["linked_records"]:
                    if original["id"] in paths:
                        content += '<p><a href="../' + paths[original["id"]] + '">原文：' + html.escape(original["title"]) + '</a></p>'
                if item["evidence_record_id"]:
                    original_id = ctx.get_record(item["evidence_record_id"])["id"]
                    if original_id in paths:
                        content += '<p><a href="../' + paths[original_id] + '">返回摘录对应原文</a> · 引用原文版本 ' + str(item["evidence_version"]) + '</p>'
                for sid in set(item["related_source_ids"] + [item["source_id"], item["serial_id"]]):
                    if sid in source_paths:
                        content += '<p><a href="../' + source_paths[sid] + '">查看关联来源：' + html.escape(next(s["name"] for s in sources if s["id"] == sid)) + '</a></p>'
                archive.writestr(paths[rid], page(item["title"], content))
            index += "</ul>"
            if journal_works:
                index += '<h2>期刊编译工作及全部原件版本</h2><ul>'
                for work in journal_works:
                    index += '<li><a href="'+work['path']+'">'+html.escape(work['journal_name']+' · '+work['coverage'])+'</a></li>'
                    archive.writestr(work['path'],page(work['journal_name'],journal_collaboration.export_html(work)))
                index += '</ul>'
                journal_collaboration.write_export_files(archive,ctx.data_dir,db(),journal_works)
            index += "<h2>来源介绍与登记</h2><ul>"
            for source in sources:
                index += '<li><a href="' + source_paths[source["id"]] + '">' + html.escape(source["name"]) + '</a></li>'
                content = '<p><a href="../index.html">返回目录</a></p>' + source["introduction_html"]
                content += reviews.html(source)
                for key, label in [("id", "稳定编号"), ("original_name", "原名"), ("aliases", "别名"), ("website", "官网"), ("notes", "原始备注"), ("country_evidence", "国家依据"), ("host_evidence", "主办依据"), ("international_evidence", "国际定位依据")]:
                    content += prose(label, source[key])
                for item in records.values():
                    if source["id"] in [item["source_id"], item["serial_id"], *item["related_source_ids"]]:
                        content += '<p><a href="../' + paths[item["id"]] + '">' + html.escape(item["title"]) + '</a></p>'
                archive.writestr(source_paths[source["id"]], page(source["name"], content))
            index += "</ul>"
            for collection in collections:
                index += "<section><h2>" + html.escape(collection["name"]) + "</h2>" + prose("研究问题", collection["research_question"]) + collection["comparison_html"] + prose("阶段判断", collection["stage_judgment"]) + "</section>"
            archive.writestr("index.html", page("研究资料内容导出", index + scope_html))
            for group, folder, label in [(attachments, "uploads", "附件"), (avatars, "avatars", "头像"), (final_files, "handoffs", "编译定稿")]:
                for entry in group.values():
                    try:
                        data = (ctx.data_dir / folder / entry["stored_name"]).read_bytes()
                    except OSError:
                        abort(409, label + "文件缺失或不可读，无法完成内容导出。")
                    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                        abort(409, label + "文件与登记信息不一致，无法完成内容导出。")
                    archive.writestr(entry["path"], data)
            manifest = {"format": "research-content-manifest-v1", "files": []}
            for name in archive.namelist():
                data = archive.read(name)
                manifest["files"].append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        output.seek(0)
        return send_file(output, mimetype="application/zip", as_attachment=True, download_name="research-content.zip")
