import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .store import connect, decoded, initialize, now, save_revision
from . import source_catalog, workflow, evidence, identity, operations, reading

ROOT = Path(__file__).resolve().parent.parent
RECORD_FIELDS = ["kind", "title", "original_title", "authors", "source_id", "serial_id", "publication_title",
                 "published_on", "language", "abstract", "keywords", "countries", "doi", "url", "visibility", "unresolved_refs"] + list(workflow.RECORD_DEFAULTS) + workflow.EVIDENCE_FIELDS
SOURCE_FIELDS = ["name", "original_name", "kind", "classification", "location", "country", "research_scope",
                 "website", "catalogue_url", "host_id", "publisher_id", "issn", "scope_status", "notes"] + list(workflow.SOURCE_DEFAULTS)
KINDS = {"research_article", "journal_article", "report", "compilation", "book_section", "book", "book_review",
         "conference_abstract", "thesis", "presentation", "speech", "policy", "news", "other"}
KINDS |= workflow.CONTENT_KINDS
SOURCE_KINDS = {"think_tank", "institution", "journal", "serial", "portal", "registry_publication"}


def relationship_ids(value):
    return list(dict.fromkeys(x.strip() for x in re.split(r"[|;,]", value) if x.strip()))


def create_app(data_dir=None, testing=False):
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    data_dir = Path(data_dir or os.environ.get("RESEARCH_DATA_DIR", ROOT / "data"))
    initialize(data_dir)
    key_path = data_dir / ".session-key"
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32), encoding="ascii")
    app.config.update(SECRET_KEY=key_path.read_text(encoding="ascii"), TESTING=testing,
                      MAX_CONTENT_LENGTH=21 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Strict", PERMANENT_SESSION_LIFETIME=28800,
                      TRUSTED_HOSTS=["127.0.0.1", "localhost"], DATA_DIR=data_dir)

    def db():
        if "db" not in g:
            g.db = connect(data_dir / "platform.sqlite3")
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop("db", None)
        if connection:
            connection.close()

    def user():
        uid = session.get("uid")
        result = db().execute("SELECT id,username,name,role,credential_version FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        if not result or session.get("credential_version", 0) != result["credential_version"]:
            abort(401, "请先登录。")
        return {k: result[k] for k in ["id", "username", "name", "role"]}

    def admin():
        if user()["role"] != "admin":
            abort(403, "此操作需要资料管理员权限。")

    @app.before_request
    def protect_request():
        if request.path.startswith("/api/"):
            if request.path not in ["/api/session", "/api/login"]:
                user()
            if request.method not in ["GET", "HEAD", "OPTIONS"]:
                origin = request.headers.get("Origin")
                if origin and origin != request.host_url.rstrip("/"):
                    abort(403, "请求来源不匹配。")
                expected = session.get("csrf")
                token = request.headers.get("X-CSRF-Token", "")
                if not expected or not secrets.compare_digest(expected, token):
                    abort(403, "页面已过期，请刷新后重试。")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(error):
        return jsonify(error="保存失败：数据关联或编号重复，请刷新后重试。"), 409

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok", app="research-commons", schema=int(db().execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]))

    @app.get("/api/session")
    def get_session():
        session.setdefault("csrf", secrets.token_hex(24))
        account = None
        if session.get("uid"):
            row = db().execute("SELECT id,username,name,role,credential_version FROM users WHERE id=? AND active=1", (session["uid"],)).fetchone()
            account = {k: row[k] for k in ["id", "username", "name", "role"]} if row and row["credential_version"] == session.get("credential_version", 0) else None
        return jsonify(user=account, csrf=session["csrf"])

    @app.post("/api/login")
    def login():
        payload = body()
        row = db().execute("SELECT * FROM users WHERE username=? AND active=1", (str(payload.get("username", "")),)).fetchone()
        if not row or not check_password_hash(row["password_hash"], str(payload.get("password", ""))):
            abort(401, "账号或密码不正确。")
        session.clear()
        session.update(uid=row["id"], csrf=secrets.token_hex(24), credential_version=row["credential_version"])
        session.permanent = True
        return jsonify(user=user(), csrf=session["csrf"])

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    def body():
        if request.is_json:
            obj = request.get_json()
        else:
            try:
                obj = json.loads(request.form.get("data", "{}"))
            except (TypeError, ValueError):
                abort(400, "表单格式不正确。")
        if not isinstance(obj, dict):
            abort(400, "表单格式不正确。")
        return obj

    def visible(r):
        u = user()
        if r["evidence_record_id"]:
            original = identity.resolve(db(), "records", r["evidence_record_id"])
            if not original or original["id"] == r["id"] or not visible(original):
                return False
        return r["visibility"] == "shared" or u["role"] == "admin" or r["owner_id"] == u["id"] or r["author_id"] == u["id"] or (u["id"] in json.loads(r["editors"]) and (r["kind"] not in workflow.PERSONAL_KINDS or r["author_confirmed"]))

    def editable(r):
        u = user()
        if r["kind"] == "directory_translation":
            return True
        if r["kind"] in workflow.PERSONAL_KINDS:
            return bool(r["author_confirmed"]) and (r["author_id"] == u["id"] or u["id"] in json.loads(r["editors"]))
        return u["role"] == "admin" or r["owner_id"] == u["id"] or u["id"] in json.loads(r["editors"])

    def get_record(rid, edit=False):
        r = identity.resolve(db(), "records", rid)
        if not r or not visible(r):
            abort(404, "资料不存在，或当前账号没有查看权限。")
        if edit and not editable(r):
            abort(403, "此内容尚待作者确认，或当前账号没有正文编辑授权。")
        return r

    def get_source(sid):
        row = identity.resolve(db(), "sources", sid)
        if not row:
            abort(404, "来源不存在。")
        return row

    def record_summary(r, favorite_ids=None):
        obj = {k: r[k] for k in ["id", "kind", "title", "original_title", "authors", "source_id", "serial_id",
               "publication_title", "published_on", "language", "abstract", "keywords", "countries", "status",
                "visibility", "owner_id", "version", "updated_at", "upstream_status", "aliases", "coverage", "author_id", "author_confirmed"]}
        source = db().execute("SELECT name FROM sources WHERE id=?", (r["source_id"],)).fetchone()
        obj["source_name"] = source[0] if source else ""
        obj["favorite"] = r["id"] in favorite_ids if favorite_ids is not None else bool(db().execute("SELECT 1 FROM favorites WHERE user_id=? AND record_id=?", (user()["id"], r["id"])).fetchone())
        obj["can_edit"] = editable(r)
        obj["has_attachment"] = bool(json.loads(r["attachment_ids"]))
        obj["related_source_ids"] = workflow.source_ids(db(), r["id"])
        text = " ".join(r[k] or "" for k in ["title", "original_title", "aliases", "abstract", "body_text", "coverage"])
        obj["search_snippet"] = workflow.snippet(text, request.args.get("q", "")) if request.args.get("q") else ""
        obj["evidence_record_id"] = r["evidence_record_id"]
        if "reading_authors" not in g:
            g.reading_authors = {u["id"]: u["name"] for u in db().execute("SELECT id,name FROM users")}
        if "reading_attachments" not in g:
            g.reading_attachments = {a["id"]: dict(a) for a in db().execute("SELECT id,record_id,name,stored_name FROM attachments")}
        obj["author_name"] = g.reading_authors.get(r["author_id"], "")
        obj["reading_access"] = reading.access(r, g.reading_attachments, data_dir)
        return obj

    def filtered_records(args):
        rows = [r for r in db().execute("SELECT * FROM records WHERE merged_into IS NULL ORDER BY published_on DESC, created_at DESC, id") if visible(r)]
        favorites = {r[0] for r in db().execute("SELECT record_id FROM favorites WHERE user_id=?", (user()["id"],))}
        q = args.get("q", "").strip().casefold()
        country = args.get("country", "").strip().casefold()
        source_names = {r["id"]: r["name"] + " " + r["original_name"] + " " + r["aliases"] for r in db().execute("SELECT * FROM sources")}
        collection_ids = None
        if args.get("collection"):
            get_collection(args["collection"])
            collection_ids = {r[0] for r in db().execute("SELECT record_id FROM collection_items WHERE collection_id=?", (args["collection"],))}
        results = []
        selected_source = get_source(args["source"])["id"] if args.get("source") else None
        for r in rows:
            if args.get("favorite") == "1" and r["id"] not in favorites:
                continue
            if collection_ids is not None and r["id"] not in collection_ids:
                continue
            associated = workflow.source_ids(db(), r["id"])
            if selected_source and selected_source not in [r["source_id"], r["serial_id"], *associated]:
                continue
            if args.get("kind") and r["kind"] != args["kind"]:
                continue
            if args.get("evidence_of") and r["evidence_record_id"] != args["evidence_of"]:
                continue
            if args.get("status") and r["status"] != args["status"]:
                continue
            if args.get("language") and args["language"] not in re.split(r"[;,|\s]+", r["language"]):
                continue
            if country and country not in r["countries"].casefold():
                continue
            if args.get("from") and (not r["published_on"] or r["published_on"] < args["from"]):
                continue
            if args.get("to") and (not r["published_on"] or r["published_on"] > args["to"]):
                continue
            if q:
                hay = " ".join(str(r[k]) for k in ["title", "original_title", "authors", "abstract", "keywords", "publication_title", "doi", "id", "aliases", "body_text", "coverage", "original_catalogue", "quote", "translation", "interpretation", "locator"]) + " " + " ".join(source_names.get(sid, "") for sid in [r["source_id"], r["serial_id"], *associated])
                if not all(word in hay.casefold() for word in q.split()):
                    continue
            results.append(r)
        if args.get("sort") == "updated":
            results.sort(key=lambda r: r["updated_at"], reverse=True)
        elif args.get("sort") == "title":
            results.sort(key=lambda r: r["title"].casefold())
        return results, favorites

    @app.get("/api/records")
    def records_list():
        rows, favorites = filtered_records(request.args)
        try:
            page = max(1, int(request.args.get("page", 1)))
            size = min(100, max(1, int(request.args.get("size", 12))))
        except ValueError:
            abort(400, "页码不正确。")
        return jsonify(items=[record_summary(r, favorites) for r in rows[(page - 1)*size:page*size]], total=len(rows), page=page, size=size)

    @app.get("/api/records/<rid>")
    def record_detail(rid):
        row = get_record(rid)
        rid = row["id"]
        obj = decoded(row)
        obj.update(record_summary(row))
        obj["owner_name"] = db().execute("SELECT name FROM users WHERE id=?", (row["owner_id"],)).fetchone()[0]
        last = db().execute("SELECT u.name,r.created_at FROM revisions r JOIN users u ON u.id=r.actor_id WHERE target_type='record' AND target_id=? ORDER BY r.id DESC LIMIT 1", (rid,)).fetchone()
        obj["last_modifier"] = dict(last) if last else None
        obj["linked_records"] = [record_summary(r) for r in db().execute("SELECT r.* FROM records r JOIN record_links l ON r.id=l.original_id WHERE l.report_id=?", (rid,)) if visible(r)]
        obj["cited_by"] = [record_summary(r) for r in db().execute("SELECT r.* FROM records r JOIN record_links l ON r.id=l.report_id WHERE l.original_id=?", (rid,)) if visible(r)]
        obj["attachments"] = [dict(a) for a in db().execute("SELECT id,name,bytes,created_at FROM attachments WHERE record_id=?", (rid,)) if a["id"] in obj["attachment_ids"]]
        obj["evidence_citations"] = evidence.citations(db(), rid, visible)
        obj["excerpts"] = [record_summary(r) for r in db().execute("SELECT * FROM records WHERE evidence_record_id=? AND merged_into IS NULL", (rid,)) if visible(r)]
        obj["evidence_snapshot"] = json.loads(row["evidence_snapshot_json"])
        obj["evidence_file_url"] = f"/api/records/{rid}/evidence-file" if row["evidence_attachment_id"] else ""
        obj["previous_ids"] = [x for x in identity.origins(db(), "records", rid) if x != rid]
        return jsonify(obj)

    @app.get("/api/records/<rid>/copy-text")
    def record_copy_text(rid):
        row = get_record(rid)
        adopted = evidence.citations(db(), row["id"], visible) if row["kind"] in {"research_report", "compilation"} else ()
        linked = [r for r in db().execute("SELECT r.* FROM records r JOIN record_links l ON r.id=l.original_id WHERE l.report_id=?", (row["id"],)) if visible(r)] if row["kind"] == "research_note" and not row["evidence_record_id"] else ()
        return jsonify(reading.copy_text(row, adopted, linked))

    def validate_text(data, fields, base=None):
        values = {}
        for field in fields:
            value = data.get(field, base[field] if base else "")
            if value is None:
                value = ""
            limit = 500000 if field in ["body_html", "body_text", "introduction_html", "introduction_text"] else 40000 if field in ["abstract", "notes", "unresolved_refs", "quote", "translation", "interpretation"] else 4000
            if not isinstance(value, str) or len(value) > limit:
                abort(400, "字段格式或长度不正确。")
            values[field] = value.strip()
        for field in ["url", "website", "catalogue_url"]:
            if values.get(field):
                try:
                    parsed = urlsplit(values[field])
                    valid = parsed.scheme in ["https", "http"] and parsed.hostname and not parsed.username and not parsed.password
                except ValueError:
                    valid = False
                if not valid:
                    abort(400, "网址需要使用有效的 http:// 或 https:// 地址。")
        return values

    def check_version(data, row):
        if type(data.get("version")) is not int or data["version"] != row["version"]:
            abort(409, "这条内容已被更新，请重新打开后再保存。")

    def validate_record(data, base=None):
        values = validate_text(data, RECORD_FIELDS, base)
        if base:
            values["aliases"] = identity.retained_aliases(db(), "records", base["id"], values["aliases"])
        values["kind"] = values["kind"] or "report"
        values["visibility"] = values["visibility"] or "shared"
        if not values["title"]:
            abort(400, "请填写题名。")
        if values["kind"] not in KINDS or values["visibility"] not in ["shared", "restricted"]:
            abort(400, "资料类型或共享范围不正确。")
        try:
            values["body_html"], values["body_text"] = workflow.clean_rich(values["body_html"])
        except ValueError as error:
            abort(400, str(error))
        if base and base["kind"] != values["kind"] and (base["kind"] in workflow.CONTENT_KINDS or values["kind"] == "directory_translation"):
            abort(400, "已保存内容的维护类型不能改变；请分别新建，避免改变既有编辑责任。")
        if values["kind"] == "directory_translation":
            if values["visibility"] != "shared" or data.get("editors", []):
                abort(400, "目录译稿由中心全体有效成员共同维护。")
            if not values["authors"] or not values["coverage"]:
                abort(400, "请填写编译者及年份、卷期或覆盖范围。")
        if values["kind"] in workflow.PERSONAL_KINDS:
            if base and base["kind"] in workflow.PERSONAL_KINDS:
                if "author_id" in data and data["author_id"] != base["author_id"]:
                    abort(403, "负责作者请通过确认流程维护。")
            else:
                author_id = data.get("author_id") or user()["id"]
                if not isinstance(author_id, str):
                    abort(400, "负责作者账号格式不正确。")
                if not db().execute("SELECT 1 FROM users WHERE id=? AND active=1", (author_id,)).fetchone():
                    abort(400, "请选择有效的负责作者账号。")
                values.update(author_id=author_id, author_confirmed=int(author_id == user()["id"]))
        if values["published_on"] and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", values["published_on"]):
            abort(400, "日期请填写为 YYYY、YYYY-MM 或 YYYY-MM-DD。")
        if values["published_on"]:
            try:
                parts = [int(x) for x in values["published_on"].split("-")]
                date(*(parts + [1] * (3-len(parts))))
            except ValueError:
                abort(400, "日期不存在，请检查年月日。")
        if base and values["kind"] in workflow.CONTENT_KINDS and base["kind"] not in workflow.CONTENT_KINDS:
            if db().execute("SELECT 1 FROM record_links WHERE original_id=?", (base["id"],)).fetchone() or db().execute("SELECT 1 FROM records WHERE evidence_record_id=?", (base["id"],)).fetchone():
                abort(409, "此资料已被成果或摘录作为原文引用，不能改成研究内容类型。")
        for field in ["source_id", "serial_id"]:
            values[field] = values[field] or None
            if values[field]:
                src = get_source(values[field])
                values[field] = src["id"]
                if field == "serial_id" and src["kind"] not in ["journal", "serial"]:
                    abort(400, "请选择期刊或连续出版物。")
        editors = data.get("editors", json.loads(base["editors"]) if base else [])
        if not isinstance(editors, list) or not all(isinstance(x, str) for x in editors):
            abort(400, "授权同事格式不正确。")
        manages_acl = (base["author_confirmed"] and base["author_id"] == user()["id"]) if base and base["kind"] in workflow.PERSONAL_KINDS else (not base or user()["id"] == base["owner_id"] or user()["role"] == "admin")
        if base and not manages_acl:
            if set(editors) != set(json.loads(base["editors"])) or values["visibility"] != base["visibility"]:
                abort(403, "只有负责作者可调整个人成果授权；其他资料由提交者或管理员调整。")
        if values["kind"] in workflow.PERSONAL_KINDS and not base and not values["author_confirmed"]:
            editors = []
        valid_users = {r[0] for r in db().execute("SELECT id FROM users WHERE active=1")}
        if not set(editors) <= valid_users:
            abort(400, "授权人员不存在。")
        values["editors"] = json.dumps(sorted(set(editors)))
        linked = data.get("linked_ids", None)
        if linked is None:
            linked = [r[0] for r in db().execute("SELECT original_id FROM record_links WHERE report_id=?", (base["id"],))] if base else []
        if not isinstance(linked, list) or not all(isinstance(x, str) for x in linked) or len(linked) > 100:
            abort(400, "原文关联格式不正确。")
        if linked and values["kind"] not in workflow.CONTENT_KINDS:
            abort(400, "编译成果可以关联原始资料。")
        canonical_links = []
        for rid in set(linked):
            original = get_record(rid)
            if original["kind"] in workflow.CONTENT_KINDS or (base and rid == base["id"]):
                abort(400, "请关联原始资料，不可关联成果本身。")
            canonical_links.append(original["id"])
        associated = data.get("related_source_ids", workflow.source_ids(db(), base["id"]) if base else [])
        if not isinstance(associated, list) or len(associated) > 100 or not all(isinstance(s, str) for s in associated):
            abort(400, "关联来源格式不正确。")
        associated = [get_source(sid)["id"] for sid in associated]
        if values["kind"] == "directory_translation" and not associated:
            abort(400, "请至少选择一个关联来源。")
        cited = evidence.validate(db(), data, values, base, get_record)
        return values, sorted(set(canonical_links)), sorted(set(associated)), cited

    def add_upload(rid, data, current_ids):
        file = request.files.get("file")
        if not file or not file.filename:
            return current_ids, None
        if data.get("sharing_confirmed") is not True:
            abort(400, "请确认附件可在所选范围内共享。")
        name = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if len(name) > 180 or any(ord(c) < 32 for c in name):
            abort(400, "文件名过长或包含无效字符。")
        suffix = Path(name).suffix.lower()
        if suffix not in [".pdf", ".docx", ".txt", ".md"]:
            abort(400, "支持 PDF、DOCX、TXT 和 Markdown，单文件最多 20 MB。")
        content = file.read(20 * 1024 * 1024 + 1)
        if not content or len(content) > 20 * 1024 * 1024:
            abort(400, "文件为空或超过 20 MB。")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            abort(400, "文件内容不是有效的 PDF。")
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if "word/document.xml" not in archive.namelist():
                        raise ValueError()
            except (ValueError, zipfile.BadZipFile):
                abort(400, "文件内容不是有效的 DOCX。")
        if suffix in [".txt", ".md"]:
            try:
                content.decode("utf-8-sig")
            except UnicodeDecodeError:
                abort(400, "文本文件请使用 UTF-8 编码。")
        aid = uuid.uuid4().hex
        path = data_dir / "uploads" / (aid + suffix)
        path.write_bytes(content)
        db().execute("INSERT INTO attachments VALUES (?,?,?,?,?,?,?)", (aid, rid, name, path.name, len(content), hashlib.sha256(content).hexdigest(), now()))
        return current_ids + [aid], path

    @app.post("/api/records")
    def new_record():
        data = body()
        values, linked, associated, cited = validate_record(data)
        # DOI duplicates are blocked even when the duplicate is restricted; no metadata is disclosed.
        if values["doi"] and db().execute("SELECT 1 FROM records WHERE lower(doi)=lower(?)", (values["doi"],)).fetchone():
            abort(409, "该 DOI 已登记，请联系管理员核对重复条目。")
        rid = "LOCAL-" + uuid.uuid4().hex[:12].upper()
        values.update(id=rid, owner_id=user()["id"], created_at=now(), updated_at=now())
        path = None
        try:
            with db():
                db().execute(f"INSERT INTO records ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
                attachments, path = add_upload(rid, data, [])
                db().execute("UPDATE records SET attachment_ids=? WHERE id=?", (json.dumps(attachments), rid))
                db().executemany("INSERT INTO record_links VALUES (?,?)", [(rid, x) for x in linked])
                workflow.set_sources(db(), rid, associated)
                evidence.save_links(db(), rid, cited, get_record)
                save_revision(db(), "record", rid, "提交资料", user()["id"])
        except Exception:
            if path:
                path.unlink(missing_ok=True)
            raise
        return jsonify(id=rid), 201

    @app.put("/api/records/<rid>")
    def edit_record(rid):
        row = get_record(rid, edit=True)
        rid = row["id"]
        data = body()
        check_version(data, row)
        values, linked, associated, cited = validate_record(data, row)
        if values["doi"] and db().execute("SELECT 1 FROM records WHERE lower(doi)=lower(?) AND id<>?", (values["doi"], rid)).fetchone():
            abort(409, "该 DOI 已登记，请联系管理员核对重复条目。")
        path = None
        try:
            with db():
                db().execute("BEGIN IMMEDIATE")
                check_version(data, get_record(rid, edit=True))
                if not db().execute("SELECT 1 FROM revisions WHERE target_type='record' AND target_id=?", (rid,)).fetchone():
                    save_revision(db(), "record", rid, "导入初始版本", "admin")
                attachment_ids, path = add_upload(rid, data, json.loads(row["attachment_ids"]))
                values.update(attachment_ids=json.dumps(attachment_ids), status="pending", version=row["version"] + 1, updated_at=now())
                db().execute(f"UPDATE records SET {','.join(k+'=?' for k in values)} WHERE id=?", [*values.values(), rid])
                db().execute("DELETE FROM record_links WHERE report_id=?", (rid,))
                db().executemany("INSERT INTO record_links VALUES (?,?)", [(rid, x) for x in linked])
                workflow.set_sources(db(), rid, associated)
                evidence.save_links(db(), rid, cited, get_record, data.get("refresh_citations") is True)
                save_revision(db(), "record", rid, "修订资料", user()["id"])
        except Exception:
            if path:
                path.unlink(missing_ok=True)
            raise
        return jsonify(id=rid)

    @app.post("/api/records/<rid>/author")
    def confirm_author(rid):
        db().execute("BEGIN IMMEDIATE")
        row, data = get_record(rid), body()
        rid = row["id"]
        check_version(data, row)
        if row["kind"] not in workflow.PERSONAL_KINDS or row["author_confirmed"]:
            abort(409, "此内容无需确认，或作者已经确认。")
        author_id = data.get("author_id", row["author_id"])
        if not isinstance(author_id, str):
            abort(400, "请选择负责作者账号。")
        if author_id != row["author_id"] and user()["id"] != row["owner_id"]:
            abort(403, "只有原提交者可以指定待确认的负责作者。")
        if not db().execute("SELECT 1 FROM users WHERE id=? AND active=1", (author_id,)).fetchone():
            abort(400, "请选择有效的负责作者。")
        confirmed = data.get("confirm") is True
        if confirmed and author_id != user()["id"]:
            abort(403, "必须由负责作者本人确认。")
        if not confirmed and row["owner_id"] != user()["id"]:
            abort(403, "只有提交者可以指定作者。")
        with db():
            if not db().execute("SELECT 1 FROM revisions WHERE target_type='record' AND target_id=?", (rid,)).fetchone():
                save_revision(db(), "record", rid, "作者确认前版本", user()["id"])
            db().execute("UPDATE records SET author_id=?,author_confirmed=?,editors='[]',version=version+1,updated_at=? WHERE id=?", (author_id, int(confirmed), now(), rid))
            save_revision(db(), "record", rid, "负责作者本人确认" if confirmed else "指定负责作者，等待本人确认", user()["id"])
        return jsonify(id=rid)

    @app.post("/api/review/<kind>/<row_id>")
    def review(kind, row_id):
        admin()
        if kind not in ["record", "source"]:
            abort(404)
        table = "records" if kind == "record" else "sources"
        row = get_record(row_id) if kind == "record" else get_source(row_id)
        row_id = row["id"]
        data = body()
        check_version(data, row)
        with db():
            if not db().execute("SELECT 1 FROM revisions WHERE target_type=? AND target_id=?", (kind, row_id)).fetchone():
                save_revision(db(), kind, row_id, "导入初始版本", "admin")
            changed = db().execute(f"UPDATE {table} SET status='verified',version=version+1,updated_at=? WHERE id=? AND version=?", (now(), row_id, row["version"])).rowcount
            if not changed:
                abort(409, "内容已变化，请刷新。")
            save_revision(db(), kind, row_id, "完成信息核对", user()["id"])
        return jsonify(ok=True)

    @app.get("/api/history/<kind>/<row_id>")
    def history(kind, row_id):
        if kind == "record":
            current = get_record(row_id, edit=True)
        elif kind == "source":
            current = get_source(row_id)
        else:
            abort(404)
        ids = identity.origins(db(), "records" if kind == "record" else "sources", current["id"])
        rows = db().execute(f"SELECT r.*,u.name AS actor_name FROM revisions r JOIN users u ON u.id=r.actor_id WHERE target_type=? AND target_id IN ({','.join('?' for _ in ids)}) ORDER BY r.id DESC", (kind, *ids))
        return jsonify(items=[{"id": r["id"], "target_id": r["target_id"], "restorable": r["target_id"] == current["id"], "action": r["action"], "actor_name": r["actor_name"], "created_at": r["created_at"], "version": json.loads(r["snapshot_json"])["version"]} for r in rows])

    @app.get("/api/history/<int:revision_id>")
    def history_snapshot(revision_id):
        row = db().execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
        if not row:
            abort(404)
        if row["target_type"] == "record":
            get_record(row["target_id"], edit=True)
            archived = db().execute("SELECT * FROM records WHERE id=?", (row["target_id"],)).fetchone()
            if not visible(archived):
                abort(404)
        else:
            if row["target_type"] == "collection":
                get_collection(row["target_id"])
            else:
                get_source(row["target_id"])
        snapshot = json.loads(row["snapshot_json"])
        if row["target_type"] == "record":
            if snapshot.get("evidence_record_id"):
                original = identity.resolve(db(), "records", snapshot["evidence_record_id"])
                if not original or not visible(original):
                    abort(404, "该历史证据对应的原始资料当前不可见。")
            snapshot["linked_ids"] = [rid for rid in snapshot.get("linked_ids", []) if (record := identity.resolve(db(), "records", rid)) and visible(record)]
            snapshot["evidence_citations"] = [link for link in snapshot.get("evidence_citations", []) if (record := identity.resolve(db(), "records", link["excerpt_id"])) and visible(record) and evidence.readable_snapshot(db(), json.loads(link["snapshot_json"]), visible)]
        if row["target_type"] == "collection":
            snapshot["item_ids"] = [rid for rid in snapshot.get("item_ids", []) if (record := identity.resolve(db(), "records", rid)) and visible(record)]
        return jsonify(snapshot=snapshot, action=row["action"], target_id=row["target_id"])

    @app.post("/api/history/<int:revision_id>/restore")
    def restore_revision(revision_id):
        # Lock before validating cross-source relationships, including restoration.
        db().execute("BEGIN IMMEDIATE")
        row = db().execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
        if not row:
            abort(404)
        kind, rid = row["target_type"], row["target_id"]
        current = get_record(rid, edit=True) if kind == "record" else get_source(rid)
        if current["id"] != rid:
            abort(409, "此历史属于已合并的原记录，只供查阅；请在保留记录中手工修订。")
        if kind == "source":
            admin()
        data = body()
        check_version(data, current)
        snapshot = json.loads(row["snapshot_json"])
        if kind == "record" and snapshot["kind"] in workflow.CONTENT_KINDS and (db().execute("SELECT 1 FROM record_links WHERE original_id=?", (rid,)).fetchone() or db().execute("SELECT 1 FROM records WHERE evidence_record_id=?", (rid,)).fetchone()):
            abort(409, "此资料现已被成果或摘录引用，不能恢复为研究内容类型。")
        fields = RECORD_FIELDS + ["attachment_ids", "evidence_version", "evidence_snapshot_json"] if kind == "record" else SOURCE_FIELDS + list(source_catalog.DEFAULTS)
        values = {k: snapshot[k] for k in fields if k in snapshot}
        if kind == "source":
            # Pre-upgrade snapshots have no new metadata: retain those current fields.
            values = source_values(values, current)
        # Restoration never restores old permissions. Current ACL and ownership remain authoritative.
        if kind == "record":
            values["visibility"] = current["visibility"]
            values["aliases"] = identity.retained_aliases(db(), "records", rid, values.get("aliases", current["aliases"]))
            for key in ["source_id", "serial_id"]:
                if values.get(key):
                    values[key] = get_source(values[key])["id"]
            if values.get("evidence_record_id"):
                values["evidence_record_id"] = get_record(values["evidence_record_id"])["id"]
            if current["kind"] in workflow.CONTENT_KINDS and values["kind"] != current["kind"]:
                abort(409, "历史类型不符合当前维护责任，请手工修订内容。")
        values.update(status="pending", version=current["version"]+1, updated_at=now())
        table = "records" if kind == "record" else "sources"
        with db():
            changed = db().execute(f"UPDATE {table} SET {','.join(k+'=?' for k in values)} WHERE id=? AND version=?", [*values.values(), rid, current["version"]]).rowcount
            if not changed:
                abort(409, "内容已变化，请刷新。")
            if kind == "record":
                if values.get("evidence_record_id"):
                    original = get_record(values["evidence_record_id"])
                    if original["kind"] in workflow.CONTENT_KINDS:
                        abort(409, "历史证据对象的类型已改变，请手工修订。")
                if "evidence_citations" in snapshot:
                    db().execute("DELETE FROM evidence_links WHERE report_id=?", (rid,))
                    for link in snapshot["evidence_citations"]:
                        cited_record = get_record(link["excerpt_id"])
                        db().execute("INSERT INTO evidence_links VALUES (?,?,?,?)", (rid, cited_record["id"], link["excerpt_version"], link["snapshot_json"]))
                if "related_source_ids" in snapshot:
                    associated = sorted({get_source(sid)["id"] for sid in snapshot["related_source_ids"]})
                    workflow.set_sources(db(), rid, associated)
                db().execute("DELETE FROM record_links WHERE report_id=?", (rid,))
                for linked_id in snapshot.get("linked_ids", []):
                    original = get_record(linked_id)
                    if original["kind"] in workflow.CONTENT_KINDS:
                        abort(409, "历史关联对象的类型已改变，请手工修订。")
                    db().execute("INSERT OR IGNORE INTO record_links VALUES (?,?)", (rid, original["id"]))
            save_revision(db(), kind, rid, f"恢复版本 {snapshot['version']}", user()["id"])
        return jsonify(id=rid)

    @app.get("/api/sources")
    def sources_list():
        rows = list(source_catalog.catalog(db()).values())
        countries = sorted({c for r in rows if r["kind"] == "journal" for c in r["national_countries"]})
        q = request.args.get("q", "").casefold().strip()
        if q:
            rows = [r for r in rows if all(w in (r["name"] + " " + r["original_name"] + " " + r["classification"] + " " + r["aliases"] + " " + r["introduction_text"]).casefold() for w in q.split())]
            for r in rows:
                r["search_snippet"] = workflow.snippet(" ".join(r[k] for k in ["name", "original_name", "aliases", "introduction_text"]), q)
        if request.args.get("kind"):
            rows = [r for r in rows if r["kind"] == request.args["kind"]]
        if request.args.get("directory") == "1":
            rows = [r for r in rows if r["group"] != "maintenance"]
        if request.args.get("group"):
            rows = [r for r in rows if r["group"] == request.args["group"]]
        if request.args.get("institution_type"):
            rows = [r for r in rows if request.args["institution_type"] in r["institution_types"]]
        country = request.args.get("country")
        if country:
            rows = [r for r in rows if r["kind"] == "journal" and (
                r["national_status"] == "pending" if country == "__pending__" else country in r["national_countries"])]
        if request.args.get("international"):
            rows = [r for r in rows if r["kind"] == "journal" and r["international_status"] == request.args["international"]]
        if request.args.get("status"):
            rows = [r for r in rows if r["status"] == request.args["status"]]
        if request.args.get("scope") == "active":
            rows = [r for r in rows if not any(x in r["scope_status"] for x in ["out_of_scope", "historical", "discovery", "candidate"]) and r["kind"] not in ["portal", "registry_publication"]]
        return jsonify(items=[{k: v for k, v in r.items() if k != "raw_json"} for r in rows], total=len(rows), countries=countries)

    @app.get("/api/sources/<sid>")
    def source_detail(sid):
        sid = get_source(sid)["id"]
        obj = source_catalog.catalog(db())[sid]
        obj["previous_ids"] = [x for x in identity.origins(db(), "sources", sid) if x != sid]
        return jsonify(obj)

    def source_values(data, base=None):
        data = dict(data)
        values = validate_text(data, SOURCE_FIELDS, base)
        if base:
            values["aliases"] = identity.retained_aliases(db(), "sources", base["id"], values["aliases"])
        try:
            values["introduction_html"], values["introduction_text"] = workflow.clean_rich(values["introduction_html"])
        except ValueError as error:
            abort(400, str(error))
        if not values["name"] or values["kind"] not in SOURCE_KINDS:
            abort(400, "请填写来源名称并选择正确类型。")
        for field in ["host_id", "publisher_id"]:
            ids = relationship_ids(values[field])
            canonical = []
            for parent_id in ids:
                parent = get_source(parent_id)
                if parent["kind"] not in ["institution", "think_tank"] or (base and parent["id"] == base["id"]):
                    abort(400, "主办方或出版方应为机构。")
                canonical.append(parent["id"])
            values[field] = " | ".join(dict.fromkeys(canonical))
        if "relationships" in data:
            relations = data["relationships"]
            if isinstance(relations, str):
                try:
                    relations = json.loads(relations)
                except ValueError:
                    abort(400, "机构关系格式不正确。")
            if isinstance(relations, list):
                canonical_relations = []
                for relation in relations:
                    if isinstance(relation, dict) and isinstance(relation.get("target_id"), str):
                        target = identity.resolve(db(), "sources", relation["target_id"])
                        relation = {**relation, "target_id": target["id"] if target else relation["target_id"]}
                    canonical_relations.append(relation)
                data["relationships"] = canonical_relations
        values["scope_status"] = values["scope_status"] or "candidate"
        try:
            source_catalog.validate_metadata(db(), data, values, base)
        except (ValueError, TypeError) as error:
            abort(400, str(error))
        return values

    @app.post("/api/sources")
    def new_source():
        db().execute("BEGIN IMMEDIATE")
        values = source_values(body())
        if db().execute("SELECT 1 FROM sources WHERE lower(name)=lower(?) OR (website<>'' AND website=?)", (values["name"], values["website"])).fetchone():
            abort(409, "相同名称或官网已登记，请先检查来源目录。")
        sid = "SRC-LOCAL-" + uuid.uuid4().hex[:10].upper()
        values.update(id=sid, created_at=now(), updated_at=now())
        with db():
            db().execute(f"INSERT INTO sources ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
            save_revision(db(), "source", sid, "提交来源", user()["id"])
        return jsonify(id=sid), 201

    @app.put("/api/sources/<sid>")
    def edit_source(sid):
        db().execute("BEGIN IMMEDIATE")
        row, data = get_source(sid), body()
        sid = row["id"]
        check_version(data, row)
        values = source_values(data, row)
        values.update(status="pending", version=row["version"]+1, updated_at=now())
        with db():
            if not db().execute("SELECT 1 FROM revisions WHERE target_type='source' AND target_id=?", (sid,)).fetchone():
                save_revision(db(), "source", sid, "导入初始版本", "admin")
            changed = db().execute(f"UPDATE sources SET {','.join(k+'=?' for k in values)} WHERE id=? AND version=?", [*values.values(), sid, row["version"]]).rowcount
            if not changed:
                abort(409, "内容已变化，请刷新。")
            save_revision(db(), "source", sid, "修订来源", user()["id"])
        return jsonify(id=sid)

    @app.get("/api/users")
    def users_list():
        return jsonify(items=[dict(r) for r in db().execute("SELECT id,name,role FROM users WHERE active=1")])

    @app.post("/api/favorites/<rid>")
    def favorite(rid):
        rid = get_record(rid)["id"]
        data = body()
        if not isinstance(data.get("saved"), bool):
            abort(400, "请指定收藏状态。")
        with db():
            if data["saved"]:
                db().execute("INSERT OR IGNORE INTO favorites VALUES (?,?)", (user()["id"], rid))
            else:
                db().execute("DELETE FROM favorites WHERE user_id=? AND record_id=?", (user()["id"], rid))
        return jsonify(saved=data["saved"])

    def get_collection(cid, edit=False):
        r = db().execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
        u = user()
        if not r or (r["visibility"] == "private" and r["owner_id"] != u["id"]):
            abort(404, "专题不存在或没有访问权限。")
        if edit and r["visibility"] != "shared" and r["owner_id"] != u["id"]:
            abort(403)
        return r

    @app.get("/api/collections")
    def collection_list():
        items = []
        for r in db().execute("SELECT c.*,u.name AS owner_name FROM collections c JOIN users u ON c.owner_id=u.id ORDER BY c.created_at DESC"):
            if r["visibility"] == "private" and r["owner_id"] != user()["id"]:
                continue
            item = dict(r)
            item["count"] = sum(1 for x in db().execute("SELECT r.* FROM records r JOIN collection_items i ON r.id=i.record_id WHERE i.collection_id=?", (r["id"],)) if visible(x))
            items.append(item)
        return jsonify(items=items)

    @app.post("/api/collections")
    def new_collection():
        values = operations.collection_values(body())
        if not values["name"] or values["visibility"] not in ["shared", "private"]:
            abort(400, "请填写专题名称并选择共享范围。")
        cid = "COL-" + uuid.uuid4().hex[:10]
        with db():
            values.update(id=cid, owner_id=user()["id"], created_at=now(), updated_at=now())
            db().execute(f"INSERT INTO collections({','.join(values)}) VALUES({','.join('?' for _ in values)})", list(values.values()))
            save_revision(db(), "collection", cid, "创建研究专题", user()["id"])
        return jsonify(id=cid), 201

    @app.post("/api/collections/<cid>/items")
    def collection_add(cid):
        get_collection(cid, edit=True)
        data = body()
        rid = str(data.get("record_id", ""))
        rid = get_record(rid)["id"]
        with db():
            if not db().execute("SELECT 1 FROM revisions WHERE target_type='collection' AND target_id=?", (cid,)).fetchone():
                save_revision(db(), "collection", cid, "专题整理前版本", user()["id"])
            if data.get("remove") is True:
                db().execute("DELETE FROM collection_items WHERE collection_id=? AND record_id=?", (cid, rid))
            else:
                db().execute("INSERT OR IGNORE INTO collection_items VALUES (?,?)", (cid, rid))
            db().execute("UPDATE collections SET version=version+1,updated_at=? WHERE id=?", (now(), cid))
            save_revision(db(), "collection", cid, "移出专题资料" if data.get("remove") is True else "加入专题资料", user()["id"])
        return jsonify(ok=True)

    @app.get("/api/attachments/<aid>")
    def download_attachment(aid):
        a = db().execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not a:
            abort(404)
        row = get_record(a["record_id"])
        if aid not in json.loads(row["attachment_ids"]):
            abort(404, "附件属于历史版本，请先恢复相应版本。")
        path = data_dir / "uploads" / a["stored_name"]
        if not path.is_file():
            abort(404, "附件文件缺失，请联系管理员。")
        return send_file(path, as_attachment=True, download_name=a["name"])

    @app.get("/api/records/<rid>/evidence-file")
    def evidence_file(rid):
        note = get_record(rid)
        original = get_record(note["evidence_record_id"])
        attachment = db().execute("SELECT * FROM attachments WHERE id=? AND record_id=?", (note["evidence_attachment_id"], original["id"])).fetchone()
        if not attachment:
            abort(404, "引用附件不存在。")
        path = data_dir / "uploads" / attachment["stored_name"]
        if not path.is_file():
            abort(404, "引用附件文件缺失。")
        return send_file(path, as_attachment=True, download_name=attachment["name"])

    @app.get("/api/export")
    def export():
        rows, _ = filtered_records(request.args)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["稳定编号", "题名", "原题名", "作者/编译者", "类型", "日期", "语言", "研究对象", "关键词", "刊物", "DOI", "原文链接", "核对状态", "来源编号", "期刊编号", "关联原文编号"])
        for r in rows:
            linked = [x["id"] for x in db().execute("SELECT r.* FROM record_links l JOIN records r ON r.id=l.original_id WHERE l.report_id=?", (r["id"],)) if visible(x)]
            values = [r[k] or "" for k in ["id", "title", "original_title", "authors", "kind", "published_on", "language", "countries", "keywords", "publication_title", "doi", "url", "status", "source_id", "serial_id"]] + [";".join(linked)]
            writer.writerow(["'" + v if str(v).lstrip().startswith(("=", "+", "-", "@")) else v for v in values])
        return send_file(io.BytesIO(output.getvalue().encode("utf-8-sig")), mimetype="text/csv; charset=utf-8", as_attachment=True, download_name="research-records.csv")

    @app.get("/api/dashboard")
    def dashboard():
        rows, favorites = filtered_records({})
        source_rows = db().execute("SELECT kind,scope_status FROM sources WHERE merged_into IS NULL").fetchall()
        stats = dict(records=len(rows), compilations=sum(r["kind"] == "compilation" for r in rows),
                     pending=sum(r["status"] == "pending" for r in rows), favorites=sum(r["id"] in favorites for r in rows),
                     institutions=sum(r["kind"] in ["institution", "think_tank"] for r in source_rows),
                     journals=sum(r["kind"] == "journal" for r in source_rows),
                     serials=sum(r["kind"] == "serial" for r in source_rows), source_entries=len(source_rows))
        activities = []
        for r in db().execute("SELECT v.*,u.name AS actor_name FROM revisions v JOIN users u ON u.id=v.actor_id ORDER BY v.id DESC LIMIT 60"):
            snapshot = json.loads(r["snapshot_json"])
            if r["target_type"] == "record":
                current = db().execute("SELECT * FROM records WHERE id=?", (r["target_id"],)).fetchone()
                if not current or not visible(current):
                    continue
                # Show current title so a stale revision never reveals previously restricted metadata.
                title = current["title"]
            elif r["target_type"] == "collection":
                current = db().execute("SELECT * FROM collections WHERE id=?", (r["target_id"],)).fetchone()
                if not current or (current["visibility"] == "private" and current["owner_id"] != user()["id"]):
                    continue
                title = current["name"]
            else:
                title = snapshot["name"]
            activities.append({"action": r["action"], "actor_name": r["actor_name"], "title": title, "created_at": r["created_at"]})
            if len(activities) == 5:
                break
        imported = db().execute("SELECT value FROM settings WHERE key='thinktank_import_v1'").fetchone()
        mine = [r for r in rows if r["kind"] in workflow.PERSONAL_KINDS and r["author_id"] == user()["id"] and r["author_confirmed"] and editable(r)]
        return jsonify(stats=stats, latest=[record_summary(r, favorites) for r in sorted(rows, key=lambda r: (r["updated_at"], r["published_on"]), reverse=True)[:5]],
                       my_work=[record_summary(r, favorites) for r in sorted(mine, key=lambda r: (r["updated_at"], r["id"]), reverse=True)[:4]],
                       activities=activities, imported=json.loads(imported[0]) if imported else None)

    @app.post("/api/backup")
    def backup():
        admin()
        from .maintenance import create_backup
        path = create_backup(data_dir)
        return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/zip")

    identity.register(app, SimpleNamespace(db=db, user=user, body=body, get_record=get_record, get_source=get_source,
                                          visible=visible, editable=editable, source_values=source_values))
    operations.register(app, SimpleNamespace(db=db, user=user, body=body, admin=admin, get_record=get_record,
                                            get_source=get_source, visible=visible, editable=editable,
                                            get_collection=get_collection, record_summary=record_summary,
                                            record_detail=record_detail, filtered_records=filtered_records,
                                            check_version=check_version, data_dir=data_dir))
    return app
