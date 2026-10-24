"""Explicit subjects of one research note, separate from citations and sources."""
import json
import uuid
from pathlib import Path

from flask import abort, jsonify

from . import identity
from .store import connect, now


SCHEMA_VERSION = 7
SUBJECT_TYPES = {"person", "institution", "journal"}


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute("""CREATE TABLE research_subjects (
                id TEXT PRIMARY KEY, note_id TEXT NOT NULL REFERENCES records(id),
                original_note_id TEXT NOT NULL REFERENCES records(id), subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL, original_subject_type TEXT NOT NULL, original_subject_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed', version INTEGER NOT NULL DEFAULT 1,
                manual_revision INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL REFERENCES users(id), updated_by TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                CHECK(subject_type IN ('person','institution','journal')),
                CHECK(original_subject_type IN ('person','institution','journal')),
                CHECK(status IN ('confirmed','needs_review','removed')))""")
            db.execute("CREATE INDEX idx_subject_note ON research_subjects(note_id,status)")
            db.execute("CREATE INDEX idx_subject_target ON research_subjects(subject_type,subject_id,status)")
            db.execute("""CREATE TABLE research_subject_history (
                id INTEGER PRIMARY KEY, relation_id TEXT NOT NULL REFERENCES research_subjects(id),
                action TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL)""")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('note_subjects_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def target(db, subject_type, subject_id):
    if not isinstance(subject_type, str) or subject_type not in SUBJECT_TYPES or not isinstance(subject_id, str):
        abort(400, "请选择人物、机构或期刊作为研究对象。")
    if subject_type == "person":
        row = identity.resolve(db, "people", subject_id)
    else:
        row = identity.resolve(db, "sources", subject_id)
    if not row:
        abort(400, "研究对象不存在，请重新选择。")
    if subject_type != "person" and row["kind"] not in ({"institution", "think_tank"} if subject_type == "institution" else {"journal"}):
        abort(409, "研究对象的类型已改变，请重新选择。")
    return row


def snapshot(db, note_id):
    return [dict(r) for r in db.execute(
        "SELECT * FROM research_subjects WHERE note_id=? AND status<>'removed' ORDER BY created_at,id", (note_id,))]


def read(db, note_id, visible=None):
    items = []
    for relation in snapshot(db, note_id):
        item = {**relation, "subject_name": target(db, relation["subject_type"], relation["subject_id"])["name"]}
        original_table = "people" if relation["original_subject_type"] == "person" else "sources"
        original = db.execute(f"SELECT name FROM {original_table} WHERE id=?", (relation["original_subject_id"],)).fetchone()
        item["original_subject_name"] = original["name"] if original else relation["original_subject_id"]
        last = db.execute("""SELECT h.action,h.identity_event_id,h.created_at,e.evidence FROM research_subject_history h
                          JOIN person_identity_events e ON e.id=h.identity_event_id
                          WHERE relation_id=? ORDER BY h.id DESC LIMIT 1""",
                          (relation["id"],)).fetchone()
        if last and last["identity_event_id"]:
            item["identity_change"] = {"event_id": last["identity_event_id"], "action": last["action"], "created_at": last["created_at"], "evidence": last["evidence"]}
        origin = db.execute("SELECT * FROM records WHERE id=?", (relation["original_note_id"],)).fetchone()
        if visible and (not origin or not visible(origin)):
            item.pop("original_note_id", None)
        items.append(item)
    return items


def audit(db, relation_id, actor_id, action, *, event_id=None):
    row = db.execute("SELECT * FROM research_subjects WHERE id=?", (relation_id,)).fetchone()
    state = dict(row)
    for prefix in ["", "original_"]:
        table = "people" if state[prefix + "subject_type"] == "person" else "sources"
        subject = db.execute(f"SELECT name FROM {table} WHERE id=?", (state[prefix + "subject_id"],)).fetchone()
        state[prefix + "subject_name"] = subject["name"] if subject else state[prefix + "subject_id"]
    db.execute("""INSERT INTO research_subject_history(relation_id,action,actor_id,created_at,snapshot_json,identity_event_id)
                  VALUES (?,?,?,?,?,?)""", (relation_id, action, actor_id, now(), json.dumps(state, ensure_ascii=False), event_id))


def save(db, note_id, kind, desired, actor_id):
    if not isinstance(desired, list) or len(desired) > 100 or not all(isinstance(r, dict) for r in desired):
        abort(400, "研究对象关联格式不正确。")
    if desired and kind != "research_note":
        abort(400, "只有研究笔记可以选择研究对象。")
    current = snapshot(db, note_id)
    retained, endpoints = set(), set()
    for item in desired:
        if "confirm" in item and type(item["confirm"]) is not bool:
            abort(400, "研究对象确认标记格式不正确。")
        subject_type, subject_id = item.get("subject_type"), item.get("subject_id")
        requested_subject_id = subject_id
        subject_id = target(db, subject_type, subject_id)["id"]
        pair = subject_type, subject_id
        row = next((r for r in current if r["id"] == item.get("id")), None) if item.get("id") else next(
            (r for r in current if (r["subject_type"], r["subject_id"]) == pair), None)
        if item.get("id") and not row:
            abort(409, "研究对象关联已改变，请重新打开笔记。")
        if (pair in endpoints and not (row and item.get("id"))) or (row and row["id"] in retained):
            abort(400, "同一研究对象请只选择一次。")
        endpoints.add(pair)
        if row:
            if item.get("id") and (type(item.get("version")) is not int or item["version"] != row["version"]):
                abort(409, "研究对象关联已改变，请重新打开笔记。")
            matching = [row] if item.get("id") else [r for r in current if (r["subject_type"], r["subject_id"]) == pair]
            for relation in matching:
                retained.add(relation["id"])
                if (relation["subject_type"], relation["subject_id"]) != pair or item.get("confirm") is True:
                    db.execute("""UPDATE research_subjects SET subject_type=?,subject_id=?,status='confirmed',
                        version=version+1,manual_revision=manual_revision+1,updated_by=?,updated_at=? WHERE id=?""",
                               (subject_type, subject_id, actor_id, now(), relation["id"]))
                    audit(db, relation["id"], actor_id, "manual")
        else:
            relation_id = "subject-" + uuid.uuid4().hex
            db.execute("""INSERT INTO research_subjects(id,note_id,original_note_id,subject_type,subject_id,
                original_subject_type,original_subject_id,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (relation_id, note_id, note_id, subject_type, subject_id, subject_type, requested_subject_id, actor_id, actor_id, now(), now()))
            retained.add(relation_id)
            audit(db, relation_id, actor_id, "created")
    for row in current:
        if row["id"] not in retained:
            db.execute("""UPDATE research_subjects SET status='removed',version=version+1,
                manual_revision=manual_revision+1,updated_by=?,updated_at=? WHERE id=?""", (actor_id, now(), row["id"]))
            audit(db, row["id"], actor_id, "removed")


def restore(db, note_id, kind, historical, actor_id):
    """A content author's explicit restoration is a new selection, never erases audit."""
    current = {r["id"]: r for r in snapshot(db, note_id)}
    selected = []
    for old in historical:
        item = {"subject_type": old["subject_type"], "subject_id": old["subject_id"]}
        if old.get("id") in current:
            item.update(id=old["id"], version=current[old["id"]]["version"])
        selected.append(item)
    save(db, note_id, kind, selected, actor_id)


def validate_source_type(db, source_id, kind):
    for row in db.execute("SELECT DISTINCT subject_type FROM research_subjects WHERE subject_id=? AND status<>'removed' AND subject_type<>'person'", (source_id,)):
        if kind not in ({"institution", "think_tank"} if row["subject_type"] == "institution" else {"journal"}):
            abort(409, "此来源仍被用作笔记研究对象；请先按笔记编辑权限处理关联，再更正类型。")


def rewire(db, old_id, new_id, actor_id, *, record=False):
    field, action = ("note_id", "record_merge") if record else ("subject_id", "source_merge")
    condition = "" if record else " AND subject_type<>'person'"
    rows = db.execute(f"SELECT * FROM research_subjects WHERE {field}=?" + condition, (old_id,)).fetchall()
    for row in rows:
        db.execute(f"UPDATE research_subjects SET {field}=?,version=version+1,updated_by=?,updated_at=? WHERE id=?",
                   (new_id, actor_id, now(), row["id"]))
        audit(db, row["id"], actor_id, action)


def validate_backup(db):
    """Polymorphic subject references need the same restore check as SQL foreign keys."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"research_subjects", "research_subject_history"} <= tables:
        raise ValueError("备份缺少笔记研究对象关系或历史。")
    for relation in db.execute("SELECT * FROM research_subjects"):
        note = db.execute("SELECT kind FROM records WHERE id=?", (relation["note_id"],)).fetchone()
        table = "people" if relation["subject_type"] == "person" else "sources"
        subject = db.execute(f"SELECT * FROM {table} WHERE id=?", (relation["subject_id"],)).fetchone()
        original_table = "people" if relation["original_subject_type"] == "person" else "sources"
        original = db.execute(f"SELECT 1 FROM {original_table} WHERE id=?", (relation["original_subject_id"],)).fetchone()
        allowed = ({"institution", "think_tank"} if relation["subject_type"] == "institution" else {"journal"})
        if (not note or note["kind"] != "research_note" or not subject or not original or
                (relation["status"] != "removed" and table == "sources" and subject["kind"] not in allowed)):
            raise ValueError("笔记研究对象不存在或类型不适用。")
    for revision in db.execute("SELECT relation_id,snapshot_json FROM research_subject_history"):
        try:
            state = json.loads(revision["snapshot_json"])
            if state["id"] != revision["relation_id"] or state["subject_type"] not in SUBJECT_TYPES:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ValueError("笔记研究对象历史不完整。") from None


def register(app, ctx):
    def notes(subject_type, subject_id):
        row = target(ctx.db(), subject_type, subject_id)
        access = ctx.records()
        rows = ctx.db().execute("""SELECT DISTINCT r.* FROM records r JOIN research_subjects s ON s.note_id=r.id
            WHERE s.subject_type=? AND s.subject_id=? AND s.status='confirmed' AND r.merged_into IS NULL
            ORDER BY r.updated_at DESC,r.id""", (subject_type, row["id"]))
        items = [ctx.record_summary(r) for r in rows if access.visible(r)]
        return jsonify(items=items, total=len(items))

    @app.get("/api/people/<pid>/research-notes")
    def person_notes(pid):
        return notes("person", pid)

    @app.get("/api/sources/<sid>/research-notes")
    def source_notes(sid):
        row = ctx.records().source(sid)
        kind = "institution" if row["kind"] in {"institution", "think_tank"} else "journal"
        return notes(kind, row["id"])

    @app.put("/api/records/<rid>/research-subjects")
    def update_note_subjects(rid):
        payload = ctx.body()
        if "research_subjects" not in payload:
            abort(400, "请明确选择研究对象。")
        return jsonify(id=ctx.records().change_subjects(rid, payload))

    @app.get("/api/records/<rid>/research-subjects/history")
    def note_subject_history(rid):
        row = ctx.records().get(rid, edit=True)
        rows = ctx.db().execute("""SELECT h.*,u.name AS actor_name FROM research_subject_history h
            JOIN research_subjects s ON s.id=h.relation_id JOIN users u ON u.id=h.actor_id
            WHERE s.note_id=? ORDER BY h.id DESC""", (row["id"],))
        return jsonify(items=[{**{k: h[k] for k in ["id", "relation_id", "action", "actor_id", "actor_name", "created_at", "identity_event_id"]},
                               "snapshot": json.loads(h["snapshot_json"])} for h in rows])
