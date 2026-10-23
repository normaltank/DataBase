"""Incremental research content model and safe, portable rich text."""
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

PERSONAL_KINDS = {"compilation", "research_note", "research_report"}
CONTENT_KINDS = PERSONAL_KINDS | {"directory_translation"}
RECORD_DEFAULTS = {
    "body_html": "", "body_text": "", "coverage": "", "original_catalogue": "", "aliases": "",
}
EVIDENCE_FIELDS = ["quote", "translation", "interpretation", "locator", "evidence_url", "evidence_record_id", "evidence_attachment_id"]
SOURCE_DEFAULTS = {"introduction_html": "", "introduction_text": "", "aliases": ""}
ALLOWED = {"p", "div", "br", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "ul", "ol", "li",
           "blockquote", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "a", "hr"}
BLOCKED = {"script", "style", "iframe", "object", "svg", "math", "template"}
VOID = {"br", "hr"}


def safe_link(value):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        parsed.port  # Access validates malformed and out-of-range port numbers.
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname) and parsed.username is None and parsed.password is None
    except ValueError:
        return False


class RichText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.text, self.stack, self.blocked = [], [], [], []

    def handle_starttag(self, tag, attrs):
        if self.blocked or tag in BLOCKED:
            if tag not in VOID:
                self.blocked.append(tag)
            return
        if tag not in ALLOWED:
            return
        attributes = []
        for key, value in attrs:
            if tag == "a" and key == "href" and value and safe_link(value):
                attributes.append('href="' + html.escape(value, quote=True) + '" rel="noopener noreferrer"')
            if tag in {"td", "th"} and key in {"colspan", "rowspan"} and value and value.isdigit() and 1 <= int(value) <= 20:
                attributes.append(f'{key}="{int(value)}"')
        self.parts.append("<" + tag + (" " + " ".join(attributes) if attributes else "") + ">")
        if tag not in VOID:
            self.stack.append(tag)
        if tag not in {"strong", "b", "em", "i", "u", "a"}:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if self.blocked:
            if tag in self.blocked:
                self.blocked = self.blocked[:self.blocked.index(tag)]
            return
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.parts.append("</" + current + ">")
                if current == tag:
                    break
            self.text.append("\n" if tag not in {"strong", "b", "em", "i", "u", "a"} else "")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(html.escape(data))
            self.text.append(data)


def clean_rich(value):
    if not isinstance(value, str) or len(value) > 500000:
        raise ValueError("正文格式不正确或超过 50 万字符。")
    parser = RichText()
    parser.feed(value)
    parser.close()
    while parser.stack:
        parser.parts.append("</" + parser.stack.pop() + ">")
    return "".join(parser.parts), re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", "".join(parser.text))).strip()


def snippet(text, query, size=180):
    words = query.strip().casefold().split()
    start = min((text.casefold().find(w) for w in words if w in text.casefold()), default=0)
    start = max(0, start - 45)
    return ("…" if start else "") + text[start:start + size] + ("…" if start + size < len(text) else "")


def source_ids(db, rid):
    return [r[0] for r in db.execute("SELECT source_id FROM record_sources WHERE record_id=? ORDER BY source_id", (rid,))]


def set_sources(db, rid, ids):
    db.execute("DELETE FROM record_sources WHERE record_id=?", (rid,))
    db.executemany("INSERT INTO record_sources VALUES (?,?)", [(rid, sid) for sid in ids])


def migrate(data_dir):
    from .store import connect
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= 3:
            return
        backup = None
        if db.execute("SELECT count(*) FROM records").fetchone()[0] or db.execute("SELECT count(*) FROM sources").fetchone()[0]:
            from .maintenance import create_backup
            backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for table, defaults in [("records", RECORD_DEFAULTS), ("sources", SOURCE_DEFAULTS)]:
                for key, value in defaults.items():
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {key} TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE records ADD COLUMN author_id TEXT REFERENCES users(id)")
            db.execute("ALTER TABLE records ADD COLUMN author_confirmed INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE record_sources(record_id TEXT NOT NULL REFERENCES records(id), source_id TEXT NOT NULL REFERENCES sources(id), PRIMARY KEY(record_id,source_id))")
            db.execute("CREATE INDEX idx_record_sources_source ON record_sources(source_id)")
            db.execute("UPDATE settings SET value='3' WHERE key='schema_version'")
            if backup:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('workflow_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def migrate_research(data_dir):
    from .store import connect
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= 4:
            return
        backup = None
        if db.execute("SELECT count(*) FROM records").fetchone()[0] or db.execute("SELECT count(*) FROM sources").fetchone()[0]:
            from .maintenance import create_backup
            backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for table in ["sources", "records"]:
                db.execute(f"ALTER TABLE {table} ADD COLUMN merged_into TEXT REFERENCES {table}(id)")
            for name in EVIDENCE_FIELDS:
                db.execute(f"ALTER TABLE records ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE records ADD COLUMN evidence_version INTEGER")
            db.execute("ALTER TABLE records ADD COLUMN evidence_snapshot_json TEXT NOT NULL DEFAULT '{}'")
            db.execute("CREATE INDEX idx_evidence_record ON records(evidence_record_id)")
            db.execute("CREATE TABLE evidence_links(report_id TEXT NOT NULL REFERENCES records(id), excerpt_id TEXT NOT NULL REFERENCES records(id), excerpt_version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, PRIMARY KEY(report_id,excerpt_id), CHECK(report_id<>excerpt_id))")
            db.execute("CREATE TABLE merge_events(id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, keep_id TEXT NOT NULL, duplicate_id TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL)")
            db.execute("UPDATE settings SET value='4' WHERE key='schema_version'")
            if backup:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('research_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def migrate_operations(data_dir):
    from .store import connect
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= 5:
            return
        backup = None
        if db.execute("SELECT count(*) FROM records").fetchone()[0] or db.execute("SELECT count(*) FROM sources").fetchone()[0]:
            from .maintenance import create_backup
            backup = create_backup(data_dir)
        with db:
            db.execute("BEGIN IMMEDIATE")
            for name in ["research_question", "comparison_html", "comparison_text", "stage_judgment", "updated_at"]:
                db.execute(f"ALTER TABLE collections ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE collections ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            db.execute("ALTER TABLE users ADD COLUMN credential_version INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE member_events(id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id), member_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, created_at TEXT NOT NULL)")
            db.execute("UPDATE settings SET value='5' WHERE key='schema_version'")
            if backup:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('operations_migration_backup',?)", (str(backup),))
    finally:
        db.close()
