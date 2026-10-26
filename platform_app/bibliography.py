"""Publication positioning as recorded in the original bibliographic source."""
from pathlib import Path

from .store import connect

SCHEMA_VERSION = 12
FIELDS = ('volume', 'issue', 'pages', 'issn')


def migrate(data_dir):
    db = connect(Path(data_dir) / 'platform.sqlite3')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            for field in FIELDS:
                db.execute(f"ALTER TABLE records ADD COLUMN {field} TEXT NOT NULL DEFAULT ''")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('bibliography_migration_backup',?)", (str(backup),))
    finally:
        db.close()
