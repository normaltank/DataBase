"""Evidence notes share record identity, permissions and revision storage."""
import json
from pathlib import Path

from flask import abort

from . import workflow

SNAPSHOT_FIELDS = ["id", "kind", "title", "original_title", "authors", "publication_title", "volume", "issue", "pages", "issn", "published_on", "url", "doi", "version",
                   "body_html", "body_text", "abstract", "quote", "translation", "interpretation", "locator",
                   "evidence_record_id", "evidence_version", "evidence_url", "evidence_attachment_id", "evidence_snapshot_json"]


SCHEMA_VERSION = 13
STANCES = {"unclassified", "supports", "contradicts", "qualifies", "background"}


def migrate(data_dir):
    from .store import connect
    from .maintenance import create_backup
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            backup = create_backup(data_dir)
            db.execute("ALTER TABLE evidence_links ADD COLUMN stance TEXT NOT NULL DEFAULT 'unclassified' CHECK(stance IN ('unclassified','supports','contradicts','qualifies','background'))")
            db.execute("ALTER TABLE evidence_links ADD COLUMN claim_note TEXT NOT NULL DEFAULT ''")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('citation_context_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def snapshot(row, original=False, db=None):
    fields = ["id", "kind", "title", "original_title", "authors", "publication_title", "volume", "issue", "pages", "issn", "published_on", "url", "doi", "version"] if original else SNAPSHOT_FIELDS
    result = {key: row[key] for key in fields if key in row.keys()}
    if db is not None:
        result["identity_baseline"] = identity_baseline(db, row["id"], original)
    return result



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
            values["evidence_snapshot_json"] = json.dumps(snapshot(original, original=True, db=db), ensure_ascii=False)
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
    if "evidence_ids" not in data and "evidence_citations" in data:
        data = {**data, "evidence_ids": [c.get("excerpt_id") for c in data["evidence_citations"]] if isinstance(data["evidence_citations"], list) and all(isinstance(c, dict) for c in data["evidence_citations"]) else None}
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
    roles = data.get("evidence_citations", [])
    if not isinstance(roles, list) or len(roles) > 100 or not all(isinstance(c, dict) for c in roles):
        abort(400, "引用用途格式不正确。")
    contexts = {}
    for context in roles:
        eid = context.get("excerpt_id")
        if not isinstance(eid, str) or eid not in ids or eid in contexts:
            abort(400, "引用用途应对应已选择的笔记，每条引用登记一次主要用途。")
        stance, claim = context.get("stance", "unclassified"), context.get("claim_note", "")
        if not isinstance(stance, str) or stance not in STANCES or not isinstance(claim, str) or len(claim) > 10000:
            abort(400, "请选择支撑、反例、限定、背景或未分类，并填写有效说明。")
        canonical_id = get_record(eid)["id"]
        if canonical_id in contexts:
            abort(400, "旧编号与当前编号指向同一笔记，请只登记一次主要用途。")
        contexts[canonical_id] = {"stance": stance, "claim_note": claim.strip()}
    return [{"excerpt_id": eid, **contexts.get(eid, {})} for eid in sorted(set(canonical))]


def save_links(db, rid, ids, get_record, refresh=False, visible=None):
    if ids is None:
        return
    current = {r["excerpt_id"]: r for r in db.execute("SELECT * FROM evidence_links WHERE report_id=?", (rid,))}
    retained = set()
    if visible:
        for eid, link in current.items():
            note = db.execute("SELECT * FROM records WHERE id=?", (eid,)).fetchone()
            if not note or not visible(note) or not readable_snapshot(db, json.loads(link["snapshot_json"]), visible):
                retained.add(eid)
    for eid in current.keys() - retained:
        db.execute("DELETE FROM evidence_links WHERE report_id=? AND excerpt_id=?", (rid, eid))
    for context in ids:
        eid = context["excerpt_id"]
        if eid in current and not refresh:
            row = current[eid]
            version, text = row["excerpt_version"], row["snapshot_json"]
        else:
            note = get_record(eid)
            version, text = note["version"], json.dumps(snapshot(note, db=db), ensure_ascii=False)
        previous = current.get(eid)
        stance = context.get("stance", previous["stance"] if previous else "background")
        claim = context.get("claim_note", previous["claim_note"] if previous else "")
        db.execute("INSERT INTO evidence_links(report_id,excerpt_id,excerpt_version,snapshot_json,stance,claim_note) VALUES (?,?,?,?,?,?)", (rid, eid, version, text, stance, claim))


def citations(db, rid, visible):
    items = []
    for link in db.execute("SELECT * FROM evidence_links WHERE report_id=?", (rid,)):
        note = db.execute("SELECT * FROM records WHERE id=?", (link["excerpt_id"],)).fetchone()
        if note and visible(note):
            pinned = json.loads(link["snapshot_json"])
            if not readable_snapshot(db, pinned, visible):
                continue
            items.append({"excerpt_id": note["id"], "excerpt_version": link["excerpt_version"],
                          "current_version": note["version"], **review_changes(db, note, link, pinned, visible), "snapshot": project_snapshot(db, pinned, visible), "stance": link["stance"], "claim_note": link["claim_note"]})
    return items


def identity_baseline(db, rid, original=False):
    """Stable relation identities and revisions, excluding mutable profile prose.

    Tombstones remain to distinguish a correction followed by restoration from
    an untouched relation. Relation versions also retain merge/split provenance.
    """
    if original:
        return {
            "bylines": [dict(r) for r in db.execute("""SELECT id,origin_record_id,version,target_type,target_id,
                selected_target_type,selected_target_id,status,removed_at FROM record_bylines
                WHERE record_id=? ORDER BY id""", (rid,))],
            "article_affiliations": [dict(r) for r in db.execute("""SELECT a.id,a.origin_record_id,a.version,a.byline_id,
                a.institution_id,a.selected_institution_id,a.removed_at,
                b.origin_record_id AS byline_origin_record_id,
                o.origin_record_id AS original_byline_origin_record_id,
                s.origin_record_id AS selected_byline_origin_record_id
                FROM record_affiliations a
                JOIN record_bylines b ON b.id=a.byline_id
                JOIN record_bylines o ON o.id=a.original_byline_id
                JOIN record_bylines s ON s.id=a.selected_byline_id
                WHERE a.record_id=? ORDER BY a.id""", (rid,))],
        }
    return {"subjects": [dict(r) for r in db.execute("""SELECT id,original_note_id,version,subject_type,subject_id,status
              FROM research_subjects WHERE note_id=? ORDER BY id""", (rid,))]}


def review_changes(db, note, link, pinned, visible):
    """Compare only baselines actually retained in the adopted note."""
    pinned = project_snapshot(db, pinned, visible)
    from .identity import resolve
    reasons = []
    if note["version"] != link["excerpt_version"]:
        reasons.append("note_updated")
    original_snapshot = json.loads(pinned.get("evidence_snapshot_json") or "{}")
    original_id = original_snapshot.get("id") or pinned.get("evidence_record_id")
    original_version = original_snapshot.get("version", pinned.get("evidence_version"))
    original = resolve(db, "records", original_id) if original_id else None
    if original:
        if original["id"] != original_id:
            reasons.append("original_merged")
        elif original_version is not None and original["version"] != original_version:
            reasons.append("original_updated")
    note_baseline = pinned.get("identity_baseline")
    original_baseline = original_snapshot.get("identity_baseline")
    known = note_baseline is not None and (not original_id or original_baseline is not None)
    identity_changes = []
    pairs = [(note_baseline, project_baseline(db, identity_baseline(db, note["id"]), visible))]
    if original:
        pairs.append((original_baseline, project_baseline(db, identity_baseline(db, original["id"], True), visible)))
    for old, current in pairs:
        if old is None:
            continue
        for scope in current:
            previous, present = old.get(scope, []), current[scope]
            if previous != present:
                endpoints = lambda rows: [{k: v for k, v in row.items() if k != "version"} for row in rows]
                identity_changes.append({"scope": scope, "change": "endpoints_or_status" if endpoints(previous) != endpoints(present) else "relation_history"})
    if identity_changes:
        reasons.append("identity_changed")
    return {"staleness_reasons": reasons, "identity_changes": identity_changes,
            "identity_baseline_status": "recorded" if known else "unknown",
            "current_original_id": original["id"] if original else None}


def project_baseline(db, baseline, visible):
    result = {}
    for kind, rows in baseline.items():
        permitted = []
        for row in rows:
            origins = [value for key, value in row.items() if key.endswith("origin_record_id") or key == "original_note_id"]
            readable = True
            for origin_id in origins:
                origin = db.execute("SELECT * FROM records WHERE id=?", (origin_id,)).fetchone()
                if origin is None or not visible(origin):
                    readable = False
                    break
            if readable:
                permitted.append(row)
        result[kind] = permitted
    return result


def project_snapshot(db, saved, visible):
    result = dict(saved)
    if "identity_baseline" in result:
        result["identity_baseline"] = project_baseline(db, result["identity_baseline"], visible)
    if result.get("evidence_snapshot_json"):
        result["evidence_snapshot_json"] = json.dumps(project_snapshot(db, json.loads(result["evidence_snapshot_json"]), visible), ensure_ascii=False)
    return result


STANCE_LABELS = {"unclassified": "未分类", "supports": "支撑", "contradicts": "反例", "qualifies": "限定", "background": "背景"}
REASON_LABELS = {"note_updated": "笔记已修订", "original_updated": "原文已修订", "original_merged": "原文已合并转向", "identity_changed": "署名、文章单位或笔记研究对象关系有变化"}


def citation_description(citation):
    lines = ["引用用途：" + STANCE_LABELS.get(citation.get("stance"), "未分类")]
    if citation.get("claim_note"):
        lines.append("所涉判断与说明：" + citation["claim_note"])
    reasons = citation.get("staleness_reasons", [])
    if reasons:
        lines.append("有变更待评估：" + "；".join(REASON_LABELS.get(reason, reason) for reason in reasons))
    scopes = {"bylines": "原文署名", "article_affiliations": "文章署名单位", "subjects": "笔记研究对象"}
    for change in citation.get("identity_changes", []):
        lines.append(scopes.get(change["scope"], change["scope"]) + ("：当前端点或确认状态已改变" if change["change"] == "endpoints_or_status" else "：关系历史已有修订（当前端点及状态相同）"))
    if citation.get("identity_baseline_status") == "unknown":
        lines.append("历史未记录完整身份基线，无法自动比较。")
    return "\n".join(lines)


def citation_scope_notice(citations):
    roles = {c.get("stance", "unclassified") for c in citations}
    if "unclassified" in roles:
        return "当前可见引用中有未分类用途，反例与限定的登记情况未知。"
    if roles == {"supports"}:
        return "当前可见的已登记引用中未登记反例或限定；这不表示现实中不存在相反材料。"
    return ""


def validate_backup(db):
    """Legacy revisions may omit context; recorded roles must remain valid."""
    import sqlite3
    try:
        columns = {r[1] for r in db.execute("PRAGMA table_info(evidence_links)")}
        if not {"stance", "claim_note"} <= columns:
            raise ValueError("备份缺少引用用途字段。")
        links = [dict(r) for r in db.execute("SELECT * FROM evidence_links")]
        for revision in db.execute("SELECT snapshot_json FROM revisions WHERE target_type='record'"):
            links.extend(json.loads(revision[0]).get("evidence_citations", []))
        for link in links:
            if (not isinstance(link.get("stance", "unclassified"), str)
                    or link.get("stance", "unclassified") not in STANCES
                    or not isinstance(link.get("claim_note", ""), str)
                    or len(link.get("claim_note", "")) > 10000
                    or not isinstance(json.loads(link["snapshot_json"]), dict)):
                raise ValueError("备份中的引用用途或说明无效。")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError, sqlite3.DatabaseError) as error:
        raise ValueError("备份中的引用用途或历史不完整。") from error
