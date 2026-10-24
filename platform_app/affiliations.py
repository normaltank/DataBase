"""Evidence-backed employment and article units retain separate stable relations."""
import json
import uuid
from datetime import date
from pathlib import Path

from flask import abort, jsonify, request
from werkzeug.exceptions import HTTPException

from . import bylines, identity, workflow
from .store import connect, now


SCHEMA_VERSION = 9


def validate_source_kind(db, sid, kind):
    if kind in {"institution", "think_tank"} or not db.execute("SELECT 1 FROM sqlite_master WHERE name='person_employments'").fetchone():
        return
    for table in ["person_employments", "record_affiliations"]:
        if db.execute(f"SELECT 1 FROM {table} WHERE institution_id=? AND removed_at IS NULL", (sid,)).fetchone():
            raise ValueError("此机构仍被任职经历或文章署名单位引用，请先有依据地整理关系，再更正来源类型。")


def source_records(db, sid):
    return {row[0] for row in db.execute("SELECT DISTINCT record_id FROM record_affiliations WHERE institution_id=?", (sid,))}


def validate_backup(db):
    """Validate current rows and complete provenance chains before a restore is published."""
    required = {"person_employments", "person_employment_state", "record_affiliations", "record_affiliation_state", "affiliation_changes"}
    if not required <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        raise ValueError("备份缺少任职、署名单位或关系历史。")

    def exists(table, rid):
        if not db.execute(f"SELECT 1 FROM {table} WHERE id=?", (rid,)).fetchone():
            raise ValueError("任职或署名单位的身份、资料引用不完整。")

    def check(row, kind, active=False):
        for key in ["institution_id", "original_institution_id", "selected_institution_id"]:
            exists("sources", row[key])
        if active and db.execute("SELECT kind FROM sources WHERE id=?", (row["institution_id"],)).fetchone()[0] not in {"institution", "think_tank"}:
            raise ValueError("当前任职或署名单位的机构类型不适用。")
        if not isinstance(row["evidence"], str) or not row["evidence"].strip():
            raise ValueError("关系出处不完整。")
        if kind == "employment":
            for key in ["person_id", "original_person_id", "selected_person_id"]:
                exists("people", row[key])
            if not isinstance(row["role"], str) or not row["role"].strip():
                raise ValueError("任职角色不完整。")
            for key in ["start_date", "end_date"]:
                if row[key]:
                    known_date(row[key])
            start, end = row["start_date"], row["end_date"]
            if start and end and start[:min(len(start), len(end))] > end[:min(len(start), len(end))]:
                raise ValueError("任职时间顺序不正确。")
        else:
            for key in ["record_id", "origin_record_id"]:
                exists("records", row[key])
            for key in ["byline_id", "original_byline_id", "selected_byline_id"]:
                exists("record_bylines", row[key])
            for key, bid in [("original_byline_json", "original_byline_id"), ("byline_snapshot_json", "selected_byline_id")]:
                snapshot = json.loads(row[key])
                if snapshot["id"] != row[bid] or not snapshot["raw_name"].strip():
                    raise ValueError("署名单位的原始署名快照不完整。")
                exists("records", snapshot["record_id"])
                exists("records", snapshot["origin_record_id"])
                for prefix in ["original_target", "selected_target", "target"]:
                    if snapshot[prefix + "_id"]:
                        if snapshot[prefix + "_type"] not in {"person", "institution"}:
                            raise ValueError("署名快照的身份类型不完整。")
                        exists("people" if snapshot[prefix + "_type"] == "person" else "sources", snapshot[prefix + "_id"])
            if active and db.execute("SELECT record_id FROM record_bylines WHERE id=?", (row["byline_id"],)).fetchone()[0] != row["record_id"]:
                raise ValueError("文章署名单位与当前作品署名的归属不一致。")

    seen = set()
    try:
        for kind, table, state, owner in [("employment", "person_employments", "person_employment_state", "person_id"),
                                           ("article_affiliation", "record_affiliations", "record_affiliation_state", "record_id")]:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for row in db.execute(f"SELECT * FROM {table}"):
                current = dict(row)
                check(current, kind, not row["removed_at"])
                version = db.execute(f"SELECT version FROM {state} WHERE {owner}=?", (row[owner],)).fetchone()
                changes = db.execute("SELECT * FROM affiliation_changes WHERE relation_type=? AND relation_id=? ORDER BY id", (kind, row["id"])).fetchall()
                if not version or version[0] < 1 or not changes or len(changes) != row["version"]:
                    raise ValueError("关系集合版本或修改历史不完整。")
                previous = None
                immutable = {key: row[key] for key in columns if key.startswith("original_") or key == "origin_record_id"}
                for index, event in enumerate(changes, 1):
                    after = json.loads(event["after_json"])
                    before = json.loads(event["before_json"]) if event["before_json"] else None
                    if (set(after) != columns or after["id"] != row["id"] or after["version"] != index or before != previous
                            or any(after[key] != value for key, value in immutable.items())
                            or after["manual_revision"] != (1 if previous is None else previous["manual_revision"] + (event["change_kind"] == "manual"))):
                        raise ValueError("关系历史来历或版本不连续。")
                    check(after, kind)
                    previous = after
                    seen.add(event["id"])
                if previous != current:
                    raise ValueError("关系当前状态与最后历史不一致。")
        if seen != {row[0] for row in db.execute("SELECT id FROM affiliation_changes")}:
            raise ValueError("关系历史存在无对应关系的记录。")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError, HTTPException) as error:
        raise ValueError("任职、署名单位或历史格式不完整。") from error


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='person_employments'").fetchone():
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute("""CREATE TABLE person_employment_state (
                person_id TEXT PRIMARY KEY REFERENCES people(id), version INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE person_employments (
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id),
                original_person_id TEXT NOT NULL REFERENCES people(id),
                selected_person_id TEXT NOT NULL REFERENCES people(id),
                institution_id TEXT NOT NULL REFERENCES sources(id),
                original_institution_id TEXT NOT NULL REFERENCES sources(id),
                selected_institution_id TEXT NOT NULL REFERENCES sources(id),
                role TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                evidence TEXT NOT NULL, version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX idx_employment_person ON person_employments(person_id)")
            db.execute("CREATE INDEX idx_employment_institution ON person_employments(institution_id)")
            db.execute("""CREATE TABLE record_affiliation_state (
                record_id TEXT PRIMARY KEY REFERENCES records(id), version INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE record_affiliations (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
                origin_record_id TEXT NOT NULL REFERENCES records(id),
                byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                original_byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                selected_byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                original_byline_json TEXT NOT NULL, byline_snapshot_json TEXT NOT NULL,
                institution_id TEXT NOT NULL REFERENCES sources(id),
                original_institution_id TEXT NOT NULL REFERENCES sources(id),
                selected_institution_id TEXT NOT NULL REFERENCES sources(id),
                evidence TEXT NOT NULL, version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX idx_affiliation_record ON record_affiliations(record_id)")
            db.execute("CREATE INDEX idx_affiliation_institution ON record_affiliations(institution_id)")
            db.execute("""CREATE TABLE affiliation_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, relation_type TEXT NOT NULL, relation_id TEXT NOT NULL,
                actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                change_kind TEXT NOT NULL, change_note TEXT NOT NULL, identity_event_id TEXT,
                before_json TEXT, after_json TEXT NOT NULL)""")
            db.execute("CREATE INDEX idx_affiliation_history ON affiliation_changes(relation_type,relation_id,id)")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('affiliations_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def text(data, key, limit=4000):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        abort(400, "关系字段格式或长度不正确。")
    return value.strip()


def known_date(value):
    """Keep YYYY, YYYY-MM or YYYY-MM-DD as supplied; never fill unknown dates."""
    try:
        if len(value) not in {4, 7, 10} or any(len(part) != size for part, size in zip(value.split("-"), [4, 2, 2])):
            raise ValueError()
        parts = value.split("-")
        if not all(part.isascii() and part.isdigit() for part in parts):
            raise ValueError()
        date(*([int(part) for part in parts] + [1] * (3 - len(parts))))
    except ValueError:
        abort(400, "时间请填写有效的 YYYY、YYYY-MM 或 YYYY-MM-DD；未知时留空。")
    return value


class Relations:
    """Independent collection versions, stable rows, manual decisions and audit events."""
    def __init__(self, db, actor):
        self.db, self.actor = db, actor

    def institution(self, sid):
        row = identity.resolve(self.db, "sources", sid)
        if not row or row["kind"] not in {"institution", "think_tank"}:
            abort(400, "请选择已有机构；期刊及其他来源不能作为任职或署名单位。")
        return {"id": row["id"], "name": row["name"]}

    def person(self, pid):
        row = identity.resolve(self.db, "people", pid)
        if not row:
            abort(404, "人物档案不存在。")
        return {"id": row["id"], "name": row["name"]}

    def version(self, owner):
        row = self.db.execute(f"SELECT version FROM {self.state_table} WHERE {self.owner_key}=?", (owner,)).fetchone()
        return row[0] if row else 0

    def bump(self, owner):
        self.db.execute(f"""INSERT INTO {self.state_table} VALUES (?,1)
            ON CONFLICT({self.owner_key}) DO UPDATE SET version=version+1""", (owner,))

    def rows(self, owner):
        return self.db.execute(f"SELECT * FROM {self.table} WHERE {self.owner_key}=? ORDER BY rowid", (owner,)).fetchall()

    def change(self, before, values, *, owner=None, kind="manual", note="", event_id=None):
        stamp = now()
        if before:
            rid = before["id"]
            values = {**values, "version": before["version"] + 1, "updated_at": stamp}
            if kind == "manual":
                values["manual_revision"] = before["manual_revision"] + 1
            self.db.execute(f"UPDATE {self.table} SET {','.join(key+'=?' for key in values)} WHERE id=?",
                            [*values.values(), rid])
        else:
            rid = self.relation_type + "-" + uuid.uuid4().hex
            values = {**self.origins(values, owner), **values, "id": rid, self.owner_key: owner,
                      "version": 1, "manual_revision": 1, "created_at": stamp, "updated_at": stamp}
            self.db.execute(f"INSERT INTO {self.table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
        after = dict(self.db.execute(f"SELECT * FROM {self.table} WHERE id=?", (rid,)).fetchone())
        self.db.execute("""INSERT INTO affiliation_changes(relation_type,relation_id,actor_id,created_at,
            change_kind,change_note,identity_event_id,before_json,after_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (self.relation_type, rid, self.actor["id"], stamp, kind, note, event_id,
                         json.dumps(dict(before), ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False)))
        return after

    def check_change(self, owner, data):
        if type(data.get("version")) is not int or data["version"] != self.version(owner):
            abort(409, "关系已被更新，请对照最新版本；你的输入仍保留。")
        note = text(data, "change_note")
        if not note:
            abort(400, "请填写本次关系维护的依据或纠正说明。")
        return note

    def readable(self, row):
        return True

    def history(self, owner):
        owner = self.detail(owner)[self.owner_key]
        items = []
        for row in self.db.execute(f"""SELECT c.*,u.name AS actor_name FROM affiliation_changes c
            JOIN {self.table} r ON r.id=c.relation_id JOIN users u ON u.id=c.actor_id
            WHERE c.relation_type=? AND r.{self.owner_key}=? ORDER BY c.id DESC""", (self.relation_type, owner)):
            after = json.loads(row["after_json"])
            if not self.readable(after):
                continue
            before = json.loads(row["before_json"]) if row["before_json"] else None
            items.append({**{key: row[key] for key in ["id", "relation_id", "actor_id", "actor_name",
                          "created_at", "change_kind", "change_note", "identity_event_id"]},
                          "before": self.historical(before) if before and self.readable(before) else None,
                          "after": self.historical(after)})
        return items

    def historical(self, row):
        item = dict(row)
        for key, table in [("institution_id", "sources"), ("person_id", "people")]:
            if key in item:
                target = self.db.execute(f"SELECT name FROM {table} WHERE id=?", (item[key],)).fetchone()
                item[key.removesuffix("_id")] = {"id": item[key], "name": target[0] if target else item[key]}
        return item

    def update(self, owner, data):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            owner = self.detail(owner)[self.owner_key]
            note, items = self.check_change(owner, data), data.get("items")
            if not isinstance(items, list) or len(items) > 200:
                abort(400, "请明确提交关系列表，最多 200 项。")
            existing = {row["id"]: row for row in self.rows(owner) if self.readable(row)}
            seen = set()
            for item in items:
                if not isinstance(item, dict):
                    abort(400, "关系格式不正确。")
                rid = item.get("id")
                if rid is not None and (not isinstance(rid, str) or rid not in existing or rid in seen or existing[rid]["removed_at"]):
                    abort(400, "关系编号无效或重复，请重新打开列表。")
                before = existing.get(rid)
                if "reconfirm" in item and type(item["reconfirm"]) is not bool:
                    abort(400, "关系重新确认标记格式不正确。")
                values = self.values(item, owner, before)
                if not before or item.get("reconfirm") or any(before[key] != value for key, value in values.items()):
                    self.change(before, values, owner=owner, note=note)
                if rid:
                    seen.add(rid)
            for rid, row in existing.items():
                if rid not in seen and not row["removed_at"]:
                    self.change(row, {"removed_at": now()}, note=note)
            self.bump(owner)
        return self.detail(owner)

    def merge_sources(self, keep, duplicate):
        rows = self.db.execute(f"SELECT * FROM {self.table} WHERE institution_id=?", (duplicate,)).fetchall()
        for row in rows:
            self.change(row, {"institution_id": keep}, kind="source_merge", note="来源合并转接：" + duplicate + " → " + keep)
        for owner in {row[self.owner_key] for row in rows}:
            self.bump(owner)

    def restore(self, owner, change_id, data):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            owner = self.detail(owner)[self.owner_key]
            note = self.check_change(owner, data)
            event = self.db.execute("SELECT * FROM affiliation_changes WHERE id=? AND relation_type=?",
                                    (change_id, self.relation_type)).fetchone()
            current = self.db.execute(f"SELECT * FROM {self.table} WHERE id=? AND {self.owner_key}=?",
                                      (event["relation_id"] if event else "", owner)).fetchone()
            if not current or not self.readable(current):
                abort(404, "关系历史不存在，或当前账号没有查看权限。")
            old = json.loads(event["after_json"])
            if not self.readable(old):
                abort(404, "当前账号没有查看此关系历史的权限。")
            selected = {**old, "institution_id": old["selected_institution_id"]}
            if "byline_id" in old:
                selected["byline_id"] = old["selected_byline_id"]
            values = self.values(selected, owner)
            values["removed_at"] = old["removed_at"]
            self.change(current, values, note=note)
            self.bump(owner)
        return self.detail(owner)


class Employments(Relations):
    table, state_table, owner_key, relation_type = "person_employments", "person_employment_state", "person_id", "employment"

    def origins(self, values, owner):
        return {"original_person_id": owner, "selected_person_id": owner,
                "original_institution_id": values["selected_institution_id"]}

    def values(self, data, owner, before=None):
        sid = text(data, "institution_id", 200)
        institution = self.institution(sid)
        values = {key: text(data, key, 40000 if key == "evidence" else 4000) for key in ["role", "start_date", "end_date", "evidence"]}
        if not values["role"] or not values["evidence"]:
            abort(400, "任职关系需要填写角色与可核查出处。")
        for key in ["start_date", "end_date"]:
            if values[key]:
                known_date(values[key])
        start, end = values["start_date"], values["end_date"]
        if start and end and start[:min(len(start), len(end))] > end[:min(len(start), len(end))]:
            abort(400, "已知任职起始时间不能晚于结束时间。")
        selected = before["selected_institution_id"] if before and not data.get("reconfirm") and institution["id"] == before["institution_id"] else sid
        return {**values, "institution_id": institution["id"], "selected_institution_id": selected}

    def present(self, row):
        return {**dict(row), "person": self.person(row["person_id"]), "institution": self.institution(row["institution_id"])}

    def detail(self, pid):
        person = self.person(pid)
        return {"person_id": person["id"], "person": person, "version": self.version(person["id"]), "can_edit": True,
                "items": [self.present(row) for row in self.rows(person["id"]) if not row["removed_at"]]}

    def for_institution(self, sid):
        institution = self.institution(sid)
        return {"institution": institution, "items": [self.present(row) for row in self.db.execute(
            "SELECT * FROM person_employments WHERE institution_id=? AND removed_at IS NULL ORDER BY rowid", (institution["id"],))]}


class ArticleAffiliations(Relations):
    table, state_table, owner_key, relation_type = "record_affiliations", "record_affiliation_state", "record_id", "article_affiliation"

    def __init__(self, db, actor, access, summary=None):
        super().__init__(db, actor)
        self.access, self.summary = access, summary
        self.bylines = bylines.Bylines(db, actor, access, summary)

    def origins(self, values, owner):
        return {"origin_record_id": owner, "original_byline_id": values["selected_byline_id"],
                "original_byline_json": values["byline_snapshot_json"],
                "original_institution_id": values["selected_institution_id"]}

    def readable(self, row):
        origin = self.db.execute("SELECT * FROM records WHERE id=?", (row["origin_record_id"],)).fetchone()
        if not origin or not self.access.visible(origin):
            return False
        # Reassigning a relation cannot disclose a private original author's snapshot.
        for key in ["byline_id", "original_byline_id", "selected_byline_id"]:
            byline = self.db.execute("SELECT * FROM record_bylines WHERE id=?", (row[key],)).fetchone()
            if not byline or not self.bylines.readable(byline):
                return False
        return True

    def values(self, data, owner, before=None):
        bid, sid = text(data, "byline_id", 200), text(data, "institution_id", 200)
        byline = self.db.execute("SELECT * FROM record_bylines WHERE id=? AND record_id=?", (bid, owner)).fetchone()
        if not byline or not self.bylines.readable(byline) or (byline["removed_at"] and (not before or before["byline_id"] != bid)):
            abort(400, "请选择本篇资料中当前可读的具体署名。")
        institution = self.institution(sid)
        evidence = text(data, "evidence", 40000)
        if not evidence:
            abort(400, "文章署名单位需要可核查的出处。")
        selected = before["selected_institution_id"] if before and not data.get("reconfirm") and institution["id"] == before["institution_id"] else sid
        return {"institution_id": institution["id"], "selected_institution_id": selected, "byline_id": bid,
                "selected_byline_id": bid, "evidence": evidence,
                "byline_snapshot_json": before["byline_snapshot_json"] if before and before["byline_id"] == bid
                else json.dumps(dict(byline), ensure_ascii=False)}

    def present(self, row):
        byline = self.db.execute("SELECT * FROM record_bylines WHERE id=?", (row["byline_id"],)).fetchone()
        displayed = self.bylines.historical(json.dumps(dict(byline))) if byline["removed_at"] else self.bylines.present(byline)
        return {**dict(row), "byline": displayed, "institution": self.institution(row["institution_id"])}

    def detail(self, rid):
        record = self.bylines.record(rid)
        return {"record_id": record["id"], "version": self.version(record["id"]),
                "record_version": record["version"], "byline_version": self.bylines.version(record["id"]), "can_edit": True,
                "bylines": [self.bylines.present(row) for row in self.bylines.rows(record["id"]) if not row["removed_at"] and self.bylines.readable(row)],
                "items": [self.present(row) for row in self.rows(record["id"]) if not row["removed_at"] and self.readable(row)]}

    def check_change(self, owner, data):
        note = super().check_change(owner, data)
        record = self.bylines.record(owner)
        if (type(data.get("record_version")) is not int or data["record_version"] != record["version"]
                or type(data.get("byline_version")) is not int or data["byline_version"] != self.bylines.version(owner)):
            abort(409, "资料或署名已改变，请对照最新内容；你的输入仍保留。")
        return note

    def historical(self, row):
        return {**super().historical(row), "byline": json.loads(row["byline_snapshot_json"])}

    def merge_records(self, keep, duplicate):
        rows = self.rows(duplicate)
        for row in rows:
            self.change(row, {"record_id": keep}, kind="record_merge", note="资料合并转接：" + duplicate + " → " + keep)
        if rows:
            self.bump(keep)
            self.bump(duplicate)

    def for_institution(self, sid):
        institution = self.institution(sid)
        items = []
        for row in self.db.execute("SELECT * FROM record_affiliations WHERE institution_id=? AND removed_at IS NULL ORDER BY rowid", (institution["id"],)):
            record = self.db.execute("SELECT * FROM records WHERE id=? AND merged_into IS NULL", (row["record_id"],)).fetchone()
            byline = self.db.execute("SELECT removed_at FROM record_bylines WHERE id=?", (row["byline_id"],)).fetchone()
            if record and self.access.visible(record) and self.readable(row) and not byline["removed_at"]:
                items.append({**self.present(row), "record": {key: record[key] for key in ["id", "title", "kind", "published_on"]}})
        return {"institution": institution, "items": items, "total": len(items)}

    def published_works(self, sid):
        institution = self.institution(sid)
        rows = [row for row in self.db.execute("SELECT * FROM records WHERE source_id=? AND merged_into IS NULL ORDER BY published_on DESC,id", (institution["id"],))
                if row["kind"] not in workflow.CONTENT_KINDS and self.access.visible(row)]
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            abort(400, "分页参数不正确。")
        return {"items": [{key: row[key] for key in ["id", "title", "kind", "authors", "published_on"]} for row in rows[(page-1)*20:page*20]],
                "total": len(rows), "page": page, "size": 20}


def register(app, ctx):
    def employment():
        return Employments(ctx.db(), ctx.user())

    def article():
        return ArticleAffiliations(ctx.db(), ctx.user(), ctx.records(), ctx.record_summary)

    @app.get("/api/people/<pid>/employments")
    def get_employments(pid):
        return jsonify(employment().detail(pid))

    @app.put("/api/people/<pid>/employments")
    def save_employments(pid):
        return jsonify(employment().update(pid, ctx.body()))

    @app.get("/api/people/<pid>/employments/history")
    def employment_history(pid):
        return jsonify(items=employment().history(pid))

    @app.post("/api/people/<pid>/employments/history/<int:change_id>/restore")
    def restore_employment(pid, change_id):
        return jsonify(employment().restore(pid, change_id, ctx.body()))

    @app.get("/api/sources/<sid>/employments")
    def institution_employments(sid):
        return jsonify(employment().for_institution(sid))

    @app.get("/api/records/<rid>/affiliations")
    def get_affiliations(rid):
        return jsonify(article().detail(rid))

    @app.put("/api/records/<rid>/affiliations")
    def save_affiliations(rid):
        return jsonify(article().update(rid, ctx.body()))

    @app.get("/api/records/<rid>/affiliations/history")
    def affiliation_history(rid):
        return jsonify(items=article().history(rid))

    @app.post("/api/records/<rid>/affiliations/history/<int:change_id>/restore")
    def restore_affiliation(rid, change_id):
        return jsonify(article().restore(rid, change_id, ctx.body()))

    @app.get("/api/sources/<sid>/affiliations")
    def institution_affiliations(sid):
        return jsonify(article().for_institution(sid))

    @app.get("/api/sources/<sid>/published-works")
    def institution_published_works(sid):
        return jsonify(article().published_works(sid))
