import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

CURRENT_SCHEMA_VERSION = 15


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
    from .people import migrate as migrate_people
    migrate_people(data_dir)
    from .note_subjects import migrate as migrate_note_subjects
    migrate_note_subjects(data_dir)
    from .bylines import migrate as migrate_bylines
    migrate_bylines(data_dir)
    from .affiliations import migrate as migrate_affiliations
    migrate_affiliations(data_dir)
    from .person_identity import migrate as migrate_person_identity
    migrate_person_identity(data_dir)
    from .saved_searches import migrate as migrate_saved_searches
    migrate_saved_searches(data_dir)
    from .bibliography import migrate as migrate_bibliography
    migrate_bibliography(data_dir)
    from .evidence import migrate as migrate_citations
    migrate_citations(data_dir)
    from .collection_scope import migrate as migrate_collection_scope
    migrate_collection_scope(data_dir)
    from .translations import migrate as migrate_translations
    migrate_translations(data_dir)


def decoded(row):
    obj = dict(row)
    for key in ("editors", "attachment_ids", "raw_json"):
        if key in obj:
            obj[key] = json.loads(obj[key])
    return obj


def save_revision(db, kind, row_id, action, actor, review_event=None):
    table = {"record": "records", "source": "sources", "collection": "collections", "person": "people"}[kind]
    if kind == "record":
        from .record_revisions import snapshot as record_snapshot
        snapshot = record_snapshot(db, row_id)
    else:
        snapshot = dict(db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone())
    if kind == "collection":
        snapshot["item_details"] = [dict(r) for r in db.execute("SELECT record_id,disposition,rationale FROM collection_items WHERE collection_id=? ORDER BY record_id", (row_id,))]
        snapshot["item_ids"] = [r[0] for r in db.execute("SELECT record_id FROM collection_items WHERE collection_id=? ORDER BY record_id", (row_id,))]
    if review_event is not None:
        snapshot["review_event"] = review_event
    db.execute("INSERT INTO revisions(target_type,target_id,action,actor_id,created_at,snapshot_json) VALUES (?,?,?,?,?,?)",
               (kind, row_id, action, actor, now(), json.dumps(snapshot, ensure_ascii=False)))
