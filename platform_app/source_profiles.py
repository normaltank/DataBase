"""Shared versioned source writes used by HTTP and maintenance tools."""
import json
import uuid
from flask import abort
from . import identity, workflow, source_catalog, note_subjects
from .store import save_revision, now
from .record_revisions import validate_text, check_version
SOURCE_FIELDS = ["name", "original_name", "kind", "classification", "location", "country", "research_scope", "website", "catalogue_url", "host_id", "publisher_id", "issn", "scope_status", "notes"] + list(workflow.SOURCE_DEFAULTS)
SOURCE_KINDS = {"think_tank", "institution", "journal", "serial", "portal", "registry_publication"}
relationship_ids = source_catalog.ids

def get(db, sid):
    row=identity.resolve(db,'sources',sid)
    if not row:abort(404,'来源不存在。')
    return row

def values(db, data, base=None):
    data = dict(data)
    values = validate_text(data, SOURCE_FIELDS, base)
    if base:
        values["aliases"] = identity.retained_aliases(db, "sources", base["id"], values["aliases"])
    try:
        values["introduction_html"], values["introduction_text"] = workflow.clean_rich(values["introduction_html"])
    except ValueError as error:
        abort(400, str(error))
    if not values["name"] or values["kind"] not in SOURCE_KINDS:
        abort(400, "请填写来源名称并选择正确类型。")
    for field in ["host_id", "publisher_id"]:
        ids = relationship_ids(values[field])
        canonical = []
        for parent_id in ids:
            parent = get(db, parent_id)
            if parent["kind"] not in ["institution", "think_tank"] or (base and parent["id"] == base["id"]):
                abort(400, "主办方或出版方应为机构。")
            canonical.append(parent["id"])
        values[field] = " | ".join(dict.fromkeys(canonical))
    if "relationships" in data:
        relations = data["relationships"]
        if isinstance(relations, str):
            try:
                relations = json.loads(relations)
            except ValueError:
                abort(400, "机构关系格式不正确。")
        if isinstance(relations, list):
            canonical_relations = []
            for relation in relations:
                if isinstance(relation, dict) and isinstance(relation.get("target_id"), str):
                    target = identity.resolve(db, "sources", relation["target_id"])
                    relation = {**relation, "target_id": target["id"] if target else relation["target_id"]}
                canonical_relations.append(relation)
            data["relationships"] = canonical_relations
    values["scope_status"] = values["scope_status"] or "candidate"
    if base:
        note_subjects.validate_source_type(db, base["id"], values["kind"])
        from .journal_archives import validate_source_type
        validate_source_type(db, base['id'], values['kind'])
    try:
        source_catalog.validate_metadata(db, data, values, base)
    except (ValueError, TypeError) as error:
        abort(400, str(error))
    return values


def save_in_transaction(db, actor, sid, data, action="修订来源"):
    """Caller owns transaction, including any candidate decision audit."""
    row = get(db, sid)
    sid = row["id"]
    check_version(data, row)
    current = values(db, data, row)
    current.update(status="pending", version=row["version"]+1, updated_at=now())
    if not db.execute("SELECT 1 FROM revisions WHERE target_type='source' AND target_id=?", (sid,)).fetchone():
        save_revision(db, "source", sid, "导入初始版本", "admin")
    changed = db.execute(f"UPDATE sources SET {','.join(k+'=?' for k in current)} WHERE id=? AND version=?", [*current.values(), sid, row["version"]]).rowcount
    if not changed:
        abort(409, "内容已变化，请刷新。")
    save_revision(db, "source", sid, action, actor["id"])
    return sid


def create_in_transaction(db, actor, data):
    current=values(db,data)
    duplicate=db.execute("SELECT id FROM sources WHERE lower(name)=lower(?) OR (website<>'' AND website=?) ORDER BY id LIMIT 1",(current['name'],current['website'])).fetchone()
    if duplicate:abort(409,'相同名称或官网已登记，请先读取已有来源。')
    sid='SRC-LOCAL-'+uuid.uuid4().hex[:10].upper()
    current.update(id=sid,created_at=now(),updated_at=now())
    db.execute(f"INSERT INTO sources ({','.join(current)}) VALUES ({','.join('?' for _ in current)})",list(current.values()))
    save_revision(db,'source',sid,'建立来源档案',actor['id'])
    return sid
