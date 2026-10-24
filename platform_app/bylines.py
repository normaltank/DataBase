"""Evidence-backed original-work bylines, separate from body authorship and ACLs."""
import json
import uuid
from pathlib import Path

from flask import abort, jsonify, request

from . import identity, workflow
from .store import connect, now


SCHEMA_VERSION = 7
FIELDS = ["raw_name", "position", "status", "target_type", "target_id", "selected_target_type",
          "selected_target_id", "evidence"]


def validate_source_kind(db, sid, kind):
    if kind in {"institution", "think_tank"} or not db.execute("SELECT 1 FROM sqlite_master WHERE name='record_bylines'").fetchone():
        return
    if db.execute("SELECT 1 FROM record_bylines WHERE target_type='institution' AND target_id=? AND removed_at IS NULL", (sid,)).fetchone():
        raise ValueError("此机构已被作品署名引用，请先有依据地纠正署名，再更正来源类型。")


def validate_record_kind(db, rid, kind):
    if kind in workflow.CONTENT_KINDS and db.execute("SELECT 1 FROM record_bylines WHERE record_id=?", (rid,)).fetchone():
        abort(409, "此原始资料已有独立署名及历史，不能改成研究内容；请分别建立研究笔记或成果。")


def source_records(db, sid):
    return {row[0] for row in db.execute("SELECT DISTINCT record_id FROM record_bylines WHERE target_type='institution' AND target_id=?", (sid,))}


def validate_backup(db):
    """Check polymorphic and JSON history references that SQLite FKs cannot express."""
    required = {"record_byline_state", "record_bylines", "byline_changes"}
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= tables:
        raise ValueError("备份缺少署名关系或历史数据。")

    def check(snapshot, active=False):
        if not db.execute("SELECT 1 FROM records WHERE id=?", (snapshot["origin_record_id"],)).fetchone():
            raise ValueError("署名原始资料引用不完整。")
        for prefix in ["original_target", "selected_target", "target"]:
            kind, tid = snapshot[prefix + "_type"], snapshot[prefix + "_id"]
            if not kind and not tid:
                continue
            if kind not in {"person", "institution"} or not tid:
                raise ValueError("署名身份类型不完整。")
            table = "people" if kind == "person" else "sources"
            target = db.execute(f"SELECT * FROM {table} WHERE id=?", (tid,)).fetchone()
            if not target or (active and prefix == "target" and kind == "institution" and target["kind"] not in {"institution", "think_tank"}):
                raise ValueError("署名身份不存在或当前类型不适用。")
        if (snapshot["status"] not in {"pending", "confirmed"} or snapshot["position"] < 1
                or (snapshot["status"] == "confirmed" and (not snapshot["target_id"] or not snapshot["evidence"]))):
            raise ValueError("署名状态或确认依据不完整。")

    try:
        for row in db.execute("SELECT * FROM record_bylines"):
            current = dict(row)
            check(current, not row["removed_at"])
            state = db.execute("SELECT version FROM record_byline_state WHERE record_id=?", (row["record_id"],)).fetchone()
            if not state or state[0] < 1 or row["manual_revision"] < 1:
                raise ValueError("署名关系版本不完整。")
            changes = db.execute("SELECT * FROM byline_changes WHERE byline_id=? ORDER BY id", (row["id"],)).fetchall()
            if not changes or len(changes) != row["version"]:
                raise ValueError("署名修改历史不完整。")
            for index, change in enumerate(changes, 1):
                after = json.loads(change["after_json"])
                if after["id"] != row["id"] or after["version"] != index:
                    raise ValueError("署名历史版本不连续。")
                check(after)
                if change["before_json"]:
                    before = json.loads(change["before_json"])
                    check(before)
                    if before["id"] != row["id"] or before["version"] != index - 1:
                        raise ValueError("署名修改前版本不一致。")
                elif index != 1:
                    raise ValueError("署名修改前历史缺失。")
            if json.loads(changes[-1]["after_json"]) != current:
                raise ValueError("署名当前状态与最后历史不一致。")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("署名或其历史格式不完整。") from error


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='record_bylines'").fetchone():
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute("""CREATE TABLE record_byline_state (
                record_id TEXT PRIMARY KEY REFERENCES records(id), version INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE record_bylines (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
                origin_record_id TEXT NOT NULL REFERENCES records(id), original_authors TEXT NOT NULL,
                raw_name TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL,
                original_target_type TEXT NOT NULL, original_target_id TEXT,
                selected_target_type TEXT NOT NULL, selected_target_id TEXT,
                target_type TEXT NOT NULL, target_id TEXT, evidence TEXT NOT NULL,
                version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX idx_byline_record ON record_bylines(record_id,position,id)")
            db.execute("CREATE INDEX idx_byline_target ON record_bylines(target_type,target_id,status)")
            db.execute("""CREATE TABLE byline_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                change_kind TEXT NOT NULL, change_note TEXT NOT NULL, identity_event_id TEXT,
                before_json TEXT, after_json TEXT NOT NULL)""")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('byline_migration_backup',?)", (str(backup),))
    finally:
        db.close()


class Bylines:
    def __init__(self, db, actor, access, summary=None):
        self.db, self.actor, self.access, self.summary = db, actor, access, summary

    def record(self, rid):
        row = self.access.get(rid)
        if row["kind"] in workflow.CONTENT_KINDS:
            abort(400, "作品署名只用于原始资料；个人成果的负责作者另行维护。")
        return row

    def readable(self, row):
        origin = self.db.execute("SELECT * FROM records WHERE id=?", (row["origin_record_id"],)).fetchone()
        return bool(origin and self.access.visible(origin))

    def target(self, kind, tid):
        if not kind and not tid:
            return None
        if kind == "person":
            row = self.db.execute("SELECT * FROM people WHERE id=?", (tid,)).fetchone()
        elif kind == "institution":
            row = identity.resolve(self.db, "sources", tid)
            if row and row["kind"] not in {"institution", "think_tank"}:
                abort(400, "机构署名必须引用机构，不能引用期刊或其他来源类型。")
        else:
            abort(400, "请选择个人或机构署名身份。")
        if not row:
            abort(400, "署名身份不存在，请核对所选档案。")
        return {"type": kind, "id": row["id"], "name": row["name"]}

    def present(self, row):
        return {**dict(row), "target": self.target(row["target_type"], row["target_id"])}

    def version(self, rid):
        row = self.db.execute("SELECT version FROM record_byline_state WHERE record_id=?", (rid,)).fetchone()
        return row[0] if row else 0

    def rows(self, rid):
        return self.db.execute("SELECT * FROM record_bylines WHERE record_id=? ORDER BY position,created_at,id", (rid,)).fetchall()

    def detail(self, rid):
        record = self.record(rid)
        return {"record_id": record["id"], "version": self.version(record["id"]),
                "record_version": record["version"],
                "raw_authors": record["authors"], "can_edit": True,
                "items": [self.present(row) for row in self.rows(record["id"]) if not row["removed_at"] and self.readable(row)]}

    def values(self, data, position):
        if not isinstance(data, dict):
            abort(400, "署名格式不正确。")
        result = {}
        for field, limit in [("raw_name", 4000), ("status", 20), ("evidence", 40000),
                             ("target_type", 20), ("target_id", 200)]:
            value = data.get(field, "")
            if not isinstance(value, str) or len(value) > limit:
                abort(400, "署名字段格式或长度不正确。")
            result[field] = value if field == "raw_name" else value.strip()
        if not result["raw_name"].strip() or result["status"] not in {"pending", "confirmed"}:
            abort(400, "请保留原始署名片段，并选择待确认或已确认。")
        result["selected_target_type"] = result["target_type"]
        result["selected_target_id"] = result["target_id"] or None
        target = self.target(result["target_type"], result["target_id"])
        if result["status"] == "confirmed" and (not target or not result["evidence"]):
            abort(400, "确认署名需要选择作者身份，并填写可核查的依据。")
        if bool(result["target_type"]) != bool(result["target_id"]):
            abort(400, "请完整选择署名身份，或保留无指定身份的待确认署名。")
        result["target_id"] = target["id"] if target else None
        result["position"] = position
        return result

    def change(self, before, values, *, record=None, kind="manual", note="", event_id=None):
        """Append a relation revision; system moves never impersonate a manual decision."""
        stamp = now()
        if before:
            values = {**values, "version": before["version"] + 1, "updated_at": stamp}
            if kind == "manual":
                values["manual_revision"] = before["manual_revision"] + 1
            self.db.execute(f"UPDATE record_bylines SET {','.join(k+'=?' for k in values)} WHERE id=?",
                            [*values.values(), before["id"]])
            bid = before["id"]
        else:
            bid = "byline-" + uuid.uuid4().hex
            values = {**values, "id": bid, "record_id": record["id"], "origin_record_id": record["id"],
                      "original_authors": record["authors"], "original_target_type": values["selected_target_type"],
                      "original_target_id": values["selected_target_id"], "version": 1, "manual_revision": 1,
                      "created_at": stamp, "updated_at": stamp}
            self.db.execute(f"INSERT INTO record_bylines ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
        after = dict(self.db.execute("SELECT * FROM record_bylines WHERE id=?", (bid,)).fetchone())
        self.db.execute("""INSERT INTO byline_changes(byline_id,actor_id,created_at,change_kind,change_note,
                           identity_event_id,before_json,after_json) VALUES (?,?,?,?,?,?,?,?)""",
                        (bid, self.actor["id"], stamp, kind, note, event_id,
                         json.dumps(dict(before), ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False)))
        return after

    def bump(self, rid):
        self.db.execute("""INSERT INTO record_byline_state VALUES (?,1)
            ON CONFLICT(record_id) DO UPDATE SET version=version+1""", (rid,))

    def merge_records(self, keep, duplicate):
        rows = self.rows(duplicate)
        if not rows:
            return
        offset = max((row["position"] for row in self.rows(keep)), default=0)
        for index, row in enumerate(rows, offset + 1):
            self.change(row, {"record_id": keep, "position": index}, kind="record_merge",
                        note="资料合并转接：" + duplicate + " → " + keep)
        self.bump(keep)
        self.bump(duplicate)

    def merge_sources(self, keep, duplicate):
        rows = self.db.execute("SELECT * FROM record_bylines WHERE target_type='institution' AND target_id=?", (duplicate,)).fetchall()
        for row in rows:
            self.change(row, {"target_id": keep}, kind="source_merge", note="来源合并转接：" + duplicate + " → " + keep)
        for rid in {row["record_id"] for row in rows}:
            self.bump(rid)

    def check_change(self, rid, data):
        if type(data.get("version")) is not int or data["version"] != self.version(rid):
            abort(409, "署名已被更新，请对照最新版本；你的输入仍保留。")
        note = data.get("change_note")
        if not isinstance(note, str) or not note.strip() or len(note) > 4000:
            abort(400, "请填写本次署名维护的依据或纠正说明。")
        return note.strip()

    def update(self, rid, data):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            record = self.record(rid)
            rid = record["id"]
            note, items = self.check_change(rid, data), data.get("items")
            if type(data.get("record_version")) is not int or data["record_version"] != record["version"]:
                abort(409, "原始资料已被修订，请对照最新题录与署名；你的输入仍保留。")
            if not isinstance(items, list) or len(items) > 100:
                abort(400, "请明确提交署名列表，最多 100 项。")
            existing = {row["id"]: row for row in self.rows(rid) if self.readable(row)}
            seen = set()
            for position, item in enumerate(items, 1):
                values = self.values(item, position)
                bid = item.get("id")
                if bid is not None and (not isinstance(bid, str) or bid not in existing or existing[bid]["removed_at"] or bid in seen):
                    abort(400, "署名编号无效或重复，请重新打开署名列表。")
                before = existing.get(bid)
                if "reconfirm" in item and type(item["reconfirm"]) is not bool:
                    abort(400, "署名身份确认标记格式不正确。")
                if before and not item.get("reconfirm") and (values["target_type"], values["target_id"]) == (before["target_type"], before["target_id"]):
                    # A form containing unchanged system transfers is not a new identity choice.
                    values["selected_target_type"] = before["selected_target_type"]
                    values["selected_target_id"] = before["selected_target_id"]
                if not before or item.get("reconfirm") or any(values[key] != before[key] for key in FIELDS):
                    self.change(before, values, record=record, note=note)
                if bid:
                    seen.add(bid)
            for bid, row in existing.items():
                if bid not in seen and not row["removed_at"]:
                    self.change(row, {"removed_at": now()}, note=note)
            self.bump(rid)
        return self.detail(rid)

    def historical(self, value):
        if value is None:
            return None
        snapshot = json.loads(value)
        target = None
        if snapshot["target_id"]:
            table = "people" if snapshot["target_type"] == "person" else "sources"
            row = self.db.execute(f"SELECT name FROM {table} WHERE id=?", (snapshot["target_id"],)).fetchone()
            target = {"id": snapshot["target_id"], "type": snapshot["target_type"], "name": row[0] if row else snapshot["target_id"]}
        return {**snapshot, "target": target}

    def history(self, rid):
        record = self.record(rid)
        rows = self.db.execute("""SELECT c.*,u.name AS actor_name FROM byline_changes c
            JOIN record_bylines b ON b.id=c.byline_id JOIN users u ON u.id=c.actor_id
            WHERE b.record_id=? ORDER BY c.id DESC""", (record["id"],))
        items = []
        for row in rows:
            after = self.historical(row["after_json"])
            if not self.readable(after):
                continue
            items.append({**{k: row[k] for k in ["id", "byline_id", "actor_id", "actor_name", "created_at",
                          "change_kind", "change_note", "identity_event_id"]},
                          "before": self.historical(row["before_json"]), "after": after, "can_restore": True})
        return items

    def restore(self, rid, change_id, data):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            record = self.record(rid)
            rid = record["id"]
            note = self.check_change(rid, data)
            event = self.db.execute("SELECT * FROM byline_changes WHERE id=?", (change_id,)).fetchone()
            current = self.db.execute("SELECT * FROM record_bylines WHERE id=? AND record_id=?",
                                      (event["byline_id"] if event else "", rid)).fetchone()
            if not current or not self.readable(current):
                abort(404, "署名历史不存在，或当前账号没有查看权限。")
            old = json.loads(event["after_json"])
            values = self.values({**old, "target_type": old["selected_target_type"],
                                  "target_id": old["selected_target_id"] or ""}, old["position"])
            values["removed_at"] = old["removed_at"]
            ordered = [row for row in self.rows(rid) if row["id"] != current["id"] and not row["removed_at"]]
            if not values["removed_at"]:
                index = min(values["position"] - 1, len(ordered))
                ordered.insert(index, current)
                values["position"] = index + 1
            self.change(current, values, note=note)
            for position, row in enumerate(ordered, 1):
                if row["id"] != current["id"] and row["position"] != position:
                    self.change(row, {"position": position}, kind="order_adjustment", note="恢复署名后的顺序整理")
            self.bump(rid)
        return self.detail(rid)

    def works(self, kind, tid):
        target = self.target(kind, tid)
        found = {}
        q = request.args.get("q", "").strip().casefold().split()
        for row in self.db.execute("""SELECT * FROM record_bylines WHERE target_type=? AND target_id=?
            AND status='confirmed' AND removed_at IS NULL ORDER BY position,id""", (kind, target["id"])):
            record = self.db.execute("SELECT * FROM records WHERE id=? AND merged_into IS NULL", (row["record_id"],)).fetchone()
            if not record or not self.access.visible(record) or not self.readable(row):
                continue
            if not all(word in (record["title"] + " " + record["authors"] + " " + record["original_title"]).casefold() for word in q):
                continue
            if record["id"] not in found:
                found[record["id"]] = {**self.summary(record), "bylines": []}
            found[record["id"]]["bylines"].append(self.present(row))
        items = sorted(found.values(), key=lambda r: (r["published_on"], r["id"]), reverse=True)
        try:
            page, size = max(1, int(request.args.get("page", "1"))), min(100, max(1, int(request.args.get("size", "20"))))
        except ValueError:
            abort(400, "分页参数不正确。")
        return {"items": items[(page-1)*size:page*size], "total": len(items), "page": page, "size": size}

    def search_text(self, rid):
        text = []
        for row in self.rows(rid):
            if row["removed_at"] or not self.readable(row):
                continue
            text.append(row["raw_name"])
            if row["status"] != "confirmed" or not row["target_id"]:
                continue
            table = "people" if row["target_type"] == "person" else "sources"
            target = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (row["target_id"],)).fetchone()
            if target:
                text.extend(target[key] for key in ["name", "original_name", "aliases"])
                if table == "people":
                    text.append(target["chinese_name"])
        return " ".join(text)


def register(app, ctx):
    def service():
        return Bylines(ctx.db(), ctx.user(), ctx.records(), ctx.record_summary)

    @app.get("/api/records/<rid>/bylines")
    def get_bylines(rid):
        return jsonify(service().detail(rid))

    @app.put("/api/records/<rid>/bylines")
    def save_bylines(rid):
        return jsonify(service().update(rid, ctx.body()))

    @app.get("/api/records/<rid>/bylines/history")
    def byline_history(rid):
        return jsonify(items=service().history(rid))

    @app.post("/api/records/<rid>/bylines/history/<int:change_id>/restore")
    def restore_byline(rid, change_id):
        return jsonify(service().restore(rid, change_id, ctx.body()))

    @app.get("/api/people/<pid>/works")
    def person_works(pid):
        return jsonify(service().works("person", pid))

    @app.get("/api/sources/<sid>/works")
    def institution_works(sid):
        return jsonify(service().works("institution", sid))
