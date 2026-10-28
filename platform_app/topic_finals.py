"""Final decisions and immutable issue adoptions, linked to existing records."""
import json
import uuid
from pathlib import Path

from flask import abort, jsonify, request, send_file

from . import collaboration, handoff_files, topic_review as review
from .record_revisions import RecordRevisions
from .store import connect, now

SCHEMA_VERSION = 23
SCHEMA = [
    "CREATE TABLE topic_finals(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), assignment_id TEXT NOT NULL, submission_id TEXT UNIQUE NOT NULL REFERENCES topic_manuscripts(id), meeting_id TEXT NOT NULL REFERENCES topic_meetings(id), topic_version INTEGER NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), qualification_version INTEGER NOT NULL, record_id TEXT NOT NULL REFERENCES records(id), note TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,assignment_id,actor_id,request_id))",
    "CREATE TABLE topic_summaries(id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES collaboration_topics(id), version INTEGER NOT NULL CHECK(version>0), topic_version INTEGER NOT NULL, author_id TEXT NOT NULL REFERENCES users(id), uploader_id TEXT NOT NULL REFERENCES users(id), file_id TEXT UNIQUE NOT NULL REFERENCES handoff_files(id), record_id TEXT NOT NULL REFERENCES records(id), note TEXT NOT NULL, adoptions_json TEXT NOT NULL, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(topic_id,version), UNIQUE(topic_id,uploader_id,request_id))",
]


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        previous = int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0])
        if previous >= SCHEMA_VERSION:
            return
        if previous != 22:
            raise ValueError("定稿结构升级须先完成期刊编译结构22。")
        from .maintenance import create_backup
        backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA:
                db.execute(statement)
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('topic_finals_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def access(db, actor, data_dir):
    return RecordRevisions(db, actor, Path(data_dir) / "uploads")


def clean_request(row):
    item = dict(row)
    for key in ("request_id", "request_hash", "request_json"):
        item.pop(key)
    return item


def record_reference(db, actor, rid):
    # Record ACL is independent of the right to read a topic's submitted files.
    service = access(db, actor, ".")
    from . import identity
    row = identity.resolve(db, "records", rid)
    return {"id": row["id"], "title": row["title"], "author_confirmed": bool(row["author_confirmed"])} if row and service.visible(row) else None


def final_projection(db, actor, tid):
    items = []
    for row in db.execute("SELECT f.*,u.name AS actor_name,s.file_id,s.version,s.author_id,a.name AS author_name,v.name AS uploader_name,s.uploader_id FROM topic_finals f JOIN users u ON u.id=f.actor_id JOIN topic_manuscripts s ON s.id=f.submission_id JOIN users a ON a.id=s.author_id JOIN users v ON v.id=s.uploader_id WHERE f.topic_id=? ORDER BY f.created_at DESC,f.id", (tid,)):
        item = review.file_metadata(db, tid, "finals", clean_request(row))
        meeting = db.execute("SELECT assignments_json FROM topic_meetings WHERE id=?", (row["meeting_id"],)).fetchone()
        assignment = next(a for a in json.loads(meeting[0]) if a["id"] == row["assignment_id"])
        item.update(title=assignment["title"], country=assignment["country"])
        item["record"] = record_reference(db, actor, item.pop("record_id"))
        items.append(item)
    return items


def summary_projection(db, actor, tid):
    finals = {f["id"]: f for f in final_projection(db, actor, tid)}
    items = []
    for row in db.execute("SELECT s.*,a.name AS author_name,u.name AS uploader_name FROM topic_summaries s JOIN users a ON a.id=s.author_id JOIN users u ON u.id=s.uploader_id WHERE s.topic_id=? ORDER BY version DESC", (tid,)):
        item = review.file_metadata(db, tid, "summaries", clean_request(row))
        item["adoptions"] = [finals[fid] for fid in json.loads(item.pop("adoptions_json"))]
        item["record"] = record_reference(db, actor, item.pop("record_id"))
        items.append(item)
    return items


def enrich_workflow(db, actor, topic, workflow):
    finals = final_projection(db, actor, topic["id"])
    for a in workflow["assignments"]:
        a["finals"] = [f for f in finals if f["assignment_id"] == a["id"]]
        latest = a["submissions"][0] if a["submissions"] else None
        if latest and any(f["submission_id"] == latest["id"] for f in a["finals"]):
            a["status"] = "final"
    workflow["summaries"] = summary_projection(db, actor, topic["id"])
    return workflow


def record_works(db, actor, rid):
    """Reading a record alone never discloses a private process archive."""
    from . import identity
    origins = identity.origins(db, "records", rid)
    result = []
    for table, kind in (("topic_finals", "final"), ("topic_summaries", "summary")):
        for row in db.execute(f"SELECT id,topic_id,record_id FROM {table}"):
            if row["record_id"] not in origins:
                continue
            topic = db.execute("SELECT * FROM collaboration_topics WHERE id=?", (row["topic_id"],)).fetchone()
            if collaboration.can_read(db, actor, topic):
                items = final_projection(db, actor, topic["id"]) if kind == "final" else summary_projection(db, actor, topic["id"])
                item = next(x for x in items if x["id"] == row["id"])
                result.append({"topic_id": topic["id"], "theme": topic["theme"], "kind": kind, **item})
    return result


def referenced_files(db):
    return [r[0] for r in db.execute("SELECT file_id FROM topic_summaries")]


def prepare_export(db, records):
    """Already-authorized record projections, including their adopted originals."""
    files = {}
    def original(item):
        row = db.execute("SELECT * FROM handoff_files WHERE id=?", (item["file_id"],)).fetchone()
        item["path"] = "handoffs/" + row["stored_name"]
        files[row["id"]] = {**dict(row), "path": item["path"]}
        for adopted in item.get("adoptions", []):
            original(adopted)
    for record in records.values():
        for work in record.get("collaboration_works", []):
            original(work)
    return files


def validate_backup(db):
    """Validate frozen decisions against historical authority and exact versions."""
    def require(value):
        if not value:
            raise ValueError("定稿或整期汇总采用关系损坏。")

    for table in ("topic_finals", "topic_summaries"):
        for row in db.execute(f"SELECT * FROM {table}"):
            try:
                data = json.loads(row["request_json"])
                import re
                require(isinstance(data, dict) and data.get("request_id") == row["request_id"] and bool(re.fullmatch(r"[A-Za-z0-9_-]{8,100}", row["request_id"])))
                require(type(data.get("topic_version")) is int and data["topic_version"] == row["topic_version"])
                require(isinstance(data.get("note", ""), str) and data.get("note", "").strip() == row["note"] and len(row["note"]) <= 4000)
                event = db.execute("SELECT snapshot_json FROM topic_events WHERE topic_id=? AND version=?", (row["topic_id"], row["topic_version"])).fetchone()
                require(event is not None)
                topic = json.loads(event[0])
                actor = row["actor_id"] if table == "topic_finals" else row["uploader_id"]
                require(actor in topic["participant_ids"])
                require(db.execute("SELECT 1 FROM records WHERE id=?", (row["record_id"],)).fetchone())
                original = None
                if table == "topic_finals":
                    qualification = db.execute("SELECT enabled FROM qualification_events WHERE member_id=? AND version=?", (actor, row["qualification_version"])).fetchone()
                    require(topic["lead_id"] == actor and qualification and qualification[0] == 1)
                    submission = db.execute("SELECT * FROM topic_manuscripts WHERE id=? AND topic_id=? AND assignment_id=?", (row["submission_id"], row["topic_id"], row["assignment_id"])).fetchone()
                    meeting = db.execute("SELECT * FROM topic_meetings WHERE id=? AND topic_id=?", (row["meeting_id"], row["topic_id"])).fetchone()
                    require(submission and meeting and submission["meeting_id"] == meeting["id"])
                    require(data.get("submission_id") == submission["id"] and type(data.get("version")) is int and data["version"] == submission["version"])
                    require(data.get("meeting_version") == meeting["version"] and data.get("status") == "pending")
                    require(not db.execute("SELECT 1 FROM topic_returns WHERE submission_id=?", (submission["id"],)).fetchone())
                    author_id = submission["author_id"]
                else:
                    original = db.execute("SELECT * FROM handoff_files WHERE id=?", (row["file_id"],)).fetchone()
                    require(original and original["uploader_id"] == actor and data.get("author_id") == row["author_id"] and row["author_id"] in topic["participant_ids"])
                    require(type(data.get("version")) is int and data["version"] + 1 == row["version"])
                    adopted = json.loads(row["adoptions_json"])
                    require(isinstance(adopted, list) and 0 < len(adopted) <= 200 and len(set(adopted)) == len(adopted) and adopted == data.get("final_ids"))
                    for fid in adopted:
                        final = db.execute("SELECT * FROM topic_finals WHERE id=? AND topic_id=?", (fid, row["topic_id"])).fetchone()
                        require(final and final["created_at"] <= row["created_at"])
                    author_id = row["author_id"]
                if data.get("record_id"):
                    from . import identity
                    requested = identity.resolve(db, "records", data["record_id"])
                    saved = identity.resolve(db, "records", row["record_id"])
                    require(requested and saved and requested["id"] == saved["id"] and type(data.get("record_version")) is int and 0 < data["record_version"] <= requested["version"])
                else:
                    initial = db.execute("SELECT actor_id,snapshot_json FROM revisions WHERE target_type='record' AND target_id=? ORDER BY id LIMIT 1", (row["record_id"],)).fetchone()
                    require(initial and initial["actor_id"] == actor)
                    record = json.loads(initial["snapshot_json"])
                    require(record["kind"] == "compilation" and record["owner_id"] == actor and record["author_id"] == author_id and record["author_confirmed"] == int(actor == author_id) and json.loads(record["editors"]) == [])
                    require(record["visibility"] == data.get("visibility", "restricted"))
                identity = {"data": data, "file": [original["name"], original["sha256"]] if original else None}
                require(review.fingerprint(identity) == row["request_hash"])
            except (KeyError, TypeError, json.JSONDecodeError):
                raise ValueError("定稿与汇总请求依据损坏。") from None
    for series in db.execute("SELECT COUNT(*),MAX(version) FROM topic_summaries GROUP BY topic_id"):
        require(series[0] == series[1])


def register(app, ctx):
    db, user, body = ctx.db, ctx.user, ctx.body

    @app.post("/api/collaboration/topics/<tid>/assignments/<aid>/finals")
    def finalize(tid, aid):
        collaboration.topic_for(db(), user(), tid, manage=True)
        data = body()
        key, note = review.request_key(data), review.text(data.get("note", ""), "定稿依据")
        digest = review.request_identity(data, None)
        with handoff_files.transaction(db()):
            actor = user()
            topic = collaboration.topic_for(db(), actor, tid, manage=True)
            old = review.reused(db(), "topic_finals", tid, aid, actor, key, digest)
            if old:
                rid = db().execute("SELECT record_id FROM topic_finals WHERE id=?", (old["id"],)).fetchone()[0]
                return jsonify(id=old["id"], record_id=rid, reused=True)
            meeting, assignment = review.current_assignment(db(), tid, aid)
            review.expect_version(data, "topic_version", topic["version"])
            review.expect_version(data, "meeting_version", meeting["version"])
            latest = review.latest_manuscript(db(), tid, aid)
            if not latest or data.get("submission_id") != latest["id"] or latest["meeting_id"] != meeting["id"] or latest["author_id"] != assignment["author_id"]:
                abort(409, "当前会议、分工或稿件已经变化，请核对最新明确版本后再定稿。")
            review.expect_version(data, "version", latest["version"])
            if data.get("status") != "pending" or db().execute("SELECT 1 FROM topic_returns WHERE submission_id=? UNION ALL SELECT 1 FROM topic_finals WHERE submission_id=?", (latest["id"], latest["id"])).fetchone():
                abort(409, "这一版的审稿状态已经变化，请核对当前稿件；已保存决定仍保留。")
            original = db().execute("SELECT * FROM handoff_files WHERE id=?", (latest["file_id"],)).fetchone()
            handoff_files.original_path(ctx.data_dir, original)
            rid = access(db(), actor, ctx.data_dir).work_identity(data, latest["author_id"], assignment["title"])
            fid = uuid.uuid4().hex
            qv = db().execute("SELECT version FROM lead_qualifications WHERE member_id=?", (actor["id"],)).fetchone()[0]
            db().execute("INSERT INTO topic_finals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (fid, tid, aid, latest["id"], meeting["id"], topic["version"], actor["id"], qv, rid, note, key, digest, json.dumps(data, ensure_ascii=False), now()))
        return jsonify(id=fid, record_id=rid), 201

    @app.post("/api/collaboration/topics/<tid>/summaries")
    def save_summary(tid):
        collaboration.topic_for(db(), user(), tid)
        data = body()
        key, note = review.request_key(data), review.text(data.get("note", ""), "汇总说明")
        uploaded = handoff_files.read_upload(request.files.get("file"))
        digest = review.request_identity(data, uploaded)
        with handoff_files.transaction(db()) as created:
            actor = user()
            topic = collaboration.topic_for(db(), actor, tid)
            if not db().execute("SELECT 1 FROM topic_participants WHERE topic_id=? AND member_id=? AND active=1", (tid, actor["id"])).fetchone():
                abort(403, "只有本期参与者可以提交实际整期汇总。")
            old = db().execute("SELECT id,request_hash,record_id FROM topic_summaries WHERE topic_id=? AND uploader_id=? AND request_id=?", (tid, actor["id"], key)).fetchone()
            if old:
                if old["request_hash"] != digest:
                    abort(409, "此请求已经保存不同内容，请核对已有汇总。")
                return jsonify(id=old["id"], record_id=old["record_id"], reused=True)
            review.expect_version(data, "topic_version", topic["version"])
            version = db().execute("SELECT COALESCE(MAX(version),0) FROM topic_summaries WHERE topic_id=?", (tid,)).fetchone()[0]
            review.expect_version(data, "version", version)
            author = data.get("author_id")
            if not isinstance(author, str) or not db().execute("SELECT 1 FROM topic_participants p JOIN users u ON u.id=p.member_id WHERE p.topic_id=? AND p.member_id=? AND p.active=1 AND u.active=1", (tid, author)).fetchone():
                abort(400, "请选择本期有效的负责作者，代交仍等待作者本人确认。")
            adopted = data.get("final_ids")
            if not isinstance(adopted, list) or not 0 < len(adopted) <= 200 or not all(isinstance(f, str) for f in adopted) or len(set(adopted)) != len(adopted):
                abort(400, "请明确选择实际采用的定稿版本（最多200篇）。")
            for final_id in adopted:
                final = db().execute("SELECT s.file_id FROM topic_finals f JOIN topic_manuscripts s ON s.id=f.submission_id WHERE f.id=? AND f.topic_id=?", (final_id, tid)).fetchone()
                if not final:
                    abort(400, "采用的定稿版本不属于本期。")
                handoff_files.original_path(ctx.data_dir, db().execute("SELECT * FROM handoff_files WHERE id=?", (final[0],)).fetchone())
            rid = access(db(), actor, ctx.data_dir).work_identity(data, author, topic["theme"] + " · 整期汇总")
            file_id = handoff_files.save_original(db(), ctx.data_dir, actor["id"], uploaded, created)
            sid = uuid.uuid4().hex
            db().execute("INSERT INTO topic_summaries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid, tid, version + 1, topic["version"], author, actor["id"], file_id, rid, note, json.dumps(adopted), key, digest, json.dumps(data, ensure_ascii=False), now()))
        return jsonify(id=sid, record_id=rid, version=version + 1), 201

    @app.get("/api/collaboration/topics/<tid>/finals/<fid>/file")
    def final_file(tid, fid):
        collaboration.topic_for(db(), user(), tid)
        row = db().execute("SELECT o.* FROM topic_finals f JOIN topic_manuscripts s ON s.id=f.submission_id JOIN handoff_files o ON o.id=s.file_id WHERE f.id=? AND f.topic_id=?", (fid, tid)).fetchone()
        if not row:
            abort(404)
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row["name"])

    @app.get("/api/collaboration/topics/<tid>/summaries/<sid>/file")
    def summary_file(tid, sid):
        collaboration.topic_for(db(), user(), tid)
        row = db().execute("SELECT o.* FROM topic_summaries s JOIN handoff_files o ON o.id=s.file_id WHERE s.id=? AND s.topic_id=?", (sid, tid)).fetchone()
        if not row:
            abort(404)
        return send_file(handoff_files.original_path(ctx.data_dir, row), as_attachment=True, download_name=row["name"])
