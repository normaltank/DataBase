"""Portable backups; restore only into a new directory, never overwrite live data."""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from .store import connect, now


def create_backup(data_dir):
    data_dir = Path(data_dir)
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    destination = backup_dir / ("research-backup-" + now()[:19].replace(":", "-") + "-" + uuid.uuid4().hex[:6] + ".zip")
    with tempfile.TemporaryDirectory(prefix="research-backup-") as temp:
        snapshot = Path(temp) / "platform.sqlite3"
        source, target = connect(data_dir / "platform.sqlite3"), sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        snapshot_db = connect(snapshot)
        try:
            uploaded = [r[0] for r in snapshot_db.execute("SELECT stored_name FROM attachments")]
            avatars = ([dict(r) for r in snapshot_db.execute("SELECT stored_name,sha256,bytes FROM person_avatars")]
                       if snapshot_db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='person_avatars'").fetchone() else [])
            setting = snapshot_db.execute("SELECT value FROM settings WHERE key='thinktank_import_v1'").fetchone()
        finally:
            snapshot_db.close()
        manifest = {"format": "research-commons-v1", "created_at": now(), "files": {}}
        payloads = {"platform.sqlite3": snapshot.read_bytes()}
        if setting:
            payloads["import-report.json"] = setting[0].encode("utf-8")
        for name in uploaded:
            if not re.fullmatch(r"[a-f0-9]{32}\.(pdf|docx|txt|md)", name):
                raise ValueError("Unexpected attachment name")
            payloads["uploads/" + name] = (data_dir / "uploads" / name).read_bytes()
        for avatar in avatars:
            name = avatar["stored_name"]
            if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", name):
                raise ValueError("Unexpected avatar name")
            content = (data_dir / "avatars" / name).read_bytes()
            if len(content) != avatar["bytes"] or hashlib.sha256(content).hexdigest() != avatar["sha256"]:
                raise ValueError("头像文件与登记信息不一致。")
            payloads["avatars/" + name] = content
        for name, content in payloads.items():
            manifest["files"][name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        partial = destination.with_suffix(".tmp")
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in payloads.items():
                    archive.writestr(name, content)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
    return destination


def restore_backup(archive_path, target_dir):
    target_dir = Path(target_dir).resolve()
    if target_dir.exists():
        raise ValueError("恢复目录必须尚不存在，避免覆盖正在使用的数据。")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="research-restore-", dir=target_dir.parent) as temp:
        stage = Path(temp) / "data"
        stage.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            names = [info.filename for info in entries]
            if len(names) != len(set(names)):
                raise ValueError("备份包含重复文件。")
            if any(info.file_size > 1024 * 1024 * 1024 for info in entries) or sum(info.file_size for info in entries) > 4 * 1024 * 1024 * 1024:
                raise ValueError("备份超出本地恢复工具大小限制。")
            for name in names:
                if (name not in ["platform.sqlite3", "manifest.json", "import-report.json"]
                        and not re.fullmatch(r"uploads/[a-f0-9]{32}\.(pdf|docx|txt|md)", name)
                        and not re.fullmatch(r"avatars/[a-f0-9]{32}\.(jpg|png|webp)", name)):
                    raise ValueError("备份包含未允许的文件路径。")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "research-commons-v1" or set(names) != set(manifest["files"]) | {"manifest.json"} or "platform.sqlite3" not in names:
                raise ValueError("备份格式或清单不完整。")
            for name, info in manifest["files"].items():
                content = archive.read(name)
                if len(content) != info["bytes"] or hashlib.sha256(content).hexdigest() != info["sha256"]:
                    raise ValueError("备份校验失败：" + name)
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
        db = connect(stage / "platform.sqlite3")
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("数据库完整性检查失败。")
            version = db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]
            if version not in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"}:
                raise ValueError("数据库版本不匹配。")
            from . import evidence
            if int(version) >= evidence.SCHEMA_VERSION:
                evidence.validate_backup(db)
            from . import collection_scope
            if int(version) >= collection_scope.SCHEMA_VERSION:
                collection_scope.validate_backup(db)
            if int(version) >= 11:
                from .saved_searches import validate_backup
                validate_backup(db)
            for row in db.execute("SELECT stored_name,sha256 FROM attachments"):
                name = "uploads/" + row["stored_name"]
                if name not in manifest["files"] or manifest["files"][name]["sha256"] != row["sha256"]:
                    raise ValueError("附件与数据库不一致。")
            if int(version) >= 6:
                for row in db.execute("SELECT stored_name,sha256,bytes FROM person_avatars"):
                    name = "avatars/" + row["stored_name"]
                    if (name not in manifest["files"] or manifest["files"][name]["sha256"] != row["sha256"]
                            or manifest["files"][name]["bytes"] != row["bytes"]):
                        raise ValueError("头像与数据库不一致。")
                from . import people
                people.validate_backup(db)
            if int(version) >= 7:
                from .note_subjects import validate_backup
                validate_backup(db)
            from . import bylines
            if int(version) >= bylines.SCHEMA_VERSION:
                bylines.validate_backup(db)
            from . import affiliations
            if int(version) >= affiliations.SCHEMA_VERSION:
                affiliations.validate_backup(db)
            from . import person_identity
            if int(version) >= person_identity.SCHEMA_VERSION:
                person_identity.validate_backup(db)
        finally:
            db.close()
        (stage / "uploads").mkdir(exist_ok=True)
        # The checked destination does not exist. Move only the newly created staging directory.
        shutil.move(str(stage), str(target_dir))
    return target_dir


def main():
    parser = argparse.ArgumentParser(description="平台备份/恢复（恢复到新目录）")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    if args.backup and not args.restore:
        print(create_backup(args.backup))
    elif args.restore and args.target and not args.backup:
        print(restore_backup(args.restore, args.target))
    else:
        parser.error("使用 --backup DATA_DIR 或 --restore ZIP --target NEW_DIR")


if __name__ == "__main__":
    main()
