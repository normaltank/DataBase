"""Human-confirmed identity merges retain old objects, versions and references."""
import json
import re
import unicodedata
from difflib import SequenceMatcher

from flask import abort, jsonify, request

from . import source_catalog


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


def readable_record(db, item, visible):
    """A shared current record does not publish a private merged record's aliases."""
    result, hidden, public_ids = dict(item), set(), []
    for rid in origins(db, "records", item["id"]):
        if rid == item["id"]:
            continue
        old = db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
        if visible(old):
            public_ids.append(rid)
        else:
            hidden.add(rid)
            hidden.update(line.strip() for key in ["title", "original_title", "aliases"] for line in old[key].splitlines())
    result["aliases"] = "\n".join(line for line in result.get("aliases", "").splitlines() if line not in hidden)
    if "previous_ids" in result:
        result["previous_ids"] = public_ids
    return result


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


def source_merge_dependents(db, duplicate_id):
    return {s["id"] for s in db.execute("SELECT * FROM sources WHERE merged_into IS NULL")
            if duplicate_id in source_catalog.ids(s["host_id"]) + source_catalog.ids(s["publisher_id"])
            or any(r["target_id"] == duplicate_id for r in json.loads(s["relationships"]))}


def rewrite_source_graph(db, keep, duplicate, validate_source):
    """Rewrite and validate the source graph inside the revision owner's transaction."""
    kid, did = keep["id"], duplicate["id"]
    names = aliases(keep["aliases"], duplicate["aliases"], duplicate["name"], duplicate["original_name"], did)
    db.execute("UPDATE sources SET aliases=? WHERE id=?", (names, kid))
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
    db.execute("UPDATE sources SET relationships=? WHERE id=?", (json.dumps(merged_outgoing, ensure_ascii=False), kid))
    for row in db.execute("SELECT * FROM sources WHERE merged_into IS NULL AND id<>?", (did,)).fetchall():
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
            db.execute(f"UPDATE sources SET {','.join(k+'=?' for k in values)} WHERE id=?", [*values.values(), row["id"]])
    db.execute("UPDATE sources SET merged_into=? WHERE id=?", (kid, did))
    # Revalidate the complete prospective graph in the same transaction.
    for row in db.execute("SELECT * FROM sources WHERE merged_into IS NULL").fetchall():
        obj = dict(row)
        obj["relationships"] = json.loads(obj["relationships"])
        obj["institution_types"] = json.loads(obj["institution_types"])
        validate_source(obj, row)


def register(app, *, db, body, records, validate_source):
    @app.get("/api/duplicates")
    def candidates():
        kind = request.args.get("type", "record")
        if kind not in {"record", "source"}:
            abort(400)
        table = "records" if kind == "record" else "sources"
        access = records()
        rows = [r for r in db().execute(f"SELECT * FROM {table} WHERE merged_into IS NULL LIMIT 2000") if kind == "source" or access.visible(r)]
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
        return jsonify(records().preview_merge(body()))

    @app.post("/api/merge")
    def merge():
        return jsonify(records().merge(body(), validate_source=validate_source))

    @app.get("/api/merged/<kind>/<rid>")
    def archived(kind, rid):
        if kind not in {"record", "source"}:
            abort(404)
        table = "records" if kind == "record" else "sources"
        access = records()
        canonical = access.get(rid) if kind == "record" else access.source(rid)
        old = db().execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
        if not old or not old["merged_into"]:
            abort(404)
        # Archived bodies retain their own visibility, even if the survivor later becomes shared.
        if kind == "record" and not access.visible(old):
            abort(404)
        return jsonify(current_id=canonical["id"], archived=dict(old))
