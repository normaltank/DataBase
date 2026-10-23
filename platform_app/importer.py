"""Read only the four explicit ThinkTank tables; never execute source workspace code."""
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from .store import connect, now

DEFAULT_ROOT = Path(r"D:\Agent Workspace\ThinkTank\PaperDatabase\LatviaResearchDatabase")
FILES = ["02_Source_Registry/sources.csv", "02_Source_Registry/serials.csv",
         "03_Bibliography/records.csv", "03_Bibliography/attachments.csv"]


def norm(value):
    return re.sub(r"[^\w]", "", value.casefold())


def insert(db, table, item):
    if table == "sources":
        from .source_catalog import initial_metadata
        item.update(initial_metadata(item))
    keys = list(item)
    db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", list(item.values()))


def import_thinktank(data_dir, root=DEFAULT_ROOT):
    root, data_dir = Path(root), Path(data_dir)
    tables, digests = {}, {}
    for rel in FILES:
        path = root / rel
        content = path.read_bytes()
        digests[rel] = hashlib.sha256(content).hexdigest()
        tables[rel] = list(csv.DictReader(content.decode("utf-8-sig").splitlines(keepends=True)))
    db = connect(data_dir / "platform.sqlite3")
    if db.execute("SELECT 1 FROM settings WHERE key='thinktank_import_v1'").fetchone():
        db.close()
        return {"already_imported": True}
    stamp = now()
    report = {"imported_at": stamp, "source_root": str(root), "sha256": digests,
              "source_rows": 0, "serial_rows": 0, "records": 0, "skipped": [],
              "unresolved_serial_matches": [], "attachment_policy": "official_links_only"}
    try:
        with db:
            for r in tables[FILES[0]]:
                scope = r["current_scope_disposition"]
                kind = "institution"
                if "discovery_portal" in scope:
                    kind = "portal"
                elif r["source_class"] == "学术期刊":
                    kind = "registry_publication"
                elif any(x in r["source_class"] for x in ["智库", "独立经济政策", "非政府政策", "非营利社会与政策"]):
                    kind = "think_tank"
                location = r["location"]
                country = "爱沙尼亚" if "Estonia" in location else (
                    "拉脱维亚" if any(x in location for x in ["Latvia", "Rīga", "Daugavpils", "Jelgava", "Liepāja", "Rēzekne", "Salaspils", "Valmiera", "Ventspils"]) else "")
                insert(db, "sources", dict(id=r["source_id"], name=r["name_zh"] or r["name_en"] or r["name_local"],
                    original_name=r["name_en"] or r["name_local"], kind=kind, classification=r["source_class"],
                    location=location, country=country, research_scope="", website=r["official_website"],
                    catalogue_url=r["publication_catalog_url"], scope_status=scope,
                    upstream_status=r["verification_status"], notes=r["scope_relationship"],
                    raw_json=json.dumps(r, ensure_ascii=False), created_at=stamp, updated_at=stamp))
                report["source_rows"] += 1
            serial_by_issn, serial_by_title = defaultdict(set), defaultdict(set)
            for r in tables[FILES[1]]:
                kind = "journal" if r["serial_type"] in ["journal", "peer_reviewed_journal"] else "serial"
                insert(db, "sources", dict(id=r["serial_id"], name=r["chinese_working_title"] or r["title_en"] or r["title_local"],
                    original_name=r["title_en"] or r["title_local"], kind=kind, classification=r["serial_type"],
                    host_id=r["host_institution_source_id"], publisher_id=r["primary_publisher_source_id"],
                    issn="; ".join(filter(None, [r["issn_print"], r["issn_electronic"]])),
                    website=r["official_homepage"], catalogue_url=r["archive_url"],
                    scope_status=r["current_scope_disposition"], upstream_status=r["verification_status"],
                    notes=r["publisher_relationship"], raw_json=json.dumps(r, ensure_ascii=False),
                    created_at=stamp, updated_at=stamp))
                for key in [r["issn_print"], r["issn_electronic"]]:
                    if key:
                        serial_by_issn[norm(key)].add(r["serial_id"])
                for key in [r["title_en"], r["title_local"], r["chinese_working_title"]]:
                    if key:
                        serial_by_title[norm(key)].add(r["serial_id"])
                report["serial_rows"] += 1
            source_ids = {r[0] for r in db.execute("SELECT id FROM sources")}
            attachment_map = defaultdict(list)
            for a in tables[FILES[3]]:
                if a["is_current"] != "1":
                    continue
                # Keep metadata only. No files are copied or served from the external workspace.
                attachment_map[a["record_id"]].append({
                    "name": Path(a["local_path"].replace("\\", "/")).name,
                    "url": a["official_source_url"], "type": a["attachment_type"],
                    "sha256": a["sha256"], "sharing_status": "not_migrated"})
            for r in tables[FILES[2]]:
                if r["collection_scope"] not in ["core_local_publication", "extended_external_output"]:
                    report["skipped"].append({"id": r["record_id"], "reason": r["collection_scope"]})
                    continue
                matches = set()
                for part in re.split(r"[;,|]", r["ISSN"]):
                    matches |= serial_by_issn.get(norm(part), set())
                title_matches = serial_by_title.get(norm(r["publication_title"]), set())
                if len(matches) != 1:
                    matches = title_matches if len(title_matches) == 1 else matches
                serial_id = next(iter(matches)) if len(matches) == 1 else None
                if not serial_id and r["publication_title"]:
                    report["unresolved_serial_matches"].append(r["record_id"])
                raw = dict(r, imported_attachments=attachment_map[r["record_id"]])
                insert(db, "records", dict(id=r["record_id"], kind=r["publication_type"],
                    title=r["title_translated"] or r["title_original"], original_title=r["title_original"],
                    authors=r["creators"], source_id=r["publisher_source_id"] if r["publisher_source_id"] in source_ids else None,
                    serial_id=serial_id, publication_title=r["publication_title"],
                    published_on=r["date_published"], language=r["language"], abstract=r["abstract_original"],
                    keywords=r["author_keywords"], countries="", doi=r["DOI"], url=r["landing_page_url"],
                    owner_id="admin", upstream_status=r["metadata_status"],
                    raw_json=json.dumps(raw, ensure_ascii=False), created_at=stamp, updated_at=stamp))
                report["records"] += 1
            db.execute("INSERT INTO collections(id,name,description,visibility,owner_id,created_at) VALUES (?,?,?,?,?,?)", (
                "pilot-latvia", "拉脱维亚 · 语言与社会", "初始试用专题：从现有条目中整理语言、社会融入及公共政策资料。可继续加入原文和编译成果。", "shared", "admin", stamp))
            samples = db.execute("SELECT id FROM records WHERE lower(title) LIKE '%language%' OR lower(title) LIKE '%integration%' ORDER BY published_on DESC LIMIT 6").fetchall()
            db.executemany("INSERT INTO collection_items VALUES (?,?)", [("pilot-latvia", s[0]) for s in samples])
            db.execute("INSERT INTO settings VALUES ('thinktank_import_v1',?)", (json.dumps(report, ensure_ascii=False),))
    finally:
        db.close()
    (data_dir / "import-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
