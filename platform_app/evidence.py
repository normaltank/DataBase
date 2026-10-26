"""Evidence notes share record identity, permissions and revision storage."""
import json

from flask import abort

from . import workflow

SNAPSHOT_FIELDS = ["id", "kind", "title", "original_title", "authors", "publication_title", "volume", "issue", "pages", "issn", "published_on", "url", "doi", "version",
                   "body_html", "body_text", "abstract", "quote", "translation", "interpretation", "locator",
                   "evidence_record_id", "evidence_version", "evidence_url", "evidence_attachment_id", "evidence_snapshot_json"]


def snapshot(row, original=False):
    fields = ["id", "kind", "title", "original_title", "authors", "publication_title", "volume", "issue", "pages", "issn", "published_on", "url", "doi", "version"] if original else SNAPSHOT_FIELDS
    return {key: row[key] for key in fields if key in row.keys()}


def readable_snapshot(db, snapshot_data, visible):
    if snapshot_data.get("evidence_record_id"):
        from .identity import resolve
        original = resolve(db, "records", snapshot_data["evidence_record_id"])
        return bool(original and visible(original))
    return True


def validate(db, data, values, base, get_record, data_dir):
    rid = values.get("evidence_record_id", "")
    if rid:
        original = get_record(rid)
        if values["kind"] != "research_note" or original["kind"] in workflow.CONTENT_KINDS or (base and original["id"] == base["id"]):
            abort(400, "带出处的摘录应保存为研究笔记，并关联原始资料。")
        if not values["quote"] or not values["locator"]:
            abort(400, "请分别填写原文摘录和页码、段落或其他定位。")
        values["evidence_record_id"] = original["id"]
        attachment = values.get("evidence_attachment_id", "")
        changed = not base or base["evidence_record_id"] != original["id"] or base["evidence_attachment_id"] != attachment
        refresh = data.get("refresh_evidence") is True
        if attachment and (changed or refresh) and attachment not in json.loads(original["attachment_ids"]):
            abort(400, "引用附件不属于该原始资料的当前版本。")
        if changed or refresh:
            values["evidence_version"] = original["version"]
            values["evidence_snapshot_json"] = json.dumps(snapshot(original, original=True), ensure_ascii=False)
        text_changed = bool(base and any(values[key] != base[key] for key in ["quote", "locator"]))
        if attachment and (changed or refresh or text_changed):
            attached = db.execute("SELECT * FROM attachments WHERE id=? AND record_id=?", (attachment, original["id"])).fetchone()
            if not attached:
                abort(400, "引用附件不属于该原始资料。")
            from .attachment_anchor import capture
            saved = json.loads(values.get("evidence_snapshot_json") or base["evidence_snapshot_json"])
            occurrence = data.get("evidence_occurrence", 0)
            if type(occurrence) is not int or not 0 <= occurrence <= 1000000:
                abort(400, "所选原句位置格式不正确。")
            saved["attachment_anchor"] = capture(db, data_dir, attached, values["quote"], values["locator"], occurrence)
            values["evidence_snapshot_json"] = json.dumps(saved, ensure_ascii=False)
    elif any(values.get(key) for key in ["quote", "locator", "evidence_attachment_id"]):
        abort(400, "请指定摘录对应的原始资料。")
    elif base and base["evidence_record_id"]:
        values.update(evidence_version=None, evidence_snapshot_json="{}")
    if values.get("evidence_url") and not workflow.safe_link(values["evidence_url"]):
        abort(400, "证据链接应使用有效的 http 或 https 地址。")
    if "evidence_ids" not in data:
        return None
    ids = data["evidence_ids"]
    if not isinstance(ids, list) or len(ids) > 100 or not all(isinstance(x, str) for x in ids):
        abort(400, "证据引用格式不正确。")
    if ids and values["kind"] not in {"compilation", "research_report"}:
        abort(400, "个人报告或编译成果可以引用研究笔记和摘录。")
    canonical = []
    for eid in ids:
        note = get_record(eid)
        if note["kind"] != "research_note" or (base and note["id"] == base["id"]):
            abort(400, "请选择可见的研究笔记或摘录作为证据。")
        canonical.append(note["id"])
    return sorted(set(canonical))


def save_links(db, rid, ids, get_record, refresh=False):
    if ids is None:
        return
    current = {r["excerpt_id"]: r for r in db.execute("SELECT * FROM evidence_links WHERE report_id=?", (rid,))}
    db.execute("DELETE FROM evidence_links WHERE report_id=?", (rid,))
    for eid in ids:
        if eid in current and not refresh:
            row = current[eid]
            version, text = row["excerpt_version"], row["snapshot_json"]
        else:
            note = get_record(eid)
            version, text = note["version"], json.dumps(snapshot(note), ensure_ascii=False)
        db.execute("INSERT INTO evidence_links VALUES (?,?,?,?)", (rid, eid, version, text))


def citations(db, rid, visible):
    items = []
    for link in db.execute("SELECT * FROM evidence_links WHERE report_id=?", (rid,)):
        note = db.execute("SELECT * FROM records WHERE id=?", (link["excerpt_id"],)).fetchone()
        if note and visible(note):
            pinned = json.loads(link["snapshot_json"])
            if not readable_snapshot(db, pinned, visible):
                continue
            items.append({"excerpt_id": note["id"], "excerpt_version": link["excerpt_version"],
                          "current_version": note["version"], "snapshot": pinned})
    return items
