"""Explicit topic stages; legacy inference is distinct from a human decision."""
import json
import re
import uuid
from pathlib import Path

from flask import abort, jsonify

from . import collaboration
from .store import connect, now

# Follows the actual archive-suggestions migration in the integration baseline.
SCHEMA_VERSION = 25
SCHEMA = [
    "CREATE TABLE topic_stages(topic_id TEXT PRIMARY KEY REFERENCES collaboration_topics(id), stage TEXT NOT NULL CHECK(stage IN ('selection','compilation')), version INTEGER NOT NULL CHECK(version>0), origin_json TEXT NOT NULL)",
    "CREATE TABLE topic_stage_events(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), from_stage TEXT NOT NULL, to_stage TEXT NOT NULL, version INTEGER NOT NULL, topic_version INTEGER NOT NULL, meeting_id TEXT NOT NULL REFERENCES topic_meetings(id), actor_id TEXT NOT NULL REFERENCES users(id), qualification_version INTEGER NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,version), UNIQUE(topic_id,actor_id,request_id))",
]


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
            return
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA:
                db.execute(statement)
            for topic in db.execute("SELECT id FROM collaboration_topics"):
                evidence = {}
                for table in ("topic_meetings", "topic_manuscripts", "topic_finals", "topic_summaries"):
                    rows = db.execute(f"SELECT * FROM {table} WHERE topic_id=?", (topic["id"],)).fetchall()
                    evidence[table] = [r["id"] for r in rows if table != "topic_meetings" or json.loads(r["assignments_json"])]
                stage = "compilation" if any(evidence.values()) else "selection"
                origin = {"kind": "legacy_migration", "initial_stage": stage, "created_at": now(), "evidence": evidence}
                db.execute("INSERT INTO topic_stages VALUES (?,?,1,?)", (topic["id"], stage, json.dumps(origin, ensure_ascii=False)))
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('topic_stages_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def create(db, tid):
    origin = {"kind": "created", "initial_stage": "selection", "created_at": now()}
    db.execute("INSERT INTO topic_stages VALUES (?,'selection',1,?)", (tid, json.dumps(origin)))


def state(db, tid):
    return db.execute("SELECT * FROM topic_stages WHERE topic_id=?", (tid,)).fetchone()


def require_compilation(db, topic):
    from . import topic_closure
    topic_closure.require_open(db, topic["id"])
    if state(db, topic["id"])["stage"] != "compilation":
        abort(409, "本期仍在选题阶段，请等待负责人确认分工进入编译。文件和说明仍保留。")


def effective_assignments(db, tid, meeting):
    if not meeting:
        return []
    return [a for a in json.loads(meeting["assignments_json"]) if a["title"].strip() and db.execute(
        "SELECT 1 FROM topic_participants p JOIN users u ON u.id=p.member_id WHERE p.topic_id=? AND p.member_id=? AND p.active=1 AND u.active=1",
        (tid, a["author_id"])).fetchone()]


def projection(db, actor, topic, can_manage):
    from . import topic_review as review
    row = state(db, topic["id"])
    events = [dict(r) for r in db.execute("SELECT e.*,u.name AS actor_name,m.version AS meeting_version FROM topic_stage_events e JOIN users u ON u.id=e.actor_id JOIN topic_meetings m ON m.id=e.meeting_id WHERE e.topic_id=? ORDER BY e.version", (topic["id"],))]
    for event in events:
        for key in ("request_id", "request_hash", "request_json"):
            event.pop(key)
    return {"stage": row["stage"], "stage_version": row["version"], "stage_origin": json.loads(row["origin_json"]),
            "stage_events": events, "can_enter_compilation": bool(can_manage and row["stage"] == "selection" and effective_assignments(db, topic["id"], review.latest_meeting(db, topic["id"])))}


def validate_backup(db):
    from . import topic_review as review
    def require(value):
        if not value:
            raise ValueError("主题阶段、转换依据或历史链不一致。")
    for topic in db.execute("SELECT * FROM collaboration_topics"):
        row = state(db, topic["id"])
        require(row is not None)
        try:
            origin = json.loads(row["origin_json"])
            require(origin["kind"] in {"created", "legacy_migration"} and origin["initial_stage"] in {"selection", "compilation"} and bool(origin["created_at"]))
            if origin["kind"] == "created":
                require(origin["initial_stage"] == "selection")
            else:
                evidence = origin["evidence"]
                require(set(evidence) == {"topic_meetings", "topic_manuscripts", "topic_finals", "topic_summaries"})
                for table, ids in evidence.items():
                    require(isinstance(ids, list) and len(ids) == len(set(ids)))
                    for eid in ids:
                        item = db.execute(f"SELECT * FROM {table} WHERE id=? AND topic_id=?", (eid, topic["id"])).fetchone()
                        require(item is not None and (table != "topic_meetings" or bool(json.loads(item["assignments_json"]))))
                require(origin["initial_stage"] == ("compilation" if any(evidence.values()) else "selection"))
            stage, version = origin["initial_stage"], 1
            for event in db.execute("SELECT * FROM topic_stage_events WHERE topic_id=? ORDER BY version", (topic["id"],)):
                require(stage == "selection" and event["from_stage"] == stage and event["to_stage"] == "compilation" and event["version"] == version + 1)
                data = json.loads(event["request_json"])
                require(review.fingerprint(data) == event["request_hash"] and data["request_id"] == event["request_id"] and bool(re.fullmatch(r"[A-Za-z0-9_-]{8,100}", event["request_id"])) and type(data["stage_version"]) is int and data["stage_version"] == version and type(data["topic_version"]) is int and data["topic_version"] == event["topic_version"])
                meeting = db.execute("SELECT * FROM topic_meetings WHERE id=? AND topic_id=?", (event["meeting_id"], topic["id"])).fetchone()
                require(meeting is not None and bool(json.loads(meeting["assignments_json"])) and data["meeting_version"] == meeting["version"])
                history = db.execute("SELECT snapshot_json FROM topic_events WHERE topic_id=? AND version=?", (topic["id"], event["topic_version"])).fetchone()
                require(history is not None and json.loads(history[0])["lead_id"] == event["actor_id"])
                participants = json.loads(history[0])["participant_ids"]
                require(any(a["author_id"] in participants and a["title"].strip() for a in json.loads(meeting["assignments_json"])))
                require(meeting["created_at"] <= event["created_at"] and meeting["topic_version"] <= event["topic_version"])
                qualification = db.execute("SELECT enabled FROM qualification_events WHERE member_id=? AND version=?", (event["actor_id"], event["qualification_version"])).fetchone()
                require(qualification is not None and qualification[0] == 1 and bool(event["created_at"]))
                stage, version = event["to_stage"], event["version"]
            require(stage == row["stage"] and version == row["version"])
            if stage == "selection":
                require(not any(db.execute(f"SELECT 1 FROM {table} WHERE topic_id=? LIMIT 1", (topic["id"],)).fetchone() for table in ("topic_manuscripts", "topic_returns", "topic_finals", "topic_summaries")))
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("主题阶段来源损坏。") from None


def register(app, ctx):
    from . import topic_review as review
    @app.post("/api/collaboration/topics/<tid>/enter-compilation")
    def enter_compilation(tid):
        data = ctx.body()
        key = review.request_key(data)
        digest = review.fingerprint(data)
        with ctx.db():
            ctx.db().execute("BEGIN IMMEDIATE")
            db, actor = ctx.db(), ctx.user()
            topic = collaboration.topic_for(db, actor, tid, manage=True)
            from . import topic_closure
            topic_closure.require_open(db, tid)
            previous = db.execute("SELECT * FROM topic_stage_events WHERE topic_id=? AND actor_id=? AND request_id=?", (tid, actor["id"], key)).fetchone()
            if previous:
                if previous["request_hash"] != digest:
                    abort(409, "这一请求已确认不同分工，请核对当前阶段。")
                return jsonify(id=previous["id"], stage="compilation", stage_version=previous["version"], reused=True)
            current = state(db, tid)
            review.expect_version(data, "stage_version", current["version"])
            review.expect_version(data, "topic_version", topic["version"])
            meeting = review.latest_meeting(db, tid)
            review.expect_version(data, "meeting_version", meeting["version"] if meeting else 0)
            if current["stage"] != "selection":
                abort(409, "本期已进入编译阶段，请核对最新状态。")
            assignments = json.loads(meeting['assignments_json']) if meeting else []
            effective = effective_assignments(db, tid, meeting)
            if len(effective) != len(assignments):
                abort(409, "当前分工含失效研究员，请核对全部文章分工后再进入编译。")
            if not effective:
                abort(409, "请先保存至少一项当前有效的研究员与文章分工，再确认进入编译。")
            eid, stamp = uuid.uuid4().hex, now()
            qv = db.execute("SELECT version FROM lead_qualifications WHERE member_id=?", (actor["id"],)).fetchone()[0]
            db.execute("INSERT INTO topic_stage_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (eid, tid, "selection", "compilation", current["version"] + 1, topic["version"], meeting["id"], actor["id"], qv, key, digest, json.dumps(data, ensure_ascii=False), stamp))
            db.execute("UPDATE topic_stages SET stage='compilation',version=version+1 WHERE topic_id=?", (tid,))
        return jsonify(id=eid, stage="compilation", stage_version=current["version"] + 1), 201
