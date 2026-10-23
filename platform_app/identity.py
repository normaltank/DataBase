"""Human-confirmed identity merges retain old objects, versions and references."""
import json
import re
import unicodedata
from difflib import SequenceMatcher

from flask import abort, jsonify, request

from . import workflow, source_catalog
from .store import now, save_revision


def resolve(db, table, rid):
    if not isinstance(rid, str):
        abort(400, "编号格式不正确。")
    seen = set()
    while rid and rid not in seen:
        seen.add(rid)
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
        if not row or not row["merged_into"]:
            return row
        rid = row["merged_into"]
    abort(409, "编号转向存在循环，请检查合并记录。")


def origins(db, table, rid):
    found, frontier = {rid}, [rid]
    while frontier:
        current = frontier.pop()
        for row in db.execute(f"SELECT id FROM {table} WHERE merged_into=?", (current,)):
            if row[0] not in found:
                found.add(row[0])
                frontier.append(row[0])
    return sorted(found)


def aliases(*values):
    return "\n".join(dict.fromkeys(line.strip() for value in values for line in str(value or "").splitlines() if line.strip()))


def retained_aliases(db, table, rid, value):
    name, original = ("title", "original_title") if table == "records" else ("name", "original_name")
    values = [value]
    for old in origins(db, table, rid):
        if old == rid:
            continue
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (old,)).fetchone()
        values.extend([old, row[name], row[original], row["aliases"]])
    return aliases(*values)


def normalized(value):
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value or "").casefold())


def register(app, ctx):
    db, user, body = ctx.db, ctx.user, ctx.body

    def pair(data):
        kind = data.get("type")
        if kind not in {"source", "record"}:
            abort(400, "请选择来源或资料。")
        table = "sources" if kind == "source" else "records"
        loader = ctx.get_source if kind == "source" else ctx.get_record
        keep, duplicate = loader(data.get("keep_id", "")), loader(data.get("duplicate_id", ""))
        if keep["id"] == duplicate["id"]:
            abort(400, "两个编号已经指向同一条内容。")
        return kind, table, keep, duplicate

    def permitted(kind, keep, duplicate):
        if kind == "source":
            if user()["role"] != "admin":
                return "来源合并需要资料管理员执行。"
            if keep["kind"] != duplicate["kind"] and not ({keep["kind"], duplicate["kind"]} <= {"think_tank", "institution"}):
                return "对象类型不同，不能合并。"
        else:
            if keep["kind"] != duplicate["kind"]:
                return "资料类型不同，不能合并。"
            if keep["kind"] in workflow.PERSONAL_KINDS:
                if not ctx.editable(keep) or not ctx.editable(duplicate):
                    return "合并个人内容需要两条记录的作者编辑授权。"
            elif user()["role"] != "admin":
                return "公共资料合并需要资料管理员执行。"
            for key in ["visibility", "owner_id", "author_id", "author_confirmed"]:
                if keep[key] != duplicate[key]:
                    return "可见范围、提交责任或作者确认不同，不能安全合并。"
            if set(json.loads(keep["editors"])) != set(json.loads(duplicate["editors"])):
                return "编辑授权不同，不能安全合并。"
            if keep["evidence_record_id"] != duplicate["evidence_record_id"]:
                return "摘录对应的原始资料不同，不能合并。"
        return ""

    def impact(kind, keep, duplicate):
        did = duplicate["id"]
        if kind == "record":
            return {"附件": db().execute("SELECT count(*) FROM attachments WHERE record_id=?", (did,)).fetchone()[0],
                    "收藏": db().execute("SELECT count(*) FROM favorites WHERE record_id=?", (did,)).fetchone()[0],
                    "专题": db().execute("SELECT count(*) FROM collection_items WHERE record_id=?", (did,)).fetchone()[0],
                    "原文引用": db().execute("SELECT count(*) FROM record_links WHERE report_id=? OR original_id=?", (did, did)).fetchone()[0],
                    "证据引用": db().execute("SELECT count(*) FROM evidence_links WHERE report_id=? OR excerpt_id=?", (did, did)).fetchone()[0],
                    "历史": db().execute("SELECT count(*) FROM revisions WHERE target_type='record' AND target_id=?", (did,)).fetchone()[0]}
        return {"关联资料": db().execute("SELECT count(*) FROM records WHERE source_id=? OR serial_id=?", (did, did)).fetchone()[0],
                "一般内容关联": db().execute("SELECT count(*) FROM record_sources WHERE source_id=?", (did,)).fetchone()[0],
                "历史": db().execute("SELECT count(*) FROM revisions WHERE target_type='source' AND target_id=?", (did,)).fetchone()[0],
                "来源关系": sum(did in (str(s["host_id"]) + " " + str(s["publisher_id"]) + " " + s["relationships"]) for s in db().execute("SELECT * FROM sources WHERE merged_into IS NULL"))}

    @app.get("/api/duplicates")
    def candidates():
        kind = request.args.get("type", "record")
        if kind not in {"record", "source"}:
            abort(400)
        table = "records" if kind == "record" else "sources"
        rows = [r for r in db().execute(f"SELECT * FROM {table} WHERE merged_into IS NULL LIMIT 2000") if kind == "source" or ctx.visible(r)]
        title, original = ("title", "original_title") if kind == "record" else ("name", "original_name")
        items = []
        for i, first in enumerate(rows):
            first_names = {normalized(v) for v in [first[title], first[original], *first["aliases"].splitlines()] if v}
            for second in rows[i + 1:]:
                if first["kind"] != second["kind"]:
                    continue
                second_names = {normalized(v) for v in [second[title], second[original], *second["aliases"].splitlines()] if v}
                reason = "名称或别名一致" if first_names & second_names else ""
                identity = ["doi"] if kind == "record" else ["website", "issn"]
                for key in identity:
                    if first[key] and second[key] and normalized(first[key]) == normalized(second[key]):
                        reason = key.upper() + " 一致"
                if not reason and len(first[title]) > 12 and SequenceMatcher(None, normalized(first[title]), normalized(second[title])).ratio() >= .94:
                    reason = "名称高度相似，需人工核对"
                if reason:
                    items.append({"keep": {"id": first["id"], "name": first[title]}, "duplicate": {"id": second["id"], "name": second[title]}, "reason": reason})
                if len(items) >= 100:
                    break
            if len(items) >= 100:
                break
        return jsonify(items=items, scanned=len(rows), limited=len(rows) >= 2000 or len(items) >= 100)

    @app.post("/api/merge/preview")
    def preview():
        kind, table, keep, duplicate = pair(body())
        blocked = permitted(kind, keep, duplicate)
        excluded = {"raw_json", "body_text", "introduction_text", "evidence_snapshot_json", "merged_into"}
        return jsonify(type=kind, keep={k: keep[k] for k in keep.keys() if k not in excluded},
                       duplicate={k: duplicate[k] for k in duplicate.keys() if k not in excluded},
                       allowed=not blocked, blocked_reason=blocked, impact=impact(kind, keep, duplicate),
                       explanation="保留所选主记录的当前内容，补充旧名称与编号线索并转接关联。另一记录原文与历史归档保留；不会把两份正文自动拼接。")

    def move_pair(table, first, second, old, new):
        rows = db().execute(f"SELECT {first},{second} FROM {table} WHERE {first}=? OR {second}=?", (old, old)).fetchall()
        for row in rows:
            a, b = new if row[0] == old else row[0], new if row[1] == old else row[1]
            if table == "record_links" and a == b:
                abort(409, "合并会形成自引用，已阻止。")
            db().execute(f"INSERT OR IGNORE INTO {table}({first},{second}) VALUES (?,?)", (a, b))
        db().execute(f"DELETE FROM {table} WHERE {first}=? OR {second}=?", (old, old))

    def merge_records(keep, duplicate):
        kid, did = keep["id"], duplicate["id"]
        # All citation snapshots must survive; ambiguous collisions are not silently discarded.
        links = db().execute("SELECT * FROM evidence_links WHERE report_id=? OR excerpt_id=?", (did, did)).fetchall()
        for link in links:
            report, excerpt = kid if link["report_id"] == did else link["report_id"], kid if link["excerpt_id"] == did else link["excerpt_id"]
            other = db().execute("SELECT * FROM evidence_links WHERE report_id=? AND excerpt_id=?", (report, excerpt)).fetchone()
            if report == excerpt or (other and (other["snapshot_json"] != link["snapshot_json"] or other["excerpt_version"] != link["excerpt_version"])):
                abort(409, "合并会冲突于不同版本的证据引用，请先人工整理。")
            db().execute("INSERT OR IGNORE INTO evidence_links VALUES (?,?,?,?)", (report, excerpt, link["excerpt_version"], link["snapshot_json"]))
        db().execute("DELETE FROM evidence_links WHERE report_id=? OR excerpt_id=?", (did, did))
        move_pair("record_links", "report_id", "original_id", did, kid)
        for table, owner in [("favorites", "user_id"), ("collection_items", "collection_id"), ("record_sources", "source_id")]:
            db().execute(f"INSERT OR IGNORE INTO {table}({owner},record_id) SELECT {owner},? FROM {table} WHERE record_id=?", (kid, did))
            db().execute(f"DELETE FROM {table} WHERE record_id=?", (did,))
        db().execute("UPDATE attachments SET record_id=? WHERE record_id=?", (kid, did))
        db().execute("UPDATE records SET evidence_record_id=? WHERE evidence_record_id=?", (kid, did))
        attachments = sorted(set(json.loads(keep["attachment_ids"]) + json.loads(duplicate["attachment_ids"])))
        names = aliases(keep["aliases"], duplicate["aliases"], duplicate["title"], duplicate["original_title"], did)
        if len(names) > 4000:
            abort(409, "合并后的别名过长，请先人工整理别名。")
        db().execute("UPDATE records SET attachment_ids=?,aliases=? WHERE id=?", (json.dumps(attachments), names, kid))

    def merge_sources(keep, duplicate):
        kid, did = keep["id"], duplicate["id"]
        names = aliases(keep["aliases"], duplicate["aliases"], duplicate["name"], duplicate["original_name"], did)
        db().execute("UPDATE sources SET aliases=? WHERE id=?", (names, kid))
        outgoing = json.loads(keep["relationships"]) + json.loads(duplicate["relationships"])
        merged_outgoing = []
        for rel in outgoing:
            rel = dict(rel)
            rel["target_id"] = kid if rel["target_id"] == did else rel["target_id"]
            matches = [r for r in merged_outgoing if (r["type"], r["target_id"]) == (rel["type"], rel["target_id"])]
            if matches:
                matches[0]["evidence"] = aliases(matches[0]["evidence"], rel["evidence"])
            else:
                merged_outgoing.append(rel)
        db().execute("UPDATE sources SET relationships=? WHERE id=?", (json.dumps(merged_outgoing, ensure_ascii=False), kid))
        for row in db().execute("SELECT * FROM sources WHERE merged_into IS NULL AND id<>?", (did,)).fetchall():
            values = {}
            for key in ["host_id", "publisher_id"]:
                ids = source_catalog.ids(row[key])
                if did in ids:
                    values[key] = " | ".join(dict.fromkeys(kid if value == did else value for value in ids))
            relations = json.loads(row["relationships"])
            if any(r["target_id"] == did for r in relations):
                remapped = []
                for rel in relations:
                    rel["target_id"] = kid if rel["target_id"] == did else rel["target_id"]
                    match = next((r for r in remapped if (r["type"],r["target_id"]) == (rel["type"],rel["target_id"])), None)
                    if match:
                        match["evidence"] = aliases(match["evidence"],rel["evidence"])
                    else:
                        remapped.append(rel)
                values["relationships"] = json.dumps(remapped, ensure_ascii=False)
            if values:
                db().execute(f"UPDATE sources SET {','.join(k+'=?' for k in values)} WHERE id=?", [*values.values(), row["id"]])
        db().execute("UPDATE sources SET merged_into=? WHERE id=?", (kid, did))
        # Revalidate the complete prospective graph in the same transaction.
        for row in db().execute("SELECT * FROM sources WHERE merged_into IS NULL").fetchall():
            obj = dict(row)
            obj["relationships"] = json.loads(obj["relationships"])
            obj["institution_types"] = json.loads(obj["institution_types"])
            ctx.source_values(obj, row)
        for field in ["source_id", "serial_id"]:
            db().execute(f"UPDATE records SET {field}=? WHERE {field}=?", (kid, did))
        db().execute("INSERT OR IGNORE INTO record_sources(record_id,source_id) SELECT record_id,? FROM record_sources WHERE source_id=?", (kid, did))
        db().execute("DELETE FROM record_sources WHERE source_id=?", (did,))

    @app.post("/api/merge")
    def merge():
        db().execute("BEGIN IMMEDIATE")
        data = body()
        if data.get("confirmed") is not True:
            abort(400, "请先比较影响并确认合并。")
        kind, table, keep, duplicate = pair(data)
        reason = permitted(kind, keep, duplicate)
        if reason:
            abort(403, reason)
        if data.get("keep_version") != keep["version"] or data.get("duplicate_version") != duplicate["version"]:
            abort(409, "记录已改变，请重新比较后再确认。")
        before = {"keep": dict(keep), "duplicate": dict(duplicate), "impact": impact(kind, keep, duplicate)}
        with db():
            # Rewired references receive versions too, so an open form cannot silently undo a merge.
            did = duplicate["id"]
            affected_records, affected_sources = set(), set()
            if kind == "record":
                affected_records.update(r[0] for r in db().execute("SELECT report_id FROM record_links WHERE original_id=?", (did,)))
                affected_records.update(r[0] for r in db().execute("SELECT report_id FROM evidence_links WHERE excerpt_id=?", (did,)))
                affected_records.update(r[0] for r in db().execute("SELECT id FROM records WHERE evidence_record_id=?", (did,)))
            else:
                affected_records.update(r[0] for r in db().execute("SELECT id FROM records WHERE source_id=? OR serial_id=?", (did, did)))
                affected_records.update(r[0] for r in db().execute("SELECT record_id FROM record_sources WHERE source_id=?", (did,)))
                affected_sources.update(s["id"] for s in db().execute("SELECT * FROM sources WHERE merged_into IS NULL") if did in source_catalog.ids(s["host_id"]) + source_catalog.ids(s["publisher_id"]) or any(r["target_id"] == did for r in json.loads(s["relationships"])))
            if kind == "record":
                affected_records -= {keep["id"], did}
            else:
                affected_sources -= {keep["id"], did}
            for affected_kind, ids in [("record", affected_records), ("source", affected_sources)]:
                for aid in ids:
                    save_revision(db(), affected_kind, aid, "合并转接前版本", user()["id"])
            for row in [keep, duplicate]:
                save_revision(db(), kind, row["id"], "人工合并前快照", user()["id"])
            if kind == "record":
                merge_records(keep, duplicate)
            else:
                merge_sources(keep, duplicate)
            db().execute(f"UPDATE {table} SET merged_into=?,version=version+1,updated_at=? WHERE id=?", (keep["id"], now(), duplicate["id"]))
            db().execute(f"UPDATE {table} SET version=version+1,status='pending',updated_at=? WHERE id=?", (now(), keep["id"]))
            for affected_kind, ids in [("record", affected_records), ("source", affected_sources)]:
                affected_table = "records" if affected_kind == "record" else "sources"
                for aid in ids:
                    db().execute(f"UPDATE {affected_table} SET version=version+1,status='pending',updated_at=? WHERE id=?", (now(), aid))
                    save_revision(db(), affected_kind, aid, "合并转接编号：" + did + " → " + keep["id"], user()["id"])
            db().execute("INSERT INTO merge_events(target_type,keep_id,duplicate_id,actor_id,created_at,snapshot_json) VALUES (?,?,?,?,?,?)",
                         (kind, keep["id"], duplicate["id"], user()["id"], now(), json.dumps(before, ensure_ascii=False)))
            save_revision(db(), kind, keep["id"], "人工合并：保留旧编号 " + duplicate["id"], user()["id"])
        return jsonify(id=keep["id"], previous_id=duplicate["id"])

    @app.get("/api/merged/<kind>/<rid>")
    def archived(kind, rid):
        if kind not in {"record", "source"}:
            abort(404)
        table = "records" if kind == "record" else "sources"
        canonical = ctx.get_record(rid) if kind == "record" else ctx.get_source(rid)
        old = db().execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
        if not old or not old["merged_into"]:
            abort(404)
        # Archived bodies retain their own visibility, even if the survivor later becomes shared.
        if kind == "record" and not ctx.visible(old):
            abort(404)
        return jsonify(current_id=canonical["id"], archived=dict(old))
