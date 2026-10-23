import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT DEFAULT '', kind TEXT NOT NULL,
 classification TEXT DEFAULT '', location TEXT DEFAULT '', country TEXT DEFAULT '',
 research_scope TEXT DEFAULT '', website TEXT DEFAULT '', catalogue_url TEXT DEFAULT '',
 host_id TEXT DEFAULT '', publisher_id TEXT DEFAULT '', issn TEXT DEFAULT '',
 scope_status TEXT DEFAULT 'candidate', status TEXT NOT NULL DEFAULT 'pending',
 notes TEXT DEFAULT '', upstream_status TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, original_title TEXT DEFAULT '',
 authors TEXT DEFAULT '', source_id TEXT REFERENCES sources(id), serial_id TEXT REFERENCES sources(id),
 publication_title TEXT DEFAULT '', published_on TEXT DEFAULT '', language TEXT DEFAULT '',
 abstract TEXT DEFAULT '', keywords TEXT DEFAULT '', countries TEXT DEFAULT '',
 doi TEXT DEFAULT '', url TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
 visibility TEXT NOT NULL DEFAULT 'shared', owner_id TEXT NOT NULL REFERENCES users(id),
 editors TEXT NOT NULL DEFAULT '[]', attachment_ids TEXT NOT NULL DEFAULT '[]',
 unresolved_refs TEXT DEFAULT '', upstream_status TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS record_links (
 report_id TEXT NOT NULL REFERENCES records(id), original_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(report_id, original_id), CHECK(report_id <> original_id));
CREATE TABLE IF NOT EXISTS attachments (
 id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id), name TEXT NOT NULL,
 stored_name TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS favorites (
 user_id TEXT NOT NULL REFERENCES users(id), record_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(user_id, record_id));
CREATE TABLE IF NOT EXISTS collections (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
 visibility TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collection_items (
 collection_id TEXT NOT NULL REFERENCES collections(id), record_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(collection_id, record_id));
CREATE TABLE IF NOT EXISTS revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 action TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 snapshot_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_records_date ON records(published_on DESC);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source_id);
CREATE INDEX IF NOT EXISTS idx_revisions_target ON revisions(target_type, target_id);
"""


def initialize(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)
    db = connect(data_dir / "platform.sqlite3")
    db.executescript(SCHEMA)
    db.execute("INSERT OR IGNORE INTO settings VALUES ('schema_version','1')")
    for uid, username, name, role in [
        ("admin", "admin", "资料管理员", "admin"),
        ("researcher", "researcher", "研究员 · 林", "researcher"),
        ("colleague", "colleague", "研究员 · 周", "researcher"),
    ]:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            db.execute("INSERT INTO users (id,username,name,password_hash,role) VALUES (?,?,?,?,?)",
                       (uid, username, name, generate_password_hash("LocalDemo2026!"), role))
    db.commit()
    db.close()
    from .source_catalog import migrate
    migrate(data_dir)
    from .workflow import migrate as migrate_workflow
    migrate_workflow(data_dir)
    from .workflow import migrate_research
    migrate_research(data_dir)
    from .workflow import migrate_operations
    migrate_operations(data_dir)


def decoded(row):
    obj = dict(row)
    for key in ("editors", "attachment_ids", "raw_json"):
        if key in obj:
            obj[key] = json.loads(obj[key])
    return obj


def save_revision(db, kind, row_id, action, actor):
    table = {"record": "records", "source": "sources", "collection": "collections"}[kind]
    snapshot = dict(db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone())
    if kind == "record":
        snapshot["linked_ids"] = [r[0] for r in db.execute(
            "SELECT original_id FROM record_links WHERE report_id=? ORDER BY original_id", (row_id,))]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='record_sources'").fetchone():
            from .workflow import source_ids
            snapshot["related_source_ids"] = source_ids(db, row_id)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_links'").fetchone():
            snapshot["evidence_citations"] = [dict(r) for r in db.execute("SELECT * FROM evidence_links WHERE report_id=?", (row_id,))]
    if kind == "collection":
        snapshot["item_ids"] = [r[0] for r in db.execute("SELECT record_id FROM collection_items WHERE collection_id=? ORDER BY record_id", (row_id,))]
    db.execute("INSERT INTO revisions(target_type,target_id,action,actor_id,created_at,snapshot_json) VALUES (?,?,?,?,?,?)",
               (kind, row_id, action, actor, now(), json.dumps(snapshot, ensure_ascii=False)))
