"""Explicit topic end/reopen, immutable confirmation basis and write lock."""
import json
import re
import uuid
from pathlib import Path

from flask import abort, jsonify

from .store import connect, now

SCHEMA_VERSION = 26
WORK_TABLES = ("topic_candidates", "topic_meetings", "topic_manuscripts", "topic_returns", "topic_finals", "topic_summaries")
SCHEMA = [
    "CREATE TABLE topic_closures(topic_id TEXT PRIMARY KEY REFERENCES collaboration_topics(id), state TEXT NOT NULL CHECK(state IN ('open','closed')), version INTEGER NOT NULL CHECK(version>0), closed_stage TEXT CHECK(closed_stage IN ('selection','compilation')), origin_json TEXT NOT NULL)",
    "CREATE TABLE topic_closure_events(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), action TEXT NOT NULL CHECK(action IN ('end','reopen')), version INTEGER NOT NULL, from_state TEXT NOT NULL, to_state TEXT NOT NULL, stage TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), qualification_version INTEGER NOT NULL, basis_json TEXT NOT NULL, incomplete_json TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,version), UNIQUE(topic_id,actor_id,request_id))",
]


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        previous = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
        if previous >= SCHEMA_VERSION:
            return
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA:
                db.execute(statement)
            for topic in db.execute("SELECT id FROM collaboration_topics"):
                create(db, topic["id"], {"kind": "legacy_migration", "source_schema": previous, "initial_state": "open", "created_at": now()})
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('topic_closure_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def create(db, tid, origin=None):
    origin = origin or {"kind": "created", "initial_state": "open", "created_at": now()}
    db.execute("INSERT INTO topic_closures VALUES (?,'open',1,NULL,?)", (tid, json.dumps(origin, ensure_ascii=False)))


def state(db, tid):
    return db.execute("SELECT * FROM topic_closures WHERE topic_id=?", (tid,)).fetchone()


def is_open(db, tid):
    return state(db, tid)["state"] == "open"


def require_open(db, tid):
    if not is_open(db, tid):
        abort(409, "本期已结束，材料仍可查阅和导出。文件与说明已保留，请联系负责人重开后再继续。")


def basis(db, topic, format_version=2):
    from . import topic_stages
    stage, lifecycle = topic_stages.state(db, topic["id"]), state(db, topic["id"])
    qualification = db.execute("SELECT version FROM lead_qualifications WHERE member_id=?", (topic["lead_id"],)).fetchone()
    from . import topic_handoffs
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='topic_materials'").fetchone():
        format_version = 1
    return {**({"format_version": 2} if format_version == 2 else {}), "topic_id": topic["id"], "topic_version": topic["version"], "stage": stage["stage"], "stage_version": stage["version"],
            "lifecycle_version": lifecycle["version"], "qualification_version": qualification[0] if qualification else 0,
            "active_member_ids": [r[0] for r in db.execute("SELECT p.member_id FROM topic_participants p JOIN users u ON u.id=p.member_id WHERE p.topic_id=? AND p.active=1 AND u.active=1 ORDER BY p.member_id", (topic["id"],))],
            "materials": topic_handoffs.identities(db, topic["id"]) if format_version == 2 else {table: [r[0] for r in db.execute(f"SELECT id FROM {table} WHERE topic_id=? ORDER BY id", (topic["id"],))] for table in WORK_TABLES}}


def incomplete(db, saved):
    """Derive status from the saved work identities, not later submissions."""
    if saved.get("format_version") == 2:
        return []
    def rows(table):
        return [db.execute(f"SELECT * FROM {table} WHERE id=?", (eid,)).fetchone() for eid in saved["materials"][table]]
    meetings, manuscripts, returns, finals = [rows(t) for t in ("topic_meetings", "topic_manuscripts", "topic_returns", "topic_finals")]
    current = max(meetings, key=lambda m: m["version"], default=None)
    result = []
    for a in json.loads(current["assignments_json"]) if current else []:
        if a["author_id"] not in saved["active_member_ids"]:
            continue
        # Match the existing series rule: a predecessor's last draft is not the new author's current draft.
        latest = max((s for s in manuscripts if s["assignment_id"] == a["id"]), key=lambda s: s["version"], default=None)
        latest = latest if latest and latest["author_id"] == a["author_id"] else None
        if latest and any(f["submission_id"] == latest["id"] for f in finals):
            continue
        status = "returned" if latest and any(r["submission_id"] == latest["id"] for r in returns) else "pending" if latest else "awaiting_submission"
        result.append({"assignment_id": a["id"], "author_id": a["author_id"], "author_name": db.execute("SELECT name FROM users WHERE id=?", (a["author_id"],)).fetchone()[0],
                       "title": a["title"], "status": status, "submission_id": latest["id"] if latest else None,
                       "submission_version": latest["version"] if latest else None, "missing_current_final": True})
    return result


def projection(db, tid):
    row = state(db, tid)
    events = []
    for event in db.execute("SELECT e.*,u.name AS actor_name FROM topic_closure_events e JOIN users u ON u.id=e.actor_id WHERE e.topic_id=? ORDER BY e.version", (tid,)):
        item = dict(event)
        item["basis"] = json.loads(item.pop("basis_json"))
        item["incomplete"] = json.loads(item.pop("incomplete_json"))
        for key in ("request_id", "request_hash", "request_json"):
            item.pop(key)
        events.append(item)
    return {"lifecycle_state": row["state"], "lifecycle_version": row["version"], "closed_stage": row["closed_stage"],
            "lifecycle_origin": json.loads(row["origin_json"]), "lifecycle_events": events}


def validate_backup(db):
    from . import topic_review as review
    def require(value):
        if not value:
            raise ValueError("主题结束状态、历史或确认依据无效。")

    def work_identity(saved):
        from . import topic_handoffs
        return {**{key: saved[key] for key in ("topic_version", "stage", "stage_version")}, "materials": {table: saved['materials'].get(table, []) for table in (*WORK_TABLES, *topic_handoffs.TABLES)}}

    for topic in db.execute("SELECT * FROM collaboration_topics"):
        row = state(db, topic["id"])
        require(row is not None)
        try:
            origin = json.loads(row["origin_json"])
            require(origin["kind"] in {"created", "legacy_migration"} and origin["initial_state"] == "open" and bool(origin["created_at"]))
            if origin["kind"] == "legacy_migration":
                from . import topic_stages
                require(type(origin["source_schema"]) is int and topic_stages.SCHEMA_VERSION <= origin["source_schema"] < SCHEMA_VERSION)
            current, version, closed_stage, closed_basis = "open", 1, None, None
            for event in db.execute("SELECT * FROM topic_closure_events WHERE topic_id=? ORDER BY version", (topic["id"],)):
                saved, data, gaps = [json.loads(event[k]) for k in ("basis_json", "request_json", "incomplete_json")]
                require(saved["topic_id"] == topic["id"] and type(saved["lifecycle_version"]) is int and type(data["lifecycle_version"]) is int and saved["lifecycle_version"] == version and data["lifecycle_version"] == version)
                require(event["from_state"] == current and event["version"] == version + 1 and event["actor_id"] == topic["lead_id"] and bool(event["created_at"]))
                require(event["action"] == ("end" if current == "open" else "reopen") and event["to_state"] == ("closed" if current == "open" else "open"))
                require(bool(re.fullmatch(r"[A-Za-z0-9_-]{8,100}", event["request_id"])) and data["request_id"] == event["request_id"] and review.fingerprint({"action": event["action"], "data": data}) == event["request_hash"])
                history = db.execute("SELECT snapshot_json FROM topic_events WHERE topic_id=? AND version=?", (topic["id"], saved["topic_version"])).fetchone()
                require(history is not None)
                members = json.loads(history[0])["participant_ids"]
                require(isinstance(saved["active_member_ids"], list) and len(set(saved["active_member_ids"])) == len(saved["active_member_ids"]) and set(saved["active_member_ids"]) <= set(members))
                qualification = db.execute("SELECT enabled FROM qualification_events WHERE member_id=? AND version=?", (event["actor_id"], event["qualification_version"])).fetchone()
                require(qualification is not None and qualification[0] == 1 and saved["qualification_version"] == event["qualification_version"])
                stage_row = db.execute("SELECT * FROM topic_stages WHERE topic_id=?", (topic["id"],)).fetchone()
                expected_stage, stage_version = json.loads(stage_row["origin_json"])["initial_stage"], 1
                for stage_event in db.execute("SELECT * FROM topic_stage_events WHERE topic_id=? AND version<=? ORDER BY version", (topic["id"], saved["stage_version"])):
                    expected_stage, stage_version = stage_event["to_stage"], stage_event["version"]
                require(saved["stage_version"] == stage_version and saved["stage"] == expected_stage and event["stage"] == expected_stage)
                from . import topic_handoffs
                require(saved.get("format_version", 1) in {1, 2})
                require(set(saved["materials"]) == set((*WORK_TABLES, *topic_handoffs.TABLES) if saved.get("format_version") == 2 else WORK_TABLES))
                for table, ids in saved["materials"].items():
                    require(isinstance(ids, list) and len(ids) == len(set(ids)))
                    for eid in ids:
                        require(db.execute(f"SELECT 1 FROM {table} WHERE id=? AND topic_id=?", (eid, topic["id"])).fetchone())
                if event["action"] == "end":
                    require(data.get("confirm") is True and data["basis_token"] == review.fingerprint(saved))
                    expected_gaps = incomplete(db, saved)
                    without_names = lambda items: [{k: v for k, v in item.items() if k != "author_name"} for item in items]
                    require(without_names(gaps) == without_names(expected_gaps))
                    closed_stage, closed_basis = expected_stage, saved
                else:
                    require(expected_stage == closed_stage and work_identity(saved) == work_identity(closed_basis) and not gaps)
                    closed_stage, closed_basis = None, None
                current, version = event["to_state"], event["version"]
            require(row["state"] == current and row["version"] == version and row["closed_stage"] == closed_stage)
            if current == "closed":
                require(work_identity(basis(db, topic)) == work_identity(closed_basis))
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("主题结束记录或确认依据损坏。") from None


def register(app, ctx):
    from . import collaboration, topic_review as review, topic_stages

    @app.get("/api/collaboration/topics/<tid>/closure-preview")
    def closure_preview(tid):
        # One read transaction binds the preview and fingerprint to the same snapshot.
        with ctx.db():
            ctx.db().execute("BEGIN")
            topic = collaboration.topic_for(ctx.db(), ctx.user(), tid, manage=True)
            require_open(ctx.db(), tid)
            saved = basis(ctx.db(), topic)
            result = {"stage": saved["stage"], "lifecycle_version": saved["lifecycle_version"], "basis_token": review.fingerprint(saved), "incomplete": incomplete(ctx.db(), saved)}
        return jsonify(result)

    def change(tid, action):
        data = ctx.body()
        key = review.request_key(data)
        digest = review.fingerprint({"action": action, "data": data})
        with ctx.db():
            ctx.db().execute("BEGIN IMMEDIATE")
            db, actor = ctx.db(), ctx.user()
            topic = collaboration.topic_for(db, actor, tid, manage=True)
            current = state(db, tid)
            old = db.execute("SELECT * FROM topic_closure_events WHERE topic_id=? AND actor_id=? AND request_id=?", (tid, actor["id"], key)).fetchone()
            if old:
                if old["request_hash"] != digest:
                    abort(409, "这一请求已经记录不同操作，请核对当前工作状态。")
                return jsonify(id=old["id"], lifecycle_state=current["state"], lifecycle_version=current["version"], reused=True)
            review.expect_version(data, "lifecycle_version", current["version"])
            required, target = ("open", "closed") if action == "end" else ("closed", "open")
            if current["state"] != required:
                abort(409, "本期结束状态已变化，请核对最新状态。")
            saved = basis(db, topic)
            if action == "end" and (data.get("confirm") is not True or data.get("basis_token") != review.fingerprint(saved)):
                return jsonify(error="本期材料或状态已变化，请重新确认结束。", latest_preview={"stage": saved["stage"], "lifecycle_version": saved["lifecycle_version"], "basis_token": review.fingerprint(saved), "incomplete": incomplete(db, saved)}), 409
            stage = topic_stages.state(db, tid)["stage"]
            if action == "reopen" and stage != current["closed_stage"]:
                abort(409, "结束前阶段与当前记录不一致，请先核对恢复材料。")
            gaps = incomplete(db, saved) if action == "end" else []
            eid, stamp = uuid.uuid4().hex, now()
            db.execute("INSERT INTO topic_closure_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (eid, tid, action, current["version"] + 1, required, target, stage, actor["id"], saved["qualification_version"], json.dumps(saved, ensure_ascii=False), json.dumps(gaps, ensure_ascii=False), key, digest, json.dumps(data, ensure_ascii=False), stamp))
            db.execute("UPDATE topic_closures SET state=?,version=version+1,closed_stage=? WHERE topic_id=?", (target, stage if action == "end" else None, tid))
        return jsonify(id=eid, lifecycle_state=target, lifecycle_version=current["version"] + 1), 201

    app.add_url_rule("/api/collaboration/topics/<tid>/end", "end_topic", lambda tid: change(tid, "end"), methods=["POST"])
    app.add_url_rule("/api/collaboration/topics/<tid>/reopen", "reopen_topic", lambda tid: change(tid, "reopen"), methods=["POST"])
