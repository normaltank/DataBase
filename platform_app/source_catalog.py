"""Source identities, evidence and directed institution links, independent of HTTP/UI."""
import json
import re
from datetime import date
from pathlib import Path

INSTITUTIONS = {"institution", "think_tank"}
PUBLICATIONS = {"journal", "serial", "registry_publication"}
TYPES = {"think_tank", "university", "research_institute", "faculty", "other"}
RELATIONS = {"part_of", "established_by", "cooperates_with", "funded_by"}
DEFAULTS = {
    "institution_types": "[]", "relationships": "[]", "country_evidence": "",
    "host_evidence": "", "host_country_status": "auto",
    "international_status": "unknown", "international_evidence": "",
}
TEXT_FIELDS = [k for k in DEFAULTS if k not in {"institution_types", "relationships"}]


def ids(value):
    return list(dict.fromkeys(s.strip() for s in re.split(r"[|;,；]", value or "") if s.strip()))


def unpack(row):
    obj = dict(DEFAULTS, **dict(row))
    for key in ("institution_types", "relationships", "raw_json"):
        if isinstance(obj.get(key), str):
            obj[key] = json.loads(obj[key])
    return obj


def group(kind):
    if kind in INSTITUTIONS:
        return "institution"
    return {"journal": "journal", "portal": "maintenance"}.get(kind, "publication")


def registered_institution_types(s):
    """Classify the registered subject; an affiliation does not confer a type."""
    label = s.get("classification", "")
    name = s.get("name", "")
    subject = s.get("original_name", "").split(",", 1)[0]
    think_tank = s['kind'] == 'think_tank' or '智库' in label + name or bool(re.search(r'\bthink[ -]tank\b', subject, re.I))
    tags = ["think_tank"] if think_tank else []
    faculty = bool(re.match(r"Faculty\b", subject, re.I) or
                   re.search(r"(?:大学|高校)[^（）()]*学院(?:[（(].*)?$", name) or
                   re.search(r"(?:大学|高校)(?:内部|结构|下属|附属)?[^/；;]*学院", label))
    research = any(term in label + name for term in
                   ("研究所", "研究中心", "研究机构", "研究单位", "科研单位"))
    subunit = faculty or bool(re.search(
        r"(?:大学|高校).*(?:内部|附属|下属|结构|研究|科研|学院|中心|单位)", label))
    subunit = subunit or bool(re.search(r"高等教育.*(?:研究所|研究中心|科研单位)", label))
    subunit = subunit or any(term in name for term in ("研究所", "研究中心"))
    historical = "历史高校" in label
    higher_education = bool(re.search(r"(?:大学|高校)(?:[（(].*)?$", label) or "高等教育" in label)
    if faculty:
        tags.append("faculty")
    elif research:
        tags.append("research_institute")
    if (higher_education and not subunit) or historical:
        tags.append("university")
    return tags or ["other"]


def initial_metadata(row):
    """Describe existing registrations, without claiming a fresh external review."""
    s = unpack(row)
    raw = s.get("raw_json") or {}
    values = dict(DEFAULTS)
    if s["kind"] in INSTITUTIONS:
        values["institution_types"] = json.dumps(registered_institution_types(s))
        if s.get("country") and raw.get("location"):
            values["country_evidence"] = (
                f"既有机构登记：国家 {s['country']}；原所在地 {raw['location']}。\n"
                f"出处：{raw.get('official_website', '')}\n"
                f"{date.today().isoformat()} 整理既有登记，未重新核验机构地址，中心核对状态另计。")
    elif s["kind"] in PUBLICATIONS and ids(s.get("host_id")):
        if ids(raw.get("host_institution_source_id")) == ids(s.get("host_id")):
            values["host_evidence"] = (
                f"上游连续出版物登记 {s['id']} 的 host_institution_source_id：{s['host_id']}。\n"
                f"出处：{raw.get('evidence_urls') or raw.get('official_homepage', '')}\n"
                f"{date.today().isoformat()} 整理既有主办登记；不是中心已核对结论，发现角色冲突应标待确认。")
            role_note = raw.get("publisher_relationship", "")
            if re.search(r"(host|主办).{0,100}(pending|unverified|unresolved|待核|待确认)", role_note, re.I):
                values["host_country_status"] = "pending"
                values["host_evidence"] += "\n原登记明示角色待核：" + role_note
    return values


def migrate(data_dir):
    """Additive, transactional v1 -> v2 migration; archive before changing live rows."""
    from .store import connect, now, save_revision
    data_dir = Path(data_dir)
    db = connect(data_dir / "platform.sqlite3")
    try:
        columns = {r[1] for r in db.execute("PRAGMA table_info(sources)")}
        missing = [k for k in DEFAULTS if k not in columns]
        if not missing:
            return None
        has_content = db.execute("SELECT count(*) FROM sources").fetchone()[0] or db.execute("SELECT count(*) FROM records").fetchone()[0]
        backup = None
        if has_content:
            from .maintenance import create_backup
            backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for key in missing:
                default = DEFAULTS[key].replace("'", "''")
                db.execute(f"ALTER TABLE sources ADD COLUMN {key} TEXT NOT NULL DEFAULT '{default}'")
            for row in db.execute("SELECT * FROM sources").fetchall():
                values = initial_metadata(row)
                if not any(values[k] != DEFAULTS[k] for k in values):
                    continue
                if not db.execute("SELECT 1 FROM revisions WHERE target_type='source' AND target_id=?", (row["id"],)).fetchone():
                    save_revision(db, "source", row["id"], "目录升级前版本", "admin")
                values.update(version=row["version"] + 1, updated_at=now(), status="pending")
                db.execute(f"UPDATE sources SET {','.join(k+'=?' for k in values)} WHERE id=?", [*values.values(), row["id"]])
                save_revision(db, "source", row["id"], "目录升级：补充登记依据与类型", "admin")
            db.execute("UPDATE settings SET value='2' WHERE key='schema_version'")
            if backup:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('source_catalog_migration_backup',?)", (str(backup),))
        return backup
    finally:
        db.close()


def catalog(db):
    rows = {r["id"]: unpack(r) for r in db.execute("SELECT * FROM sources ORDER BY name") if not ("merged_into" in r.keys() and r["merged_into"])}
    for s in rows.values():
        s["group"] = group(s["kind"])
        s["related_from"] = []
        s["related"] = []
        s["institutions"] = []
        basis, candidates, missing = [], set(), []
        hosts = ids(s["host_id"])
        for host_id in hosts:
            h = rows.get(host_id)
            if not h or h["kind"] not in INSTITUTIONS:
                missing.append(host_id + "：机构登记缺失")
                continue
            countries = ids(h["country"])
            basis.append({"id": h["id"], "name": h["name"], "countries": countries, "evidence": h["country_evidence"]})
            if not countries or not h["country_evidence"]:
                missing.append(h["name"] + "：国家或依据待补充")
            else:
                candidates.update(countries)
        if not hosts:
            missing.append("主办机构待登记")
        if not s["host_evidence"]:
            missing.append("主办关系依据待补充")
        if s["host_country_status"] == "pending":
            missing.append("主办角色存在疑问或冲突")
        s["national_status"] = "pending" if missing else "recorded"
        s["national_countries"] = [] if missing else sorted(candidates)
        s["candidate_countries"] = sorted(candidates)
        s["country_basis"] = basis
        s["country_gaps"] = missing
        # One projection for source selection and record scope queries. Institution
        # registration and publication host evidence retain their distinct rules.
        s["filter_countries"] = ids(s["country"]) if s["kind"] in INSTITUTIONS else s["national_countries"] if s["kind"] in PUBLICATIONS else []
        publishers = [rows[i] for i in ids(s["publisher_id"]) if i in rows]
        s["publisher_countries"] = sorted({c for p in publishers for c in ids(p["country"])})
        for parent_id in ids(s["host_id"]) + ids(s["publisher_id"]):
            if parent_id in rows:
                p = rows[parent_id]
                if not any(x["id"] == parent_id for x in s["institutions"]):
                    s["institutions"].append({k: p[k] for k in ("id", "name", "kind")})
    for s in rows.values():
        for relation in s["relationships"]:
            target = rows.get(relation["target_id"])
            if target:
                target["related_from"].append(dict(relation, source_id=s["id"], source_name=s["name"]))
        for parent_id in set(ids(s["host_id"]) + ids(s["publisher_id"])):
            if parent_id in rows:
                rows[parent_id]["related"].append({k: s[k] for k in ("id", "name", "kind")})
    return rows


def matches_scope(source, group="", country="", international=""):
    return (not group or source["group"] == group) and (
        not country or (not source["filter_countries"] if country == "__pending__" else country in source["filter_countries"])) and (
        not international or source["kind"] == "journal" and source["international_status"] == international)


def validate_metadata(db, data, values, base=None):
    """Call while holding the source write transaction, including on history restore."""
    if base:
        from .bylines import validate_source_kind
        validate_source_kind(db, base["id"], values["kind"])
        from .affiliations import validate_source_kind as validate_affiliation_kind
        validate_affiliation_kind(db, base["id"], values["kind"])
    current = unpack(base) if base else dict(DEFAULTS)
    sid = base["id"] if base else None
    if base and values['kind'] != base['kind']:
        if values['kind'] not in INSTITUTIONS:
            if current['relationships']:
                raise ValueError('此机构已登记机构关系，请先处理这些关系后再更正为其他对象类型。')
            current.update(institution_types=[], relationships=[], country_evidence='')
            if base['kind'] in INSTITUTIONS:
                for key in ('country', 'location'):
                    if key not in data:
                        values[key] = ''
        if values['kind'] not in PUBLICATIONS:
            for key in ('host_id', 'publisher_id', 'issn'):
                if key not in data:
                    values[key] = ''
            current.update(host_evidence='', host_country_status='auto')
        if values['kind'] != 'journal':
            current.update(international_status='unknown', international_evidence='')
    for key in TEXT_FIELDS:
        v = data.get(key, current[key])
        if not isinstance(v, str) or len(v) > 12000:
            raise ValueError("依据或状态字段格式不正确。")
        values[key] = v.strip()
    if values["host_country_status"] not in {"auto", "pending"}:
        raise ValueError("请选择主办关系的依据状态。")
    if values["international_status"] not in {"yes", "no", "unknown"}:
        raise ValueError("国际定位应为是、否或未知。")
    if values["international_status"] != "unknown" and not values["international_evidence"]:
        raise ValueError("国际定位选择是或否时必须填写依据；没有依据请保留未知。")
    tags = data.get("institution_types", current.get("institution_types", []))
    relations = data.get("relationships", current.get("relationships", []))
    if isinstance(tags, str):
        tags = json.loads(tags)
    if isinstance(relations, str):
        relations = json.loads(relations)
    if not isinstance(tags, list) or any(not isinstance(t, str) or t not in TYPES for t in tags):
        raise ValueError("机构类型不正确。")
    if not base and values["kind"] == "think_tank" and "institution_types" not in data:
        tags = ["think_tank"]
    if not isinstance(relations, list) or len(relations) > 100:
        raise ValueError("机构关系格式或数量不正确。")
    all_rows = {r["id"]: unpack(r) for r in db.execute("SELECT * FROM sources") if not ("merged_into" in r.keys() and r["merged_into"])}
    institution = values["kind"] in INSTITUTIONS
    if not institution and (tags or relations):
        raise ValueError("机构类型及机构间关系只适用于机构。")
    if not institution and sid:
        for other in all_rows.values():
            if any(r["target_id"] == sid for r in other["relationships"]) or sid in ids(other["host_id"]) + ids(other["publisher_id"]):
                raise ValueError("此机构已有关系或主办／出版引用，不能改为其他对象类型。")
    if values["kind"] not in PUBLICATIONS and any(data.get(k) for k in ("host_id", "publisher_id", "issn")):
        raise ValueError("该对象不适用期刊主办方、出版方或 ISSN 字段。")
    if values["kind"] != "journal" and values["international_status"] != "unknown":
        raise ValueError("国际办刊定位只适用于期刊。")
    clean, seen = [], set()
    for r in relations:
        if not isinstance(r, dict):
            raise ValueError("每项机构关系必须包含类型、目标和依据。")
        kind, target_id, evidence, checked_on = (r.get(k, "") for k in ("type", "target_id", "evidence", "checked_on"))
        if not all(isinstance(v, str) for v in (kind, target_id, evidence, checked_on)) or kind not in RELATIONS:
            raise ValueError("机构关系类型或字段不正确。")
        target = all_rows.get(target_id)
        if not target or target["kind"] not in INSTITUTIONS:
            raise ValueError("关系目标必须是已登记机构。")
        if target_id == sid:
            raise ValueError("机构不能与自身建立关系。")
        if not evidence.strip() or len(evidence) > 12000:
            raise ValueError("每项机构关系必须填写依据。")
        if checked_on:
            try:
                date.fromisoformat(checked_on)
            except ValueError:
                raise ValueError("关系核查日期应为 YYYY-MM-DD。") from None
        if (kind, target_id) in seen:
            raise ValueError("同一关系重复登记。")
        if kind == "cooperates_with" and any(x["type"] == kind and x["target_id"] == sid for x in target["relationships"]):
            raise ValueError("合作关系已由另一方登记，请从该关系的起点编辑。")
        seen.add((kind, target_id))
        clean.append(dict(type=kind, target_id=target_id, evidence=evidence.strip(), checked_on=checked_on))
    graph = {key: [r["target_id"] for r in obj["relationships"] if r["type"] == "part_of"] for key, obj in all_rows.items()}
    if sid:
        graph[sid] = [r["target_id"] for r in clean if r["type"] == "part_of"]
    for start in graph.get(sid, []):
        pending, visited = [start], set()
        while pending:
            node = pending.pop()
            if node == sid:
                raise ValueError("隶属关系会形成循环，请检查上级与下属方向。")
            if node not in visited:
                visited.add(node)
                pending.extend(graph.get(node, []))
    values["institution_types"] = json.dumps(list(dict.fromkeys(tags)), ensure_ascii=False)
    values["relationships"] = json.dumps(clean, ensure_ascii=False)
    # Editing a dependency without supplying its evidence cannot reuse the old claim.
    if base and set(ids(values.get("country"))) != set(ids(base["country"])) and values["country_evidence"] == current["country_evidence"]:
        values["country_evidence"] = ""
    if base and set(ids(values.get("host_id"))) != set(ids(base["host_id"])) and values["host_evidence"] == current["host_evidence"]:
        values["host_evidence"] = ""
    return values
