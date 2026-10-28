"""Immutable original files; callers own business authorization and references.

No unrestricted file route is registered here. Each business must authorize the
specific work and submission before calling original_path or exposing metadata.
"""
import hashlib
import io
import re
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from flask import abort

from .store import now

MAX_BYTES = 20 * 1024 * 1024
STORED_NAME = r"[a-f0-9]{32}\.(pdf|docx|txt|md)"


def read_upload(file):
    """Same accepted originals for existing attachments and new handoffs."""
    if not file or not file.filename:
        abort(400, "请选择提交文件。")
    name = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
    if len(name) > 180 or any(ord(c) < 32 for c in name):
        abort(400, "文件名过长或包含无效字符。")
    suffix = Path(name).suffix.lower()
    if suffix not in [".pdf", ".docx", ".txt", ".md"]:
        abort(400, "支持 PDF、DOCX、TXT 和 Markdown，单文件最多 20 MB。")
    content = file.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
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
    return name, suffix, content


@contextmanager
def transaction(db):
    """Commit a whole handoff, cleaning even partial file writes on failure."""
    if db.in_transaction:
        raise RuntimeError("Handoff must own its transaction.")
    created = []
    try:
        db.execute("BEGIN IMMEDIATE")
        yield created
        db.commit()
    except BaseException:
        db.rollback()
        for path in created:
            path.unlink(missing_ok=True)
        raise


def save_original(db, data_dir, actor_id, uploaded, created):
    """Write inside transaction(); never share this identity across submissions."""
    name, suffix, content = uploaded
    fid = uuid.uuid4().hex
    directory = Path(data_dir) / "handoffs"
    directory.mkdir(exist_ok=True)
    path = directory / (fid + suffix)
    created.append(path)
    with path.open("xb") as stream:
        stream.write(content)
    db.execute("INSERT INTO handoff_files VALUES (?,?,?,?,?,?,?)", (fid, name, path.name, len(content), hashlib.sha256(content).hexdigest(), actor_id, now()))
    return fid


def original_path(data_dir, row):
    if not re.fullmatch(STORED_NAME, row["stored_name"]):
        abort(404, "原件不可用。")
    path = Path(data_dir) / "handoffs" / row["stored_name"]
    if not path.is_file():
        abort(404, "原件暂不可用，请联系管理员核查备份。")
    content = path.read_bytes()
    if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
        abort(409, "原件校验未通过，请联系管理员核查备份。")
    return path


def validate_backup(db, manifest):
    for row in db.execute("SELECT * FROM handoff_files"):
        item = manifest["files"].get("handoffs/" + row["stored_name"])
        if (not re.fullmatch(STORED_NAME, row["stored_name"]) or row["stored_name"].split(".")[0] != row["id"]
                or not item or item["sha256"] != row["sha256"] or item["bytes"] != row["bytes"] or row["bytes"] <= 0):
            raise ValueError("交接原件与登记信息不一致。")
