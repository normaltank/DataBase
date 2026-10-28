"""Immutable meeting decisions and per-article manuscript handoffs.

Topic membership permits reading; only the current qualified lead decides and
reviews. Each adopted article has its own series, independent of its author.
"""
import hashlib
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from flask import abort, jsonify, request, send_file

from . import collaboration, handoff_files
from .store import connect, now

SCHEMA_VERSION = 21
SCHEMA = [
    "CREATE TABLE topic_meetings(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), version INTEGER NOT NULL CHECK(version>0), topic_version INTEGER NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), qualification_version INTEGER NOT NULL, note TEXT NOT NULL, assignments_json TEXT NOT NULL, file_id TEXT UNIQUE REFERENCES handoff_files(id), request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,version), UNIQUE(topic_id,actor_id,request_id))",
    "CREATE TABLE topic_manuscripts(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), assignment_id TEXT NOT NULL, meeting_id TEXT NOT NULL REFERENCES topic_meetings(id), topic_version INTEGER NOT NULL, author_id TEXT NOT NULL REFERENCES users(id), uploader_id TEXT NOT NULL REFERENCES users(id), version INTEGER NOT NULL CHECK(version>0), file_id TEXT UNIQUE NOT NULL REFERENCES handoff_files(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,assignment_id,version), UNIQUE(topic_id,assignment_id,uploader_id,request_id))",
    "CREATE TABLE topic_returns(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), assignment_id TEXT NOT NULL, submission_id TEXT UNIQUE NOT NULL REFERENCES topic_manuscripts(id), meeting_id TEXT NOT NULL REFERENCES topic_meetings(id), topic_version INTEGER NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), qualification_version INTEGER NOT NULL, file_id TEXT UNIQUE REFERENCES handoff_files(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,assignment_id,actor_id,request_id))",
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
            db.execute("INSERT OR REPLACE INTO settings VALUES ('topic_review_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def request_identity(data, uploaded):
    return fingerprint({"data": data, "file": [uploaded[0], hashlib.sha256(uploaded[2]).hexdigest()] if uploaded else None})


def text(value, label, limit=4000):
    if not isinstance(value, str) or len(value) > limit:
        abort(400, label + "格式不正确或过长。")
    return value.strip()


def request_key(data):
    key = data.get("request_id")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        abort(400, "提交请求标识无效，请重新打开表单。")
    return key


def latest_meeting(db, tid):
    return db.execute("SELECT * FROM topic_meetings WHERE topic_id=? ORDER BY version DESC LIMIT 1", (tid,)).fetchone()


def expect_version(data, key, expected):
    if type(data.get(key)) is not int or data[key] != expected:
        abort(409, "本期信息、会议决定或稿件已更新。当前文件与说明仍保留，请核对最新内容后继续。")


def file_metadata(db, tid, kind, item):
    if not item.get("file_id"):
        item["file_url"] = None
        return item
    original = db.execute("SELECT name,bytes,sha256 FROM handoff_files WHERE id=?", (item["file_id"],)).fetchone()
    item.update(dict(original))
    item["file_url"] = f"/api/collaboration/topics/{tid}/{kind}/{item['id']}/file"
    return item


def meeting_projection(db, tid):
    result = []
    for row in db.execute("SELECT m.*,u.name AS actor_name FROM topic_meetings m JOIN users u ON u.id=m.actor_id WHERE topic_id=? ORDER BY version DESC", (tid,)):
        item = dict(row)
        item["assignments"] = json.loads(item.pop("assignments_json"))
        item.pop("request_id")
        item.pop("request_hash")
        item.pop("request_json")
        result.append(file_metadata(db, tid, "meetings", item))
    return result


def workflow_projection(db, actor, topic):
    meetings = meeting_projection(db, topic["id"])
    assignments = [dict(a, active=True) for a in meetings[0]["assignments"]] if meetings else []
    known = {a["id"] for a in assignments}
    for meeting in meetings[1:]:
        for a in meeting["assignments"]:
            if a["id"] not in known:
                assignments.append(dict(a, active=False))
                known.add(a["id"])
    for a in assignments:
        a["author_name"] = db.execute("SELECT name FROM users WHERE id=?", (a["author_id"],)).fetchone()[0]
        a["submissions"] = []
        for row in db.execute("SELECT s.*,u.name AS author_name,v.name AS uploader_name FROM topic_manuscripts s JOIN users u ON u.id=s.author_id JOIN users v ON v.id=s.uploader_id WHERE s.topic_id=? AND s.assignment_id=? ORDER BY version DESC", (topic["id"], a["id"])):
            item = dict(row)
            for key in ("request_id", "request_hash", "request_json"):
                item.pop(key)
            a["submissions"].append(file_metadata(db, topic["id"], "submissions", item))
        a["returns"] = []
        for row in db.execute("SELECT r.*,u.name AS actor_name FROM topic_returns r JOIN users u ON u.id=r.actor_id WHERE r.topic_id=? AND r.assignment_id=? ORDER BY r.created_at DESC,r.id", (topic["id"], a["id"])):
            item = dict(row)
            for key in ("request_id", "request_hash", "request_json"):
                item.pop(key)
            a["returns"].append(file_metadata(db, topic["id"], "returns", item))
        latest = a["submissions"][0] if a["submissions"] else None
        a["status"] = ("returned" if any(r["submission_id"] == latest["id"] for r in a["returns"]) else "pending") if latest else "awaiting_submission"
        a["can_submit"] = a["active"] and a["author_id"] == actor["id"] and collaboration.can_read(db, actor, topic) and bool(db.execute("SELECT 1 FROM topic_participants WHERE topic_id=? AND member_id=? AND active=1", (topic["id"], actor["id"])).fetchone())
    from .topic_finals import enrich_workflow
    return enrich_workflow(db, actor, topic, {"meeting_version": meetings[0]["version"] if meetings else 0, "meetings": meetings, "assignments": assignments})


def current_assignment(db, tid, aid):
    meeting = latest_meeting(db, tid)
    assignment = next((a for a in json.loads(meeting["assignments_json"]) if a["id"] == aid), None) if meeting else None
    if not assignment:
        abort(404, "文章分工不存在或已不在本期当前采用决定中，历史稿件仍保留。")
    return meeting, assignment


def latest_manuscript(db, tid, aid):
    return db.execute("SELECT * FROM topic_manuscripts WHERE topic_id=? AND assignment_id=? ORDER BY version DESC LIMIT 1", (tid, aid)).fetchone()


def referenced_files(db):
    return [row[0] for table in ("topic_meetings", "topic_manuscripts", "topic_returns") for row in db.execute(f"SELECT file_id FROM {table} WHERE file_id IS NOT NULL")]


def validate_backup(db):
    """Check historical authority against saved versions, never today's roster."""
    def require(condition):
        if not condition:
            raise ValueError("会议、稿件或退回历史归属无效。")

    def request_data(row):
        try:
            data = json.loads(row["request_json"])
            require(isinstance(data, dict) and data.get("request_id") == row["request_id"] and bool(re.fullmatch(r"[A-Za-z0-9_-]{8,100}", row["request_id"])))
            original = db.execute("SELECT * FROM handoff_files WHERE id=?", (row["file_id"],)).fetchone() if row["file_id"] else None
            require(not row["file_id"] or original is not None)
            identity = {"data": data, "file": [original["name"], original["sha256"]] if original else None}
            require(fingerprint(identity) == row["request_hash"])
            require(isinstance(data.get("note", ""), str) and data.get("note", "").strip() == row["note"] and len(row["note"]) <= 4000)
            require(type(data.get("topic_version")) is int and data["topic_version"] == row["topic_version"])
            return data, original
        except (TypeError, KeyError, json.JSONDecodeError):
            raise ValueError("交接请求依据损坏。") from None

    def history_for(row, actor):
        event = db.execute("SELECT snapshot_json FROM topic_events WHERE topic_id=? AND version=?", (row["topic_id"], row["topic_version"])).fetchone()
        require(event is not None)
        snapshot = json.loads(event[0])
        require(actor in snapshot["participant_ids"])
        return snapshot

    def lead_for(row):
        snapshot = history_for(row, row["actor_id"])
        qualification = db.execute("SELECT enabled FROM qualification_events WHERE member_id=? AND version=?", (row["actor_id"], row["qualification_version"])).fetchone()
        require(snapshot["lead_id"] == row["actor_id"] and qualification is not None and qualification[0] == 1)

    for topic in db.execute("SELECT DISTINCT topic_id FROM topic_meetings"):
        meetings = db.execute("SELECT * FROM topic_meetings WHERE topic_id=? ORDER BY version", (topic[0],)).fetchall()
        require([m["version"] for m in meetings] == list(range(1, len(meetings) + 1)))
        known = set()
        for m in meetings:
            data, original = request_data(m)
            lead_for(m)
            require(type(data.get("version")) is int and data["version"] + 1 == m["version"])
            require(not original or original["uploader_id"] == m["actor_id"])
            snapshot = history_for(m, m["actor_id"])
            try:
                assignments, raw = json.loads(m["assignments_json"]), data.get("assignments", [])
                require(isinstance(assignments, list) and isinstance(raw, list) and len(assignments) == len(raw) <= 200)
                require(len({a["id"] for a in assignments}) == len(assignments))
                for a, source in zip(assignments, raw):
                    require(isinstance(source, dict) and bool(re.fullmatch(r"[a-f0-9]{32}", a["id"])))
                    require((source.get("id") == a["id"] and a["id"] in known) if source.get("id") is not None else a["id"] not in known)
                    for key, limit in (("title", 500), ("source", 4000), ("candidate_item", 1000), ("country", 500)):
                        require(isinstance(source.get(key, ""), str) and source.get(key, "").strip() == a[key] and len(a[key]) <= limit)
                    require(bool(a["title"]) and a["author_id"] == source.get("author_id") and a["author_id"] in snapshot["participant_ids"])
                    cid = source.get("candidate_id") or None
                    require(a["candidate_id"] == cid and (not cid or db.execute("SELECT 1 FROM topic_candidates WHERE id=? AND topic_id=?", (cid, m["topic_id"])).fetchone() is not None))
                known.update(a["id"] for a in assignments)
                require(bool(m["note"] or original or assignments))
            except (KeyError, TypeError, json.JSONDecodeError):
                raise ValueError("会议采用与分工历史损坏。") from None

    for row in db.execute("SELECT * FROM topic_manuscripts"):
        data, original = request_data(row)
        meeting = db.execute("SELECT * FROM topic_meetings WHERE id=? AND topic_id=?", (row["meeting_id"], row["topic_id"])).fetchone()
        require(meeting is not None)
        assignment = next((a for a in json.loads(meeting["assignments_json"]) if a["id"] == row["assignment_id"]), None)
        require(assignment is not None and assignment["author_id"] == row["author_id"] == row["uploader_id"])
        history_for(row, row["uploader_id"])
        require(original is not None and original["uploader_id"] == row["uploader_id"])
        require(type(data.get("version")) is int and data["version"] + 1 == row["version"] and data.get("meeting_version") == meeting["version"])
    for series in db.execute("SELECT topic_id,assignment_id,COUNT(*),MAX(version) FROM topic_manuscripts GROUP BY topic_id,assignment_id"):
        require(series[2] == series[3])
    for row in db.execute("SELECT * FROM topic_returns"):
        data, original = request_data(row)
        lead_for(row)
        submission = db.execute("SELECT * FROM topic_manuscripts WHERE id=? AND topic_id=? AND assignment_id=?", (row["submission_id"], row["topic_id"], row["assignment_id"])).fetchone()
        meeting = db.execute("SELECT * FROM topic_meetings WHERE id=? AND topic_id=?", (row["meeting_id"], row["topic_id"])).fetchone()
        require(submission is not None and data.get("submission_id") == row["submission_id"] and meeting is not None)
        require(data.get("meeting_version") == meeting["version"] and any(a["id"] == row["assignment_id"] for a in json.loads(meeting["assignments_json"])))
        require(not original or original["uploader_id"] == row["actor_id"])
        require(bool(row["note"] or original))
    all_files = referenced_files(db) + [r[0] for r in db.execute("SELECT file_id FROM topic_candidates")]
    require(len(all_files) == len(set(all_files)))


def reused(db, table, tid, aid, actor, key, digest):
    column = "uploader_id" if table == "topic_manuscripts" else "actor_id"
    row = db.execute(f"SELECT id,request_hash FROM {table} WHERE topic_id=? AND assignment_id=? AND {column}=? AND request_id=?", (tid, aid, actor["id"], key)).fetchone()
    if row and row["request_hash"] != digest:
        abort(409, "此请求已保存不同内容。文件与说明仍保留，请核对最新历史。")
    return row


def assignment_values(db, tid, data):
    rows = data.get("assignments", [])
    if not isinstance(rows, list) or len(rows) > 200:
        abort(400, "采用文章与分工格式不正确（最多200项）。")
    known = {a["id"] for m in db.execute("SELECT assignments_json FROM topic_meetings WHERE topic_id=?", (tid,)) for a in json.loads(m[0])}
    active = {r[0] for r in db.execute("SELECT p.member_id FROM topic_participants p JOIN users u ON u.id=p.member_id WHERE p.topic_id=? AND p.active=1 AND u.active=1", (tid,))}
    result = []
    for raw in rows:
        if not isinstance(raw, dict):
            abort(400, "采用文章格式不正确。")
        aid = raw.get("id")
        if aid is not None and (not isinstance(aid, str) or aid not in known):
            abort(400, "文章分工不属于本期会议历史。")
        item = {"id": aid or uuid.uuid4().hex}
        for key, label, limit in (("title", "采用题名或报告项目", 500), ("source", "出处", 4000), ("candidate_item", "报告项目位置", 1000), ("country", "国家分工", 500)):
            item[key] = text(raw.get(key, ""), label, limit)
        item["author_id"] = raw.get("author_id")
        if not item["title"] or not isinstance(item["author_id"], str) or item["author_id"] not in active:
            abort(400, "请填写采用题名或报告项目，并选择本期有效研究员。")
        cid = raw.get("candidate_id")
        if cid is not None and not isinstance(cid, str):
            abort(400, "引用的选题报告版本格式不正确。")
        cid = cid or None
        if cid and (not isinstance(cid, str) or not db.execute("SELECT 1 FROM topic_candidates WHERE id=? AND topic_id=?", (cid, tid)).fetchone()):
            abort(400, "引用的选题报告版本不属于本期。")
        item["candidate_id"] = cid
        result.append(item)
    if len({a["id"] for a in result}) != len(result):
        abort(400, "同一文章分工不能重复。")
    return result


def register(app, ctx):
    db, user, body = ctx.db, ctx.user, ctx.body

    @app.get("/api/collaboration/topics/<tid>/workflow")
    def topic_workflow(tid):
        topic = collaboration.topic_for(db(), user(), tid)
        return jsonify(workflow_projection(db(), user(), topic))

    @app.post("/api/collaboration/topics/<tid>/meetings")
    def save_meeting(tid):
        collaboration.topic_for(db(), user(), tid, manage=True)
        data = body()
        key, note = request_key(data), text(data.get("note", ""), "会议决定")
        uploaded = handoff_files.read_upload(request.files["file"]) if request.files.get("file") and request.files["file"].filename else None
        request_hash = request_identity(data, uploaded)
        with handoff_files.transaction(db()) as created:
            actor = user()
            topic = collaboration.topic_for(db(), actor, tid, manage=True)
            previous = db().execute("SELECT id,request_hash FROM topic_meetings WHERE topic_id=? AND actor_id=? AND request_id=?", (tid, actor["id"], key)).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    abort(409, "此请求已保存不同决定，请核对历史后重新提交。")
                return jsonify(id=previous["id"], reused=True)
            latest = latest_meeting(db(), tid)
            version = latest["version"] if latest else 0
            expect_version(data, "version", version)
            expect_version(data, "topic_version", topic["version"])
            assignments = assignment_values(db(), tid, data)
            if not note and not uploaded and not assignments:
                abort(400, "请保存实际会议材料、简短决定或采用文章。")
            fid = handoff_files.save_original(db(), ctx.data_dir, actor["id"], uploaded, created) if uploaded else None
            mid = uuid.uuid4().hex
            qv = db().execute("SELECT version FROM lead_qualifications WHERE member_id=?", (actor["id"],)).fetchone()[0]
            db().execute("INSERT INTO topic_meetings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, tid, version + 1, topic["version"], actor["id"], qv, note, json.dumps(assignments, ensure_ascii=False), fid, key, request_hash, json.dumps(data, ensure_ascii=False), now()))
        return jsonify(id=mid, version=version + 1), 201

    @app.get("/api/collaboration/topics/<tid>/meetings/<mid>/file")
    def meeting_file(tid, mid):
        collaboration.topic_for(db(), user(), tid)
        row = db().execute("SELECT f.* FROM topic_meetings m JOIN handoff_files f ON f.id=m.file_id WHERE m.topic_id=? AND m.id=?", (tid, mid)).fetchone()
        if not row:
            abort(404)
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row["name"])

    @app.post("/api/collaboration/topics/<tid>/assignments/<aid>/submissions")
    def submit_manuscript(tid, aid):
        collaboration.topic_for(db(), user(), tid)
        data = body()
        key, note = request_key(data), text(data.get("note", ""), "交稿说明")
        uploaded = handoff_files.read_upload(request.files.get("file"))
        digest = request_identity(data, uploaded)
        with handoff_files.transaction(db()) as created:
            actor = user()
            topic = collaboration.topic_for(db(), actor, tid)
            meeting, assignment = current_assignment(db(), tid, aid)
            if assignment["author_id"] != actor["id"] or not db().execute("SELECT 1 FROM topic_participants WHERE topic_id=? AND member_id=? AND active=1", (tid, actor["id"])).fetchone():
                abort(403, "只有该文章当前分工的编译者可提交自己的稿件。")
            previous = reused(db(), "topic_manuscripts", tid, aid, actor, key, digest)
            if previous:
                return jsonify(id=previous["id"], reused=True)
            expect_version(data, "topic_version", topic["version"])
            expect_version(data, "meeting_version", meeting["version"])
            latest = latest_manuscript(db(), tid, aid)
            version = latest["version"] if latest else 0
            expect_version(data, "version", version)
            fid = handoff_files.save_original(db(), ctx.data_dir, actor["id"], uploaded, created)
            sid = uuid.uuid4().hex
            db().execute("INSERT INTO topic_manuscripts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid, tid, aid, meeting["id"], topic["version"], assignment["author_id"], actor["id"], version + 1, fid, note, key, digest, json.dumps(data, ensure_ascii=False), now()))
        return jsonify(id=sid, version=version + 1), 201

    @app.post("/api/collaboration/topics/<tid>/assignments/<aid>/returns")
    def return_manuscript(tid, aid):
        collaboration.topic_for(db(), user(), tid, manage=True)
        data = body()
        key, note = request_key(data), text(data.get("note", ""), "退回意见")
        uploaded = handoff_files.read_upload(request.files["file"]) if request.files.get("file") and request.files["file"].filename else None
        if not note and not uploaded:
            abort(400, "请填写退回意见或提交批注文件。")
        digest = request_identity(data, uploaded)
        with handoff_files.transaction(db()) as created:
            actor = user()
            topic = collaboration.topic_for(db(), actor, tid, manage=True)
            meeting, assignment = current_assignment(db(), tid, aid)
            previous = reused(db(), "topic_returns", tid, aid, actor, key, digest)
            if previous:
                return jsonify(id=previous["id"], reused=True)
            expect_version(data, "topic_version", topic["version"])
            expect_version(data, "meeting_version", meeting["version"])
            latest = latest_manuscript(db(), tid, aid)
            if not latest or data.get("submission_id") != latest["id"]:
                abort(409, "审阅的稿件已变化，不能将意见写到另一版。文件与说明仍保留，请核对最新原件。")
            if db().execute("SELECT 1 FROM topic_returns WHERE submission_id=?", (latest["id"],)).fetchone():
                abort(409, "这一版已经退回，原退回意见继续保留，请等研究员修改后重交。")
            if db().execute("SELECT 1 FROM topic_finals WHERE submission_id=?", (latest["id"],)).fetchone():
                abort(409, "这一版已经确认定稿；此前定稿决定继续留档，新稿请另行提交。")
            fid = handoff_files.save_original(db(), ctx.data_dir, actor["id"], uploaded, created) if uploaded else None
            rid = uuid.uuid4().hex
            qv = db().execute("SELECT version FROM lead_qualifications WHERE member_id=?", (actor["id"],)).fetchone()[0]
            db().execute("INSERT INTO topic_returns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, tid, aid, latest["id"], meeting["id"], topic["version"], actor["id"], qv, fid, note, key, digest, json.dumps(data, ensure_ascii=False), now()))
        return jsonify(id=rid), 201

    def manuscript_file(tid, sid, table):
        collaboration.topic_for(db(), user(), tid)
        row = db().execute(f"SELECT f.* FROM {table} s JOIN handoff_files f ON f.id=s.file_id WHERE s.topic_id=? AND s.id=?", (tid, sid)).fetchone()
        if not row:
            abort(404)
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row["name"])

    @app.get("/api/collaboration/topics/<tid>/submissions/<sid>/file")
    def submission_file(tid, sid):
        return manuscript_file(tid, sid, "topic_manuscripts")

    @app.get("/api/collaboration/topics/<tid>/returns/<rid>/file")
    def return_file(tid, rid):
        return manuscript_file(tid, rid, "topic_returns")

    @app.get("/api/collaboration/topics/<tid>/materials/export")
    def export_process(tid):
        topic = collaboration.topic_for(db(), user(), tid)
        workflow = workflow_projection(db(), user(), topic)
        candidates = collaboration.candidate_projection(db(), tid)
        payload = {"format": "topic-process-v1", "coverage": "本期已提交的选题报告、会议决定、稿件与退回意见、定稿决定、整期汇总及固定采用版本；不含未提交文件或关联成果正文", "exported_at": now(), "topic": collaboration.projection(db(), user(), topic), "candidates": candidates, "workflow": workflow, "files": []}
        originals = candidates + workflow["meetings"] + workflow["summaries"] + [r for a in workflow["assignments"] for key in ("submissions", "returns", "finals") for r in a[key]]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in originals:
                if not item.get("file_id"):
                    continue
                original = db().execute("SELECT * FROM handoff_files WHERE id=?", (item["file_id"],)).fetchone()
                item["path"] = "originals/" + original["stored_name"]
                if any(f["file_id"] == original["id"] for f in payload["files"]):
                    continue
                payload["files"].append({"file_id": original["id"], "name": original["name"], "path": item["path"], "sha256": original["sha256"], "bytes": original["bytes"]})
                archive.writestr(item["path"], handoff_files.original_path(ctx.data_dir, original).read_bytes())
            paths = {f["file_id"]: f["path"] for f in payload["files"]}
            for summary in workflow["summaries"]:
                for adopted in summary["adoptions"]:
                    adopted["path"] = paths[adopted["file_id"]]
            archive.writestr("manifest.json", json.dumps(payload, ensure_ascii=False, indent=2))
        collaboration.topic_for(db(), user(), tid)
        output.seek(0)
        return send_file(output, mimetype="application/zip", as_attachment=True, download_name="topic-process-" + tid + ".zip")
