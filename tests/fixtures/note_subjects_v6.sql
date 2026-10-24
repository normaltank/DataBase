-- Frozen synthetic schema 6 overlay for people_v5.sql; no research-subject tables.
CREATE TABLE people (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT NOT NULL DEFAULT '',
 chinese_name TEXT NOT NULL DEFAULT '', aliases TEXT NOT NULL DEFAULT '',
 introduction_html TEXT NOT NULL DEFAULT '', introduction_text TEXT NOT NULL DEFAULT '',
 sources TEXT NOT NULL DEFAULT '', change_note TEXT NOT NULL,
 avatar_id TEXT REFERENCES person_avatars(id), avatar_source TEXT NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE person_avatars (
 id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id), name TEXT NOT NULL,
 stored_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, bytes INTEGER NOT NULL,
 sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
INSERT INTO people(id,name,change_note,created_at,updated_at)
 VALUES('person-v6-fixture','Frozen v6 synthetic person','Frozen synthetic homepage','2026-10-24T00:00:00+00:00','2026-10-24T00:00:00+00:00');
UPDATE settings SET value='6' WHERE key='schema_version';
