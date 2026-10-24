"""Shared person profiles, distinct from member accounts and original bylines."""
import hashlib
import io
import json
import sqlite3
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path

from flask import abort, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError

from . import workflow, identity
from .store import connect, now, save_revision
from .record_revisions import check_version


FIELDS = ["name", "original_name", "chinese_name", "aliases", "introduction_html", "sources", "change_note", "avatar_source"]
AVATAR_TYPES = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}


def validate_backup(db):
    """All schema-6+ profile revisions must retain readable avatar references."""
    required = {"people", "person_avatars"}
    if not required <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        raise ValueError("备份缺少人物档案或头像登记。")

    def check(profile, pid):
        if (profile["id"] != pid or not db.execute("SELECT 1 FROM people WHERE id=?", (pid,)).fetchone()
                or type(profile["version"]) is not int or profile["version"] < 1
                or any(not isinstance(profile[key], str) for key in FIELDS)):
            raise ValueError("人物档案历史对象或版本不完整。")
        if profile.get("avatar_id") and not db.execute("SELECT 1 FROM person_avatars WHERE id=?", (profile["avatar_id"],)).fetchone():
            raise ValueError("人物历史头像引用不完整。")

    try:
        for row in db.execute("SELECT * FROM people"):
            check(dict(row), row["id"])
        for row in db.execute("SELECT target_id,snapshot_json FROM revisions WHERE target_type='person'"):
            check(json.loads(row["snapshot_json"]), row["target_id"])
    except (KeyError, TypeError, AttributeError, sqlite3.DatabaseError) as error:
        raise ValueError("人物档案或历史头像格式不完整。") from error


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= 6:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute("""CREATE TABLE people (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT NOT NULL DEFAULT '',
                chinese_name TEXT NOT NULL DEFAULT '', aliases TEXT NOT NULL DEFAULT '',
                introduction_html TEXT NOT NULL DEFAULT '', introduction_text TEXT NOT NULL DEFAULT '',
                sources TEXT NOT NULL DEFAULT '', change_note TEXT NOT NULL,
                avatar_id TEXT REFERENCES person_avatars(id), avatar_source TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE person_avatars (
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id), name TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("UPDATE settings SET value='6' WHERE key='schema_version'")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('people_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def values(data, base=None):
    result = {}
    for key in FIELDS:
        value = data.get(key, base[key] if base else "")
        limit = 500000 if key == "introduction_html" else 40000 if key in {"sources", "aliases"} else 2000
        if not isinstance(value, str) or len(value) > limit:
            abort(400, "人物字段格式不正确或内容过长。")
        result[key] = value.strip()
    if not result["name"] or not data.get("change_note", "").strip():
        abort(400, "请填写显示姓名及本次维护的依据或说明。")
    result["introduction_html"], result["introduction_text"] = workflow.clean_rich(result["introduction_html"])
    return result


def validated_image(upload):
    """Decode allowlisted formats; browser MIME labels alone do not prove image type."""
    content = upload.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        abort(400, "头像不能超过 5 MiB；其他输入仍已保留。")
    extension = Path(upload.filename or "").suffix.lower().lstrip(".")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content), formats=list(AVATAR_TYPES)) as picture:
                image_type = picture.format
                picture.verify()
            with Image.open(io.BytesIO(content), formats=list(AVATAR_TYPES)) as picture:
                picture.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        abort(400, "头像必须是完整、有效的 JPEG、PNG 或 WebP 图像。")
    stored_extension, mime = AVATAR_TYPES[image_type]
    if extension not in ({"jpg", "jpeg"} if image_type == "JPEG" else {stored_extension}):
        abort(400, "头像扩展名与真实图像类型不一致。")
    return content, stored_extension, mime


def retained_names(db, pid, value):
    members = identity.origins(db, "people", pid)
    names = [value]
    for old_id in members:
        if old_id != pid:
            old = db.execute("SELECT * FROM people WHERE id=?", (old_id,)).fetchone()
            names.extend(old[key] for key in ["name", "original_name", "chinese_name", "aliases"])
    return "\n".join(line for line in identity.aliases(*names).splitlines() if line not in members)


class PersonProfiles:
    """Current authenticated member's person identity and version operations."""

    def __init__(self, db, actor, data_dir):
        self.db, self.actor, self.data_dir = db, actor, Path(data_dir)

    @contextmanager
    def mutation(self):
        created_files = []
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                yield created_files
        except BaseException:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise

    def get(self, pid):
        row = self.db.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()
        if not row:
            abort(404, "人物档案不存在。")
        return row

    def detail(self, pid):
        row = identity.resolve(self.db, "people", pid)
        if not row:
            abort(404, "人物档案不存在。")
        requested_id, pid = pid, row["id"]
        actor = self.db.execute("""SELECT u.id,u.name,r.created_at FROM revisions r JOIN users u ON u.id=r.actor_id
            WHERE target_type='person' AND target_id=? ORDER BY r.id DESC LIMIT 1""", (pid,)).fetchone()
        return {**dict(row), "requested_id": requested_id,
                "previous_ids": [old for old in identity.origins(self.db, "people", pid) if old != pid],
                "avatar": self.avatar(pid, row["avatar_id"]), "can_edit": True, "can_restore": True,
                "last_modifier": dict(actor) if actor else None}

    def avatar(self, pid, avatar_id):
        if not avatar_id:
            return None
        row = self.db.execute("SELECT * FROM person_avatars WHERE id=?", (avatar_id,)).fetchone()
        referenced = row and (row["person_id"] == pid or self.db.execute(
            "SELECT 1 FROM revisions WHERE target_type='person' AND target_id=? AND json_extract(snapshot_json,'$.avatar_id')=?",
            (pid, avatar_id)).fetchone())
        if not referenced:
            abort(404, "头像不存在。")
        return {**{k: row[k] for k in ["id", "name", "mime_type", "bytes", "sha256", "created_at"]},
                "owner_id": row["person_id"], "url": f"/api/people/{row['person_id']}/avatars/{avatar_id}"}

    def upload_avatar(self, pid, current, upload, created_files):
        if not current["avatar_source"]:
            abort(400, "请填写头像的来源链接或来源说明。")
        content, extension, mime = validated_image(upload)
        aid = uuid.uuid4().hex
        folder = self.data_dir / "avatars"
        folder.mkdir(exist_ok=True)
        path = folder / (aid + "." + extension)
        created_files.append(path)
        with path.open("xb") as output:
            output.write(content)
        self.db.execute("INSERT INTO person_avatars VALUES (?,?,?,?,?,?,?,?)",
                        (aid, pid, Path(upload.filename.replace("\\", "/")).name[:255], path.name,
                         mime, len(content), hashlib.sha256(content).hexdigest(), now()))
        current["avatar_id"] = aid

    def create(self, data, upload=None):
        current = values(data)
        pid = "person-" + uuid.uuid4().hex
        with self.mutation() as created_files:
            current.update(id=pid, version=1, created_at=now(), updated_at=now())
            self.db.execute(f"INSERT INTO people ({','.join(current)}) VALUES ({','.join('?' for _ in current)})", list(current.values()))
            if upload:
                self.upload_avatar(pid, current, upload, created_files)
                self.db.execute("UPDATE people SET avatar_id=? WHERE id=?", (current["avatar_id"], pid))
            save_revision(self.db, "person", pid, "建立人物档案", self.actor["id"])
        return self.detail(pid)

    def update(self, pid, data, revision_id=None, upload=None):
        with self.mutation() as created_files:
            row = self.get(pid)
            if row["merged_into"]:
                abort(409, "此档案已合并，请打开当前人物档案维护；拆回请使用身份操作。")
            check_version(data, row)
            action = "修订人物档案"
            if revision_id is not None:
                revision = self.db.execute("SELECT * FROM revisions WHERE id=? AND target_type='person' AND target_id=?",
                                           (revision_id, pid)).fetchone()
                if not revision:
                    abort(404, "人物历史版本不存在。")
                snapshot = json.loads(revision["snapshot_json"])
                action = "恢复人物版本 " + str(snapshot["version"])
                data = {**snapshot, "change_note": data.get("change_note", "")}
            current = values(data, row)
            current["aliases"] = retained_names(self.db, pid, current["aliases"])
            if revision_id is not None:
                current["avatar_id"] = snapshot.get("avatar_id")
                self.avatar(pid, current["avatar_id"])
            elif data.get("remove_avatar") is True:
                if upload:
                    abort(400, "请只选择替换头像或移除头像其中一项。")
                current.update(avatar_id=None, avatar_source="")
            if upload:
                self.upload_avatar(pid, current, upload, created_files)
            current.update(version=row["version"] + 1, updated_at=now())
            self.db.execute(f"UPDATE people SET {','.join(k+'=?' for k in current)} WHERE id=?", [*current.values(), pid])
            save_revision(self.db, "person", pid, action, self.actor["id"])
        return self.detail(pid)

    def history(self, pid):
        person = self.get(pid)
        rows = self.db.execute("""SELECT r.*,u.name AS actor_name FROM revisions r JOIN users u ON u.id=r.actor_id
            WHERE target_type='person' AND target_id=? ORDER BY r.id DESC""", (pid,))
        items = []
        for row in rows:
            snapshot = json.loads(row["snapshot_json"])
            snapshot["avatar"] = self.avatar(pid, snapshot.get("avatar_id"))
            items.append({**{k: row[k] for k in ["id", "actor_id", "actor_name", "created_at", "action"]},
                          "version": snapshot["version"], "snapshot": snapshot, "can_restore": not bool(person["merged_into"])})
        return items


def register(app, ctx):
    def profiles():
        return PersonProfiles(ctx.db(), ctx.user(), ctx.data_dir)

    @app.get("/api/people")
    def people_list():
        service = profiles()
        words = request.args.get("q", "").strip().casefold().split()
        try:
            page = max(1, int(request.args.get("page", "1")))
            size = min(100, max(1, int(request.args.get("page_size", "24"))))
        except ValueError:
            abort(400, "分页参数不正确。")
        rows = [r for r in ctx.db().execute("SELECT * FROM people WHERE merged_into IS NULL ORDER BY updated_at DESC,id")
                if all(w in " ".join([r[k] for k in ["name", "original_name", "chinese_name", "aliases"]] +
                                     identity.origins(ctx.db(), "people", r["id"])).casefold() for w in words)]
        return jsonify(items=[service.detail(r["id"]) for r in rows[(page-1)*size:page*size]], total=len(rows), page=page, page_size=size)

    @app.get("/api/people/<pid>")
    def person_detail(pid):
        return jsonify(profiles().detail(pid))

    @app.post("/api/people")
    def create_person():
        return jsonify(profiles().create(ctx.body(), request.files.get("file"))), 201

    @app.put("/api/people/<pid>")
    def update_person(pid):
        return jsonify(profiles().update(pid, ctx.body(), upload=request.files.get("file")))

    @app.get("/api/people/<pid>/history")
    def person_history(pid):
        return jsonify(items=profiles().history(pid))

    @app.post("/api/people/<pid>/restore/<int:revision_id>")
    def restore_person(pid, revision_id):
        return jsonify(profiles().update(pid, ctx.body(), revision_id))

    @app.get("/api/people/<pid>/avatars/<avatar_id>")
    def person_avatar(pid, avatar_id):
        service = profiles()
        service.get(pid)
        metadata = service.avatar(pid, avatar_id)
        stored = ctx.db().execute("SELECT stored_name FROM person_avatars WHERE id=?", (avatar_id,)).fetchone()[0]
        return send_file(ctx.data_dir / "avatars" / stored, mimetype=metadata["mime_type"], download_name=metadata["name"])
