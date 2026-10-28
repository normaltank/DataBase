import csv
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .search import normalize, RecordSearch
from .attachment_search import AttachmentIndex, original_path
from .publication_dates import interval as publication_interval, query_range as publication_query_range
from .store import connect, decoded, initialize, now, save_revision
from .record_revisions import RecordRevisions, validate_text, check_version
from . import source_catalog, workflow, evidence, identity, operations, reading, people, note_subjects, bylines, affiliations, person_identity, bulk, intake, saved_searches, collection_scope, reviews, translations, ris, discovery, reading_feed

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FIELDS = ["name", "original_name", "kind", "classification", "location", "country", "research_scope",
                 "website", "catalogue_url", "host_id", "publisher_id", "issn", "scope_status", "notes"] + list(workflow.SOURCE_DEFAULTS)
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

    def records():
        if 'record_access' not in g:
            g.record_access = RecordRevisions(db(), user(), data_dir / "uploads")
        return g.record_access

    def visible(row):
        return records().visible(row)

    def editable(row):
        return records().editable(row)

    def get_record(rid, edit=False):
        return records().get(rid, edit=edit)

    def get_source(sid):
        return records().source(sid)

    def attachment_index():
        if 'attachment_index' not in g:
            g.attachment_index = AttachmentIndex(db(), data_dir)
        return g.attachment_index

    def index_uploaded(rid, file, previous_ids=()):
        if file and file.filename:
            # The record transaction has committed before parsing starts.
            attachments = attachment_index().current(get_record(rid))
            for attachment in attachments:
                if attachment["id"] not in previous_ids:
                    attachment_index().rebuild(attachment)

    def record_summary(r, favorite_ids=None):
        obj = {k: r[k] for k in ["id", "kind", "title", "original_title", "authors", "source_id", "serial_id",
               "publication_title", "volume", "issue", "pages", "issn", "published_on", "language", "abstract", "keywords", "countries", "status",
                "visibility", "owner_id", "version", "updated_at", "upstream_status", "aliases", "coverage", "author_id", "author_confirmed"]}
        obj.update(translations.projection(db(), r))
        obj['created_at'] = r['created_at']
        if 'record_search' in g:
            source = g.record_search.sources.get(r['source_id'])
            obj['source_name'] = source['name'] if source else ''
        else:
            source = db().execute("SELECT name FROM sources WHERE id=?", (r["source_id"],)).fetchone()
            obj["source_name"] = source[0] if source else ""
        obj["favorite"] = r["id"] in favorite_ids if favorite_ids is not None else bool(db().execute("SELECT 1 FROM favorites WHERE user_id=? AND record_id=?", (user()["id"], r["id"])).fetchone())
        obj["can_edit"] = editable(r)
        obj["can_manage_access"] = records().manages_access(r)
        obj["has_attachment"] = bool(json.loads(r["attachment_ids"]))
        obj["related_source_ids"] = g.record_search.associated[r["id"]] if "record_search" in g else workflow.source_ids(db(), r["id"])
        text = " ".join(r[k] or "" for k in ["title", "original_title", "aliases", "abstract", "body_text", "coverage"]) + ' ' + obj['display_title'] + ' ' + obj['display_abstract']
        from .ingestion import searchable_text
        text += ' '+searchable_text(r)
        obj["search_snippet"] = workflow.snippet(text, request.args.get("q", "")) if request.args.get("q") else ""
        obj["attachment_matches"] = attachment_index().matches(r, request.args.get("q", ""))
        if obj["attachment_matches"] and not any(word in normalize(text) for word in normalize(request.args.get("q", "")).split()):
            obj["search_snippet"] = ""
        obj["evidence_record_id"] = r["evidence_record_id"]
        if "reading_authors" not in g:
            g.reading_authors = {u["id"]: u["name"] for u in db().execute("SELECT id,name FROM users")}
        if "reading_attachments" not in g:
            g.reading_attachments = {a["id"]: dict(a) for a in db().execute("SELECT id,record_id,name,stored_name FROM attachments")}
        obj["author_name"] = g.reading_authors.get(r["author_id"], "")
        obj["reading_access"] = reading.access(r, g.reading_attachments, data_dir)
        return obj

    def filtered_records(args):
        args = saved_searches.resolve(db(), user()['id'], args)
        from . import reading_queries
        frozen = reading_queries.get(db(), args)
        date_from, date_to = publication_query_range(args)
        date_field = args.get('date_field', 'published')
        if date_field not in {'published', 'collected', 'updated'}:
            abort(400, '时间类型不正确。')
        all_rows = db().execute("SELECT * FROM records ORDER BY published_on DESC, created_at DESC, id").fetchall()
        access = records()
        access.prefetched_records = {r['id']: r for r in all_rows}
        rows = [r for r in all_rows if not r['merged_into'] and visible(r)]
        batch_ids = reading_feed.scope_ids(db(), user()['id'], args)
        if batch_ids is not None:
            batch_order = {rid: index for index, rid in enumerate(batch_ids)}
            rows = [r for r in rows if r['id'] in batch_order]
        g.record_search = RecordSearch(db(), access)
        from collections import defaultdict
        attachments = defaultdict(list)
        for attachment in db().execute('SELECT * FROM attachments'):
            attachments[attachment['record_id']].append(dict(attachment))
        attachment_index().prefetched = attachments
        g.reading_attachments = {a["id"]: a for group in attachments.values() for a in group}
        favorites = {r[0] for r in db().execute("SELECT record_id FROM favorites WHERE user_id=?", (user()["id"],))}
        q = normalize(args.get("q", "").strip())
        countries = {country.casefold() for country in reading_feed.choices(args.get('country'))}
        source_names = {sid: g.record_search.source_text(sid) for sid in g.record_search.sources}
        collection_ids = None
        if args.get("collection"):
            get_collection(args["collection"])
            collection_ids = {r[0] for r in db().execute("SELECT record_id FROM collection_items WHERE collection_id=? AND disposition='included'", (args["collection"],))}
        results = []
        source_unknown = '__unknown__' in reading_feed.choices(args.get('source'))
        selected_sources = {get_source(s)['id'] for s in reading_feed.choices(args.get('source')) if s != '__unknown__'}
        selected_source_row = get_source(next(iter(selected_sources))) if len(selected_sources) == 1 else None
        selected_source = selected_source_row["id"] if selected_source_row else None
        source_section = args.get("source_section")
        if source_section and (not selected_source or source_section not in {"published", "associated", "translations", "outputs"}):
            abort(400, "来源内容分区需指定来源及有效分区。")
        source_group = args.get("source_group", "")
        source_country = args.get("source_country", "").strip()
        source_international = args.get("source_international", "")
        if set(reading_feed.choices(source_group)) - {'institution', 'journal', 'publication'} or source_international not in {"", "yes", "no", "unknown"}:
            abort(400, "来源类型或国际办刊定位不正确。")
        if source_international and source_group not in {"", "journal"}:
            abort(400, "国际办刊定位只适用于期刊。")
        source_scope = None
        if source_group or source_country or source_international:
            source_scope = {sid for sid, source in source_catalog.catalog(db()).items()
                            if source['group'] != 'maintenance' and (not selected_sources or sid in selected_sources)
                            and any(source_catalog.matches_scope(source, group, country, source_international)
                                    for group in reading_feed.choices(source_group) or ['']
                                    for country in reading_feed.choices(source_country) or [''])}
        if frozen is not None:
            order = {rid: i for i, rid in enumerate(json.loads(frozen['ids_json']))}
            results = sorted((r for r in rows if r['id'] in order), key=lambda r: order[r['id']])
            g.reading_confirmation = reading_queries.confirmation(frozen, results)
            return results, favorites
        for r in rows:
            if args.get("editable") == "1" and not editable(r):
                continue
            if args.get("favorite") == "1" and r["id"] not in favorites:
                continue
            if collection_ids is not None and r["id"] not in collection_ids:
                continue
            associated = g.record_search.associated[r["id"]]
            if source_scope is not None and not source_scope.intersection([r["source_id"], r["serial_id"], *associated]):
                continue
            record_sources = {sid for sid in [r['source_id'], r['serial_id'], *associated] if sid}
            if args.get('source') and not (selected_sources.intersection(record_sources) or (source_unknown and not record_sources)):
                continue
            if source_section:
                content_kind = r["kind"] in workflow.CONTENT_KINDS
                publication_field = "source_id" if selected_source_row["kind"] in {"institution", "think_tank"} else "serial_id"
                if source_section == "published" and (content_kind or r[publication_field] != selected_source):
                    continue
                if source_section == "associated" and (content_kind or selected_source not in associated):
                    continue
                if source_section == "translations" and r["kind"] != "directory_translation":
                    continue
                if source_section == "outputs" and r["kind"] not in workflow.PERSONAL_KINDS:
                    continue
            if args.get('kind') and r['kind'] not in reading_feed.choices(args['kind']):
                continue
            if args.get("evidence_of") and r["evidence_record_id"] != args["evidence_of"]:
                continue
            if args.get("status") and r["status"] != args["status"]:
                continue
            if args.get('language') and not set(reading_feed.choices(args['language'])).intersection(re.split(r'[;,|\s]+', r['language']) if r['language'] else ['__unknown__']):
                continue
            subject_countries = {country.casefold() for country in reading_feed.terms(r['countries'])} or {'__unknown__'}
            if countries and not countries.intersection(subject_countries):
                continue
            if args.get('topic') and not any((not r['keywords'].strip()) if t == '__unknown__' else t.casefold() in r['keywords'].casefold() for t in reading_feed.choices(args['topic'])):
                continue
            if args.get('availability') and not set(reading_feed.choices(args['availability'])).intersection(reading_feed.available(r, translations.projection(db(), r))):
                continue
            date_value = r['published_on'] if date_field == 'published' else r['created_at' if date_field == 'collected' else 'updated_at'][:10]
            if args.get('date_unknown') == '1' and publication_interval(date_value) is not None:
                continue
            if date_from or date_to:
                possible = publication_interval(date_value)
                if possible is None:
                    continue
                if date_from and possible[1] < date_from:
                    continue
                if date_to and possible[0] > date_to:
                    continue
            if q:
                hay = " ".join(str(r[k]) for k in ["title", "original_title", "authors", "abstract", "keywords", "publication_title", "doi", "id", "aliases", "body_text", "coverage", "original_catalogue", "quote", "translation", "interpretation", "locator"]) + " " + " ".join(source_names.get(sid, "") for sid in [r["source_id"], r["serial_id"], *associated])
                hay += " " + " ".join(g.record_search.bylines[r["id"]])
                from .ingestion import searchable_text
                hay += ' '+searchable_text(r)
                chinese = translations.projection(db(), r)
                hay += ' ' + chinese['display_title'] + ' ' + chinese['display_abstract']
                hay += " " + " ".join(s["text"] for s in attachment_index().segments(r))
                if not all(word in normalize(hay) for word in q.split()):
                    continue
            results.append(r)
        if batch_ids is not None:
            results.sort(key=lambda r: batch_order[r['id']])
        elif args.get("sort") == "collected":
            results.sort(key=lambda r: (r['title'].casefold(), r['id']))
            results.sort(key=lambda r: (r['created_at'], r['published_on']), reverse=True)
        elif args.get("sort") == "updated":
            results.sort(key=lambda r: r["updated_at"], reverse=True)
        elif args.get("sort") == "title":
            results.sort(key=lambda r: r["title"].casefold())
        frozen = reading_queries.freeze(db(), args, results)
        if frozen is not None:
            order = {rid: i for i, rid in enumerate(json.loads(frozen['ids_json']))}
            results = sorted((r for r in rows if r['id'] in order), key=lambda r: order[r['id']])
            g.reading_confirmation = reading_queries.confirmation(frozen, results)
        return results, favorites

    @app.get("/api/records")
    def records_list():
        rows, favorites = filtered_records(request.args)
        try:
            page = max(1, int(request.args.get("page", 1)))
            size = min(100, max(1, int(request.args.get("size", 12))))
        except ValueError:
            abort(400, "页码不正确。")
        return jsonify(items=[record_summary(r, favorites) for r in rows[(page - 1)*size:page*size]], total=len(rows), page=page, size=size,
                       facets=reading_feed.facets(rows, db()), reading_confirmation=g.get('reading_confirmation'))

    @app.get("/api/record-candidates")
    def record_candidates():
        purpose = request.args.get("purpose")
        if purpose not in {"original", "collection"}:
            abort(400, "请选择有效的查找用途。")
        rows, favorites = filtered_records(request.args)
        excluded = set(request.args.getlist("exclude"))
        if purpose == "collection":
            cid = request.args.get("target_collection", "")
            get_collection(cid)
            excluded.update(r[0] for r in db().execute("SELECT record_id FROM collection_items WHERE collection_id=?", (cid,)))
        rows = [r for r in rows if r["id"] not in excluded and (purpose != "original" or r["kind"] not in workflow.CONTENT_KINDS)]
        try:
            size = min(100, max(1, int(request.args.get("size", 15))))
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            abort(400, "页码不正确。")
        page = min(page, max(1, (len(rows) + size - 1) // size))
        return jsonify(items=[record_summary(r, favorites) for r in rows[(page-1)*size:page*size]], total=len(rows), page=page, size=size)

    @app.get("/api/records/<rid>")
    def record_detail(rid):
        row = get_record(rid)
        rid = row["id"]
        obj = decoded(row)
        if obj.get("raw_json", {}).get("intake_evidence"):
            obj["intake_evidence"] = obj["raw_json"]["intake_evidence"]
        if obj.get("raw_json", {}).get("ris_evidence"):
            obj["ris_evidence"] = obj["raw_json"]["ris_evidence"]
        if obj.get("raw_json", {}).get("discovery_evidence"):
            obj["discovery_evidence"] = obj["raw_json"]["discovery_evidence"]
        from .ingestion import acquisition_projection
        acquired = acquisition_projection(row)
        if acquired:
            obj['automatic_acquisition'] = acquired
        obj.update(record_summary(row))
        obj["owner_name"] = db().execute("SELECT name FROM users WHERE id=?", (row["owner_id"],)).fetchone()[0]
        last = reviews.last_modifier(db(), "record", rid)
        obj["last_modifier"] = {key: last[key] for key in ["name", "created_at"]} if last else None
        obj.update(reviews.summary(db(), "record", rid, visible))
        obj["linked_records"] = [record_summary(r) for r in db().execute("SELECT r.* FROM records r JOIN record_links l ON r.id=l.original_id WHERE l.report_id=?", (rid,)) if visible(r)]
        obj["cited_by"] = [record_summary(r) for r in db().execute("SELECT r.* FROM records r JOIN record_links l ON r.id=l.report_id WHERE l.original_id=?", (rid,)) if visible(r)]
        obj["attachments"] = [dict(a) for a in db().execute("SELECT id,name,bytes,created_at FROM attachments WHERE record_id=?", (rid,)) if a["id"] in obj["attachment_ids"]]
        for attachment in obj["attachments"]:
            full = db().execute("SELECT * FROM attachments WHERE id=?", (attachment["id"],)).fetchone()
            attachment["index"] = attachment_index().info(full)
        obj["evidence_citations"] = evidence.citations(db(), rid, visible)
        obj["excerpts"] = [record_summary(r) for r in db().execute("SELECT * FROM records WHERE evidence_record_id=? AND merged_into IS NULL", (rid,)) if visible(r)]
        obj["evidence_snapshot"] = evidence.project_snapshot(db(), json.loads(row["evidence_snapshot_json"]), visible)
        obj["evidence_snapshot_json"] = json.dumps(obj["evidence_snapshot"], ensure_ascii=False)
        obj["evidence_file_url"] = f"/api/records/{rid}/evidence-file" if row["evidence_attachment_id"] else ""
        obj["previous_ids"] = [x for x in identity.origins(db(), "records", rid) if x != rid]
        if row["kind"] == "research_note":
            obj["research_subjects"] = note_subjects.read(db(), rid, visible)
        obj["translations"] = translations.items(db(), row)
        obj["translation_history"] = translations.human_history(db(), row["id"])
        return jsonify(obj)

    @app.get("/api/records/<rid>/copy-text")
    def record_copy_text(rid):
        row = get_record(rid)
        adopted = evidence.citations(db(), row["id"], visible) if row["kind"] in {"research_report", "compilation"} else ()
        linked = [r for r in db().execute("SELECT r.* FROM records r JOIN record_links l ON r.id=l.original_id WHERE l.report_id=?", (row["id"],)) if visible(r)] if row["kind"] == "research_note" and not row["evidence_record_id"] else ()
        return jsonify(reading.copy_text(row, adopted, linked))

    @app.post("/api/records")
    def new_record():
        file = request.files.get("file")
        rid = records().create(body(), file)
        index_uploaded(rid, file)
        return jsonify(id=rid), 201

    @app.put("/api/records/<rid>")
    def edit_record(rid):
        file = request.files.get("file")
        previous_ids = json.loads(get_record(rid)["attachment_ids"])
        rid = records().edit(rid, body(), file)
        index_uploaded(rid, file, previous_ids)
        return jsonify(id=rid)

    @app.post("/api/records/<rid>/author")
    def confirm_author(rid):
        return jsonify(id=records().confirm_author(rid, body()))

    @app.post("/api/review/<kind>/<row_id>")
    def review(kind, row_id):
        admin()
        if kind not in ["record", "source"]:
            abort(404)
        if kind == "record":
            records().review(row_id, body())
            return jsonify(ok=True)
        data = body()
        with db():
            db().execute("BEGIN IMMEDIATE")
            row = get_source(row_id)
            row_id = row["id"]
            check_version(data, row)
            event = reviews.facts(db(), kind, row, user(), data)
            if not db().execute("SELECT 1 FROM revisions WHERE target_type=? AND target_id=?", (kind, row_id)).fetchone():
                save_revision(db(), kind, row_id, "导入初始版本", "admin")
            changed = db().execute("UPDATE sources SET status='verified',version=version+1,updated_at=? WHERE id=? AND version=?", (now(), row_id, row["version"])).rowcount
            if not changed:
                abort(409, "内容已变化，请刷新。")
            save_revision(db(), kind, row_id, reviews.ACTION, user()["id"], event)
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
        if row["target_type"] == "record":
            snapshot = evidence.project_snapshot(db(), snapshot, visible)
            for citation in snapshot.get("evidence_citations", []):
                citation["snapshot_json"] = json.dumps(evidence.project_snapshot(db(), json.loads(citation["snapshot_json"]), visible), ensure_ascii=False)
        if row["target_type"] == "collection":
            snapshot["scope_log"] = json.loads(snapshot.get("scope_log_json", "[]"))
            snapshot["item_details"] = [item for item in snapshot.get("item_details", [{"record_id": rid, "disposition": "included", "rationale": ""} for rid in snapshot.get("item_ids", [])]) if (record := identity.resolve(db(), "records", item["record_id"])) and visible(record)]
            snapshot["item_ids"] = [rid for rid in snapshot.get("item_ids", []) if (record := identity.resolve(db(), "records", rid)) and visible(record)]
        return jsonify(snapshot=snapshot, action=row["action"], target_id=row["target_id"])

    @app.post("/api/history/<int:revision_id>/restore")
    def restore_revision(revision_id):
        row = db().execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
        if not row:
            abort(404)
        if row["target_type"] == "record":
            return jsonify(id=records().restore(revision_id, body()))
        # Public source content uses the same member maintenance boundary as edits.
        db().execute("BEGIN IMMEDIATE")
        rid = row["target_id"]
        current = get_source(rid)
        if current["id"] != rid:
            abort(409, "此历史属于已合并的原记录，只供查阅；请在保留记录中手工修订。")
        check_version(body(), current)
        old = json.loads(row["snapshot_json"])
        values = source_values({k: old[k] for k in SOURCE_FIELDS + list(source_catalog.DEFAULTS) if k in old}, current)
        values.update(status="pending", version=current["version"]+1, updated_at=now())
        with db():
            changed = db().execute(f"UPDATE sources SET {','.join(k+'=?' for k in values)} WHERE id=? AND version=?", [*values.values(), rid, current["version"]]).rowcount
            if not changed:
                abort(409, "内容已变化，请刷新。")
            save_revision(db(), "source", rid, f"恢复版本 {old['version']}", user()["id"])
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
        for source in rows:
            source["previous_ids"] = [sid for sid in identity.origins(db(), "sources", source["id"]) if sid != source["id"]]
        return jsonify(items=[{k: v for k, v in r.items() if k != "raw_json"} for r in rows], total=len(rows), countries=countries)

    @app.get("/api/sources/<sid>")
    def source_detail(sid):
        sid = get_source(sid)["id"]
        obj = source_catalog.catalog(db())[sid]
        if discovery.supported(obj):
            obj['discovery_supported'] = True
        obj.update(reviews.summary(db(), "source", sid))
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
        if base:
            note_subjects.validate_source_type(db(), base["id"], values["kind"])
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
            item["count"] = sum(1 for x in db().execute("SELECT r.* FROM records r JOIN collection_items i ON r.id=i.record_id WHERE i.collection_id=? AND i.disposition='included' AND r.merged_into IS NULL", (r["id"],)) if visible(x))
            items.append(item)
        return jsonify(items=items)

    @app.post("/api/collections")
    def new_collection():
        values = operations.collection_values(body())
        if not values["name"] or values["visibility"] not in ["shared", "private"]:
            abort(400, "请填写资料夹名称并选择共享范围。")
        cid = "COL-" + uuid.uuid4().hex[:10]
        with db():
            values.update(id=cid, owner_id=user()["id"], created_at=now(), updated_at=now())
            db().execute(f"INSERT INTO collections({','.join(values)}) VALUES({','.join('?' for _ in values)})", list(values.values()))
            save_revision(db(), "collection", cid, "创建资料夹", user()["id"])
        return jsonify(id=cid), 201

    @app.post("/api/collections/<cid>/items")
    def collection_add(cid):
        db().execute("BEGIN IMMEDIATE")
        collection = get_collection(cid, edit=True)
        data = body()
        if "version" in data or "disposition" in data or "rationale" in data or data.get("remove") is True:
            check_version(data, collection)
        rid = str(data.get("record_id", ""))
        rid = get_record(rid)["id"]
        existing = db().execute("SELECT disposition,rationale FROM collection_items WHERE collection_id=? AND record_id=?", (cid, rid)).fetchone()
        disposition, rationale = collection_scope.decision({**(dict(existing) if existing else {}), **data})
        with db():
            if not db().execute("SELECT 1 FROM revisions WHERE target_type='collection' AND target_id=?", (cid,)).fetchone():
                save_revision(db(), "collection", cid, "资料夹整理前版本", user()["id"])
            if data.get("remove") is True:
                db().execute("DELETE FROM collection_items WHERE collection_id=? AND record_id=?", (cid, rid))
            else:
                if "disposition" in data or "rationale" in data:
                    db().execute("INSERT INTO collection_items(collection_id,record_id,disposition,rationale) VALUES (?,?,?,?) ON CONFLICT(collection_id,record_id) DO UPDATE SET disposition=excluded.disposition,rationale=excluded.rationale", (cid, rid, disposition, rationale))
                else:
                    db().execute("INSERT OR IGNORE INTO collection_items(collection_id,record_id) VALUES (?,?)", (cid, rid))
            db().execute("UPDATE collections SET version=version+1,updated_at=? WHERE id=?", (now(), cid))
            save_revision(db(), "collection", cid, "移出资料夹资料" if data.get("remove") is True else "修订专题条目决定与理由" if "disposition" in data or "rationale" in data else "加入资料夹资料", user()["id"])
        return jsonify(ok=True)

    def current_attachment(aid):
        a = db().execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not a:
            abort(404)
        row = get_record(a["record_id"])
        if aid not in json.loads(row["attachment_ids"]):
            abort(404, "附件属于历史版本，请先恢复相应版本。")
        path = original_path(data_dir, a)
        if path is None:
            abort(404, "附件文件缺失，请联系管理员。")
        return a, path

    @app.get("/api/attachments/<aid>")
    def download_attachment(aid):
        a, path = current_attachment(aid)
        return send_file(path, as_attachment=True, download_name=a["name"])

    @app.get("/api/attachments/<aid>/segment")
    def attachment_segment(aid):
        attached, _ = current_attachment(aid)
        indexed = attachment_index().read(attached)
        if indexed["status"] != "ready":
            abort(409, "当前附件没有可用文字索引，请重建或手工填写摘录。")
        segment = next((s for s in indexed["segments"] if s["locator"] == request.args.get("locator")), None)
        if not segment:
            abort(404, "附件索引中没有该位置。")
        return jsonify(record_id=attached["record_id"], attachment_id=aid, name=attached["name"], **segment)

    @app.post("/api/attachments/<aid>/index")
    def rebuild_attachment_index(aid):
        attachment, _ = current_attachment(aid)
        result = attachment_index().rebuild(attachment)
        current_attachment(aid)  # Recheck membership and permissions after parsing.
        return jsonify(result)

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
        return export_csv(rows)

    def export_csv(rows, filename="research-records.csv"):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["稳定编号", "题名", "原题名", "作者/编译者", "类型", "日期", "语言", "研究对象", "关键词", "刊物", "卷", "期", "页码", "ISSN", "DOI", "原文链接", "核对状态", "来源编号", "期刊编号", "关联原文编号", "人工中文题名", "人工中文摘要", "机器译文版本及出处", "当前阅读题名", "当前阅读摘要", "阅读版本类型", "首次收录", "最近修订"])
        for r in rows:
            linked = [x["id"] for x in db().execute("SELECT r.* FROM record_links l JOIN records r ON r.id=l.original_id WHERE l.report_id=?", (r["id"],)) if visible(x)]
            values = [r[k] or "" for k in ["id", "title", "original_title", "authors", "kind", "published_on", "language", "countries", "keywords", "publication_title", "volume", "issue", "pages", "issn", "doi", "url", "status", "source_id", "serial_id"]] + [";".join(linked), r["chinese_title"], r["chinese_abstract"], json.dumps(translations.items(db(), r), ensure_ascii=False)]
            projection = translations.projection(db(), r)
            values.extend([projection['display_title'], projection['display_abstract'],
                           {'human':'人工中文','machine':'机器中文，未人工校订','original':'原始信息'}[projection['translation_origin']],
                           r['created_at'], r['updated_at']])
            writer.writerow(["'" + v if str(v).lstrip().startswith(("=", "+", "-", "@")) else v for v in values])
        return send_file(io.BytesIO(output.getvalue().encode("utf-8-sig")), mimetype="text/csv; charset=utf-8", as_attachment=True, download_name=filename)

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

    saved_searches.register(app, SimpleNamespace(db=db, user=user, body=body, filtered_records=filtered_records))
    reading_feed.register(app, SimpleNamespace(db=db, user=user, body=body, filtered_records=filtered_records))
    intake.register(app, SimpleNamespace(db=db, user=user, body=body, records=records))
    discovery.register(app, SimpleNamespace(db=db, user=user, body=body, records=records))
    from . import ingestion
    ingestion.register(app, SimpleNamespace(db=db, user=user, body=body, records=records, admin=admin))
    ris.register(app, SimpleNamespace(db=db, user=user, body=body, records=records))
    translations.register(app, SimpleNamespace(db=db, user=user, body=body, records=records))
    bulk.register(app, SimpleNamespace(db=db, user=user, body=body, visible=visible, get_collection=get_collection, export_csv=export_csv))
    identity.register(app, db=db, body=body, records=records, validate_source=source_values)
    people.register(app, SimpleNamespace(db=db, user=user, body=body, data_dir=data_dir))
    person_identity.register(app, SimpleNamespace(db=db, user=user, body=body, data_dir=data_dir, records=records, record_summary=record_summary))
    bylines.register(app, SimpleNamespace(db=db, user=user, body=body, records=records, record_summary=record_summary))
    affiliations.register(app, SimpleNamespace(db=db, user=user, body=body, records=records, record_summary=record_summary))
    note_subjects.register(app, SimpleNamespace(db=db, records=records, body=body, record_summary=record_summary))
    operations.register(app, SimpleNamespace(db=db, user=user, body=body, admin=admin, get_record=get_record,
                                            get_source=get_source, visible=visible, editable=editable,
                                            get_collection=get_collection, record_summary=record_summary,
                                            record_detail=record_detail, filtered_records=filtered_records,
                                            check_version=check_version, data_dir=data_dir, records=records))
    return app
