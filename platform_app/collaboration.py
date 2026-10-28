"""Topic work policy. Reading a handoff never grants record editing rights."""
import json
import hashlib
import re
import uuid
from datetime import date
from pathlib import Path

from flask import abort, jsonify, request, send_file

from .record_revisions import check_version
from .store import connect, now
from . import handoff_files

SCHEMA_VERSION = 20
SCHEMA = [
    "CREATE TABLE lead_qualifications(member_id TEXT PRIMARY KEY REFERENCES users(id), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), version INTEGER NOT NULL CHECK(version>0))",
    "CREATE TABLE qualification_events(id INTEGER PRIMARY KEY, member_id TEXT NOT NULL REFERENCES users(id), actor_id TEXT NOT NULL REFERENCES users(id), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), version INTEGER NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE collaboration_topics(id TEXT PRIMARY KEY, theme TEXT NOT NULL, lead_id TEXT NOT NULL REFERENCES users(id), due_on TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE topic_participants(topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), member_id TEXT NOT NULL REFERENCES users(id), active INTEGER NOT NULL CHECK(active IN (0,1)), PRIMARY KEY(topic_id,member_id))",
    "CREATE TABLE topic_events(id INTEGER PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), actor_id TEXT NOT NULL REFERENCES users(id), version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE handoff_files(id TEXT PRIMARY KEY, name TEXT NOT NULL, stored_name TEXT UNIQUE NOT NULL, bytes INTEGER NOT NULL CHECK(bytes>0), sha256 TEXT NOT NULL, uploader_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)",
    "CREATE TABLE topic_candidates(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), author_id TEXT NOT NULL REFERENCES users(id), uploader_id TEXT NOT NULL REFERENCES users(id), version INTEGER NOT NULL CHECK(version>0), topic_version INTEGER NOT NULL, file_id TEXT UNIQUE NOT NULL REFERENCES handoff_files(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,author_id,version), UNIQUE(topic_id,uploader_id,request_id))",
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
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('collaboration_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def qualified(db, uid):
    return bool(db.execute("SELECT 1 FROM lead_qualifications q JOIN users u ON u.id=q.member_id WHERE q.member_id=? AND q.enabled=1 AND u.active=1", (uid,)).fetchone())


def can_read(db, actor, topic):
    return actor["role"] == "admin" or bool(db.execute("SELECT 1 FROM topic_participants WHERE topic_id=? AND member_id=? AND active=1", (topic["id"], actor["id"])).fetchone())


def topic_for(db, actor, tid, manage=False):
    row = db.execute("SELECT * FROM collaboration_topics WHERE id=?", (tid,)).fetchone()
    if not row or not can_read(db, actor, row):
        abort(404, "本期工作不存在或当前无权查阅。")
    if manage and (row["lead_id"] != actor["id"] or not qualified(db, actor["id"])):
        abort(403, "只有本期具有有效资格的负责人可维护本期工作。")
    return row


def topic_values(db, data):
    theme, due = data.get("theme"), data.get("due_on", "")
    ids = data.get("participant_ids")
    if not isinstance(theme, str) or not theme.strip() or len(theme) > 500:
        abort(400, "请填写本期主题（最多500字）。")
    if not isinstance(due, str):
        abort(400, "提交日期格式不正确。")
    if due:
        try:
            if date.fromisoformat(due).isoformat() != due:
                raise ValueError()
        except ValueError:
            abort(400, "提交日期请填写 YYYY-MM-DD。")
    if not isinstance(ids, list) or len(ids) > 200 or not all(isinstance(x, str) for x in ids):
        abort(400, "请选择有效参与研究员。")
    active = {r[0] for r in db.execute("SELECT id FROM users WHERE active=1")}
    if not set(ids) <= active:
        abort(400, "参与研究员包含不存在或已停用的账号。")
    return theme.strip(), due, sorted(set(ids))


def save_topic_event(db, tid, actor):
    row = dict(db.execute("SELECT * FROM collaboration_topics WHERE id=?", (tid,)).fetchone())
    row["participant_ids"] = [r[0] for r in db.execute("SELECT member_id FROM topic_participants WHERE topic_id=? AND active=1 ORDER BY member_id", (tid,))]
    db.execute("INSERT INTO topic_events(topic_id,actor_id,version,snapshot_json,created_at) VALUES (?,?,?,?,?)", (tid, actor, row["version"], json.dumps(row, ensure_ascii=False), now()))


def projection(db, actor, row):
    result = dict(row)
    result["lead_name"] = db.execute("SELECT name FROM users WHERE id=?", (row["lead_id"],)).fetchone()[0]
    result["participants"] = [dict(r) for r in db.execute("SELECT u.id,u.name,u.active FROM topic_participants p JOIN users u ON u.id=p.member_id WHERE p.topic_id=? AND p.active=1 ORDER BY u.name,u.id", (row["id"],))]
    result["can_manage"] = row["lead_id"] == actor["id"] and qualified(db, actor["id"])
    result["can_submit"] = any(p["id"] == actor["id"] for p in result["participants"])
    return result


def candidate_projection(db, tid):
    # Only call after topic_for() has authorized this exact work.
    items = []
    for row in db.execute("SELECT s.*,f.name,f.bytes,f.sha256,u.name AS author_name,v.name AS uploader_name FROM topic_candidates s JOIN handoff_files f ON f.id=s.file_id JOIN users u ON u.id=s.author_id JOIN users v ON v.id=s.uploader_id WHERE s.topic_id=? ORDER BY s.created_at DESC,s.version DESC,s.id", (tid,)):
        item = dict(row)
        item.pop("request_hash")
        item.pop("request_id")
        item["file_url"] = f"/api/collaboration/topics/{tid}/candidates/{row['id']}/file"
        items.append(item)
    return items


def validate_backup(db):
    """Reject semantic corruption even when an archive's hashes were rewritten."""
    for q in db.execute("SELECT * FROM lead_qualifications"):
        events = db.execute("SELECT * FROM qualification_events WHERE member_id=? ORDER BY version", (q["member_id"],)).fetchall()
        if ([e["version"] for e in events] != list(range(1, q["version"] + 1)) or events[-1]["enabled"] != q["enabled"]):
            raise ValueError("负责人资格历史不完整。")
    for topic in db.execute("SELECT * FROM collaboration_topics"):
        if not topic["theme"].strip() or not db.execute("SELECT 1 FROM topic_participants WHERE topic_id=? AND member_id=? AND active=1", (topic["id"], topic["lead_id"])).fetchone():
            raise ValueError("主题负责人或参与归属无效。")
        events = db.execute("SELECT * FROM topic_events WHERE topic_id=? ORDER BY version", (topic["id"],)).fetchall()
        if [e["version"] for e in events] != list(range(1, topic["version"] + 1)):
            raise ValueError("主题维护历史不完整。")
        for event in events:
            try:
                snapshot = json.loads(event["snapshot_json"])
                ids = snapshot["participant_ids"]
                if (snapshot["id"] != topic["id"] or snapshot["lead_id"] != topic["lead_id"] or snapshot["version"] != event["version"]
                        or not isinstance(ids, list) or len(ids) != len(set(ids)) or snapshot["lead_id"] not in ids
                        or any(not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() for uid in ids)):
                    raise ValueError()
            except (TypeError, KeyError, ValueError):
                raise ValueError("主题历史归属无效。") from None
        last = json.loads(events[-1]["snapshot_json"])
        members = sorted(r[0] for r in db.execute("SELECT member_id FROM topic_participants WHERE topic_id=? AND active=1", (topic["id"],)))
        if any(last[k] != topic[k] for k in ("theme", "due_on", "lead_id", "version")) or sorted(last["participant_ids"]) != members:
            raise ValueError("主题与最新历史不一致。")
    for row in db.execute("SELECT s.*,f.uploader_id AS file_uploader,f.created_at AS file_created FROM topic_candidates s JOIN handoff_files f ON f.id=s.file_id"):
        topic = db.execute("SELECT * FROM collaboration_topics WHERE id=?", (row["topic_id"],)).fetchone()
        history = db.execute("SELECT snapshot_json FROM topic_events WHERE topic_id=? AND version=?", (row["topic_id"], row["topic_version"])).fetchone()
        if (not topic or not history or row["author_id"] != row["uploader_id"] or row["file_uploader"] != row["uploader_id"]
                or row["author_id"] not in json.loads(history[0])["participant_ids"]
                or not re.fullmatch(r"[a-f0-9]{64}", row["request_hash"])):
            raise ValueError("候选交接归属或原件身份无效。")
    for row in db.execute("SELECT topic_id,author_id,COUNT(*) AS total,MAX(version) AS latest FROM topic_candidates GROUP BY topic_id,author_id"):
        if row["total"] != row["latest"]:
            raise ValueError("候选交接版本不连续。")


def register(app, ctx):
    db, user, body = ctx.db, ctx.user, ctx.body

    @app.get("/api/collaboration/qualifications")
    def qualifications():
        ctx.admin()
        items = [dict(r) for r in db().execute("SELECT u.id,u.name,u.active,COALESCE(q.enabled,0) AS enabled,COALESCE(q.version,0) AS version FROM users u LEFT JOIN lead_qualifications q ON q.member_id=u.id ORDER BY u.name")]
        events = [dict(r) for r in db().execute("SELECT e.*,u.name AS actor_name FROM qualification_events e JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC")]
        return jsonify(items=items, events=events)

    @app.put("/api/collaboration/qualifications/<uid>")
    def set_qualification(uid):
        ctx.admin()
        data = body()
        with db():
            db().execute("BEGIN IMMEDIATE")
            if not db().execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                abort(404)
            old = db().execute("SELECT * FROM lead_qualifications WHERE member_id=?", (uid,)).fetchone()
            version = old["version"] if old else 0
            if type(data.get("version")) is not int or data["version"] != version:
                abort(409, "资格登记已变化，请刷新后重试。")
            if type(data.get("enabled")) is not bool:
                abort(400, "负责人资格格式不正确。")
            db().execute("INSERT OR REPLACE INTO lead_qualifications VALUES (?,?,?)", (uid, int(data["enabled"]), version + 1))
            db().execute("INSERT INTO qualification_events(member_id,actor_id,enabled,version,created_at) VALUES (?,?,?,?,?)", (uid, user()["id"], int(data["enabled"]), version + 1, now()))
        return jsonify(id=uid, version=version + 1)

    @app.get("/api/collaboration/topics")
    def topics():
        actor = user()
        scope = request.args.get("scope", "participating")
        if scope not in {"participating", "leading", "maintenance"}:
            abort(400, "工作范围不正确。")
        if scope == "maintenance":
            ctx.admin()
        items = []
        for row in db().execute("SELECT * FROM collaboration_topics ORDER BY updated_at DESC,id"):
            if not can_read(db(), actor, row):
                continue
            item = projection(db(), actor, row)
            if scope == "leading" and row["lead_id"] != actor["id"]:
                continue
            if scope == "participating" and not item["can_submit"]:
                continue
            items.append(item)
        return jsonify(items=items, can_create=qualified(db(), actor["id"]))

    @app.post("/api/collaboration/topics")
    def create_topic():
        data = body()
        with db():
            db().execute("BEGIN IMMEDIATE")
            actor = user()
            if not qualified(db(), actor["id"]):
                abort(403, "发起主题需要管理员登记有效负责人资格。")
            theme, due, ids = topic_values(db(), data)
            tid, stamp = uuid.uuid4().hex, now()
            db().execute("INSERT INTO collaboration_topics VALUES (?,?,?,?,1,?,?)", (tid, theme, actor["id"], due, stamp, stamp))
            db().executemany("INSERT INTO topic_participants VALUES (?,?,1)", [(tid, uid) for uid in set(ids) | {actor["id"]}])
            save_topic_event(db(), tid, actor["id"])
        return jsonify(id=tid), 201

    @app.get("/api/collaboration/topics/<tid>")
    def topic_detail(tid):
        row = topic_for(db(), user(), tid)
        return jsonify(projection(db(), user(), row))

    @app.get("/api/collaboration/topics/<tid>/history")
    def collaboration_topic_history(tid):
        topic_for(db(), user(), tid)
        items = []
        for e in db().execute("SELECT e.*,u.name AS actor_name FROM topic_events e JOIN users u ON u.id=e.actor_id WHERE topic_id=? ORDER BY version DESC", (tid,)):
            snapshot = json.loads(e["snapshot_json"])
            items.append({"version": e["version"], "actor_name": e["actor_name"], "created_at": e["created_at"], "theme": snapshot["theme"], "due_on": snapshot["due_on"], "participants": [{"id": uid, "name": db().execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()[0]} for uid in snapshot["participant_ids"]]})
        return jsonify(items=items)

    @app.put("/api/collaboration/topics/<tid>")
    def edit_topic(tid):
        data = body()
        with db():
            db().execute("BEGIN IMMEDIATE")
            row = topic_for(db(), user(), tid, manage=True)
            check_version(data, row)
            theme, due, ids = topic_values(db(), data)
            db().execute("UPDATE collaboration_topics SET theme=?,due_on=?,version=version+1,updated_at=? WHERE id=?", (theme, due, now(), tid))
            db().execute("UPDATE topic_participants SET active=0 WHERE topic_id=?", (tid,))
            db().executemany("INSERT INTO topic_participants VALUES (?,?,1) ON CONFLICT(topic_id,member_id) DO UPDATE SET active=1", [(tid, uid) for uid in set(ids) | {row["lead_id"]}])
            save_topic_event(db(), tid, user()["id"])
        return jsonify(id=tid, version=row["version"] + 1)

    @app.get("/api/collaboration/topics/<tid>/candidates")
    def topic_candidates_list(tid):
        topic_for(db(), user(), tid)
        return jsonify(items=candidate_projection(db(), tid))

    @app.post("/api/collaboration/topics/<tid>/candidates")
    def submit_candidate(tid):
        data = body()
        topic_for(db(), user(), tid)
        uploaded = handoff_files.read_upload(request.files.get("file"))
        request_id, note = data.get("request_id"), data.get("note", "")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            abort(400, "提交请求标识无效，请重新打开提交表单。")
        if not isinstance(note, str) or len(note) > 4000 or data.get("sharing_confirmed") is not True:
            abort(400, "请检查简短说明并确认文件可在本期共享。")
        request_hash = hashlib.sha256(json.dumps({"name": uploaded[0], "sha256": hashlib.sha256(uploaded[2]).hexdigest(), "note": note.strip(), "version": data.get("version"), "topic_version": data.get("topic_version")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with handoff_files.transaction(db()) as created:
            actor = user()
            topic = topic_for(db(), actor, tid)
            if not db().execute("SELECT 1 FROM topic_participants WHERE topic_id=? AND member_id=? AND active=1", (tid, actor["id"])).fetchone():
                abort(403, "只有本期参与者可提交自己的选题报告。")
            previous = db().execute("SELECT id,request_hash FROM topic_candidates WHERE topic_id=? AND uploader_id=? AND request_id=?", (tid, actor["id"], request_id)).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    abort(409, "此请求已提交不同内容，请重新打开表单提交新版本。")
                return jsonify(id=previous["id"], reused=True)
            if type(data.get("topic_version")) is not int or data["topic_version"] != topic["version"]:
                abort(409, "本期主题或参与者已更新。文件和说明仍保留，请核对后重试。")
            latest = db().execute("SELECT COALESCE(MAX(version),0) FROM topic_candidates WHERE topic_id=? AND author_id=?", (tid, actor["id"])).fetchone()[0]
            if type(data.get("version")) is not int or data["version"] != latest:
                abort(409, "你已提交更新版本。文件和说明仍保留，请核对后重试。")
            fid = handoff_files.save_original(db(), ctx.data_dir, actor["id"], uploaded, created)
            sid = uuid.uuid4().hex
            db().execute("INSERT INTO topic_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)", (sid, tid, actor["id"], actor["id"], latest + 1, topic["version"], fid, note.strip(), request_id, request_hash, now()))
        return jsonify(id=sid, version=latest + 1), 201

    @app.get("/api/collaboration/topics/<tid>/candidates/<sid>/file")
    def candidate_file(tid, sid):
        topic_for(db(), user(), tid)
        row = db().execute("SELECT f.* FROM topic_candidates s JOIN handoff_files f ON f.id=s.file_id WHERE s.topic_id=? AND s.id=?", (tid, sid)).fetchone()
        if not row:
            abort(404)
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row["name"])
