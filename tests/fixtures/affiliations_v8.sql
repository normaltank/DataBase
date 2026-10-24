-- Frozen synthetic schema 8 from commit 32a60f5786b379cbafe4256a5a5b24fb60663c4c.
-- Created through that commit's authenticated HTTP API on 2026-10-24; no external data or files.
-- Runtime backup-path settings are omitted; demo password hashes use the public local demo password.
BEGIN TRANSACTION;
CREATE TABLE attachments (
 id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id), name TEXT NOT NULL,
 stored_name TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE byline_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                change_kind TEXT NOT NULL, change_note TEXT NOT NULL, identity_event_id TEXT,
                before_json TEXT, after_json TEXT NOT NULL);
INSERT INTO "byline_changes" VALUES(1,'byline-a2a9744f5954429eaeea2d405573034d','researcher','2026-10-24T06:35:08+00:00','manual','旧版人工署名确认',NULL,NULL,'{"id": "byline-a2a9744f5954429eaeea2d405573034d", "record_id": "LOCAL-691904EA313C", "origin_record_id": "LOCAL-691904EA313C", "original_authors": "Frozen V8 Author; 未确认署名", "raw_name": "Frozen V8 Author", "position": 1, "status": "confirmed", "original_target_type": "person", "original_target_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "selected_target_type": "person", "selected_target_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "target_type": "person", "target_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "evidence": "https://example.org/frozen-v8#author", "version": 1, "manual_revision": 1, "removed_at": null, "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00"}');
INSERT INTO "byline_changes" VALUES(2,'byline-6c4d9b2245894c7c83b990c6d4b30745','researcher','2026-10-24T06:35:08+00:00','manual','旧版人工署名确认',NULL,NULL,'{"id": "byline-6c4d9b2245894c7c83b990c6d4b30745", "record_id": "LOCAL-691904EA313C", "origin_record_id": "LOCAL-691904EA313C", "original_authors": "Frozen V8 Author; 未确认署名", "raw_name": "未确认署名", "position": 2, "status": "pending", "original_target_type": "", "original_target_id": null, "selected_target_type": "", "selected_target_id": null, "target_type": "", "target_id": null, "evidence": "", "version": 1, "manual_revision": 1, "removed_at": null, "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00"}');
CREATE TABLE collection_items (
 collection_id TEXT NOT NULL REFERENCES collections(id), record_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(collection_id, record_id));
CREATE TABLE collections (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
 visibility TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, research_question TEXT NOT NULL DEFAULT '', comparison_html TEXT NOT NULL DEFAULT '', comparison_text TEXT NOT NULL DEFAULT '', stage_judgment TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE evidence_links(report_id TEXT NOT NULL REFERENCES records(id), excerpt_id TEXT NOT NULL REFERENCES records(id), excerpt_version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, PRIMARY KEY(report_id,excerpt_id), CHECK(report_id<>excerpt_id));
CREATE TABLE favorites (
 user_id TEXT NOT NULL REFERENCES users(id), record_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(user_id, record_id));
CREATE TABLE member_events(id INTEGER PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id), member_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE merge_events(id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, keep_id TEXT NOT NULL, duplicate_id TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL);
CREATE TABLE people (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT NOT NULL DEFAULT '',
                chinese_name TEXT NOT NULL DEFAULT '', aliases TEXT NOT NULL DEFAULT '',
                introduction_html TEXT NOT NULL DEFAULT '', introduction_text TEXT NOT NULL DEFAULT '',
                sources TEXT NOT NULL DEFAULT '', change_note TEXT NOT NULL,
                avatar_id TEXT REFERENCES person_avatars(id), avatar_source TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "people" VALUES('person-86c54443e4ab47d2bb92c1947f2f99c3','冻结八版合成人物','Frozen V8 Author','','','<p>固定旧版的纯合成人物介绍。</p>','固定旧版的纯合成人物介绍。','','合成主页',NULL,'',1,'2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00');
CREATE TABLE person_avatars (
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id), name TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE record_byline_state (
                record_id TEXT PRIMARY KEY REFERENCES records(id), version INTEGER NOT NULL);
INSERT INTO "record_byline_state" VALUES('LOCAL-691904EA313C',1);
CREATE TABLE record_bylines (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
                origin_record_id TEXT NOT NULL REFERENCES records(id), original_authors TEXT NOT NULL,
                raw_name TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL,
                original_target_type TEXT NOT NULL, original_target_id TEXT,
                selected_target_type TEXT NOT NULL, selected_target_id TEXT,
                target_type TEXT NOT NULL, target_id TEXT, evidence TEXT NOT NULL,
                version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "record_bylines" VALUES('byline-a2a9744f5954429eaeea2d405573034d','LOCAL-691904EA313C','LOCAL-691904EA313C','Frozen V8 Author; 未确认署名','Frozen V8 Author',1,'confirmed','person','person-86c54443e4ab47d2bb92c1947f2f99c3','person','person-86c54443e4ab47d2bb92c1947f2f99c3','person','person-86c54443e4ab47d2bb92c1947f2f99c3','https://example.org/frozen-v8#author',1,1,NULL,'2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00');
INSERT INTO "record_bylines" VALUES('byline-6c4d9b2245894c7c83b990c6d4b30745','LOCAL-691904EA313C','LOCAL-691904EA313C','Frozen V8 Author; 未确认署名','未确认署名',2,'pending','',NULL,'',NULL,'',NULL,'',1,1,NULL,'2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00');
CREATE TABLE record_links (
 report_id TEXT NOT NULL REFERENCES records(id), original_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(report_id, original_id), CHECK(report_id <> original_id));
CREATE TABLE record_sources(record_id TEXT NOT NULL REFERENCES records(id), source_id TEXT NOT NULL REFERENCES sources(id), PRIMARY KEY(record_id,source_id));
CREATE TABLE records (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, original_title TEXT DEFAULT '',
 authors TEXT DEFAULT '', source_id TEXT REFERENCES sources(id), serial_id TEXT REFERENCES sources(id),
 publication_title TEXT DEFAULT '', published_on TEXT DEFAULT '', language TEXT DEFAULT '',
 abstract TEXT DEFAULT '', keywords TEXT DEFAULT '', countries TEXT DEFAULT '',
 doi TEXT DEFAULT '', url TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
 visibility TEXT NOT NULL DEFAULT 'shared', owner_id TEXT NOT NULL REFERENCES users(id),
 editors TEXT NOT NULL DEFAULT '[]', attachment_ids TEXT NOT NULL DEFAULT '[]',
 unresolved_refs TEXT DEFAULT '', upstream_status TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, body_html TEXT NOT NULL DEFAULT '', body_text TEXT NOT NULL DEFAULT '', coverage TEXT NOT NULL DEFAULT '', original_catalogue TEXT NOT NULL DEFAULT '', aliases TEXT NOT NULL DEFAULT '', author_id TEXT REFERENCES users(id), author_confirmed INTEGER NOT NULL DEFAULT 0, merged_into TEXT REFERENCES records(id), quote TEXT NOT NULL DEFAULT '', translation TEXT NOT NULL DEFAULT '', interpretation TEXT NOT NULL DEFAULT '', locator TEXT NOT NULL DEFAULT '', evidence_url TEXT NOT NULL DEFAULT '', evidence_record_id TEXT NOT NULL DEFAULT '', evidence_attachment_id TEXT NOT NULL DEFAULT '', evidence_version INTEGER, evidence_snapshot_json TEXT NOT NULL DEFAULT '{}');
INSERT INTO "records" VALUES('LOCAL-691904EA313C','report','冻结八版原始资料','','Frozen V8 Author; 未确认署名',NULL,NULL,'','','','','','','','','pending','shared','researcher','[]','[]','','','{}',1,'2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00','<p>旧版原始正文。</p>','旧版原始正文。','','','',NULL,0,NULL,'','','','','','','',NULL,'{}');
INSERT INTO "records" VALUES('LOCAL-E17885C34DE5','research_note','冻结八版比较笔记','','',NULL,NULL,'','','','','','','','','pending','shared','researcher','[]','[]','','','{}',1,'2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00','<p>旧版作者独立研究判断。</p>','旧版作者独立研究判断。','','','','researcher',1,NULL,'','','','','','','',NULL,'{}');
CREATE TABLE research_subject_history (
                id INTEGER PRIMARY KEY, relation_id TEXT NOT NULL REFERENCES research_subjects(id),
                action TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL);
INSERT INTO "research_subject_history" VALUES(1,'subject-31cbc6750b4e487883be1d2968e3ff3a','created','researcher','2026-10-24T06:35:08+00:00','{"id": "subject-31cbc6750b4e487883be1d2968e3ff3a", "note_id": "LOCAL-E17885C34DE5", "original_note_id": "LOCAL-E17885C34DE5", "subject_type": "person", "subject_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "original_subject_type": "person", "original_subject_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "status": "confirmed", "version": 1, "manual_revision": 1, "created_by": "researcher", "updated_by": "researcher", "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00", "subject_name": "冻结八版合成人物", "original_subject_name": "冻结八版合成人物"}');
INSERT INTO "research_subject_history" VALUES(2,'subject-29bb37b78c1f47ee9d2f6dc08fba224a','created','researcher','2026-10-24T06:35:08+00:00','{"id": "subject-29bb37b78c1f47ee9d2f6dc08fba224a", "note_id": "LOCAL-E17885C34DE5", "original_note_id": "LOCAL-E17885C34DE5", "subject_type": "institution", "subject_id": "SRC-LOCAL-E8FD545384", "original_subject_type": "institution", "original_subject_id": "SRC-LOCAL-E8FD545384", "status": "confirmed", "version": 1, "manual_revision": 1, "created_by": "researcher", "updated_by": "researcher", "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00", "subject_name": "冻结八版合成机构", "original_subject_name": "冻结八版合成机构"}');
CREATE TABLE research_subjects (
                id TEXT PRIMARY KEY, note_id TEXT NOT NULL REFERENCES records(id),
                original_note_id TEXT NOT NULL REFERENCES records(id), subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL, original_subject_type TEXT NOT NULL, original_subject_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed', version INTEGER NOT NULL DEFAULT 1,
                manual_revision INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL REFERENCES users(id), updated_by TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                CHECK(subject_type IN ('person','institution','journal')),
                CHECK(original_subject_type IN ('person','institution','journal')),
                CHECK(status IN ('confirmed','needs_review','removed')));
INSERT INTO "research_subjects" VALUES('subject-31cbc6750b4e487883be1d2968e3ff3a','LOCAL-E17885C34DE5','LOCAL-E17885C34DE5','person','person-86c54443e4ab47d2bb92c1947f2f99c3','person','person-86c54443e4ab47d2bb92c1947f2f99c3','confirmed',1,1,'researcher','researcher','2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00');
INSERT INTO "research_subjects" VALUES('subject-29bb37b78c1f47ee9d2f6dc08fba224a','LOCAL-E17885C34DE5','LOCAL-E17885C34DE5','institution','SRC-LOCAL-E8FD545384','institution','SRC-LOCAL-E8FD545384','confirmed',1,1,'researcher','researcher','2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00');
CREATE TABLE revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 action TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 snapshot_json TEXT NOT NULL);
INSERT INTO "revisions" VALUES(1,'person','person-86c54443e4ab47d2bb92c1947f2f99c3','建立人物档案','researcher','2026-10-24T06:35:08+00:00','{"id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "name": "冻结八版合成人物", "original_name": "Frozen V8 Author", "chinese_name": "", "aliases": "", "introduction_html": "<p>固定旧版的纯合成人物介绍。</p>", "introduction_text": "固定旧版的纯合成人物介绍。", "sources": "", "change_note": "合成主页", "avatar_id": null, "avatar_source": "", "version": 1, "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00"}');
INSERT INTO "revisions" VALUES(2,'source','SRC-LOCAL-E8FD545384','提交来源','researcher','2026-10-24T06:35:08+00:00','{"id": "SRC-LOCAL-E8FD545384", "name": "冻结八版合成机构", "original_name": "", "kind": "institution", "classification": "", "location": "", "country": "", "research_scope": "", "website": "", "catalogue_url": "", "host_id": "", "publisher_id": "", "issn": "", "scope_status": "candidate", "status": "pending", "notes": "", "upstream_status": "", "raw_json": "{}", "version": 1, "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00", "institution_types": "[]", "relationships": "[]", "country_evidence": "", "host_evidence": "", "host_country_status": "auto", "international_status": "unknown", "international_evidence": "", "introduction_html": "", "introduction_text": "", "aliases": "", "merged_into": null}');
INSERT INTO "revisions" VALUES(3,'record','LOCAL-691904EA313C','提交资料','researcher','2026-10-24T06:35:08+00:00','{"id": "LOCAL-691904EA313C", "kind": "report", "title": "冻结八版原始资料", "original_title": "", "authors": "Frozen V8 Author; 未确认署名", "source_id": null, "serial_id": null, "publication_title": "", "published_on": "", "language": "", "abstract": "", "keywords": "", "countries": "", "doi": "", "url": "", "status": "pending", "visibility": "shared", "owner_id": "researcher", "editors": "[]", "attachment_ids": "[]", "unresolved_refs": "", "upstream_status": "", "raw_json": "{}", "version": 1, "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00", "body_html": "<p>旧版原始正文。</p>", "body_text": "旧版原始正文。", "coverage": "", "original_catalogue": "", "aliases": "", "author_id": null, "author_confirmed": 0, "merged_into": null, "quote": "", "translation": "", "interpretation": "", "locator": "", "evidence_url": "", "evidence_record_id": "", "evidence_attachment_id": "", "evidence_version": null, "evidence_snapshot_json": "{}", "linked_ids": [], "related_source_ids": [], "evidence_citations": [], "research_subjects": []}');
INSERT INTO "revisions" VALUES(4,'record','LOCAL-E17885C34DE5','提交资料','researcher','2026-10-24T06:35:08+00:00','{"id": "LOCAL-E17885C34DE5", "kind": "research_note", "title": "冻结八版比较笔记", "original_title": "", "authors": "", "source_id": null, "serial_id": null, "publication_title": "", "published_on": "", "language": "", "abstract": "", "keywords": "", "countries": "", "doi": "", "url": "", "status": "pending", "visibility": "shared", "owner_id": "researcher", "editors": "[]", "attachment_ids": "[]", "unresolved_refs": "", "upstream_status": "", "raw_json": "{}", "version": 1, "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00", "body_html": "<p>旧版作者独立研究判断。</p>", "body_text": "旧版作者独立研究判断。", "coverage": "", "original_catalogue": "", "aliases": "", "author_id": "researcher", "author_confirmed": 1, "merged_into": null, "quote": "", "translation": "", "interpretation": "", "locator": "", "evidence_url": "", "evidence_record_id": "", "evidence_attachment_id": "", "evidence_version": null, "evidence_snapshot_json": "{}", "linked_ids": [], "related_source_ids": [], "evidence_citations": [], "research_subjects": [{"id": "subject-29bb37b78c1f47ee9d2f6dc08fba224a", "note_id": "LOCAL-E17885C34DE5", "original_note_id": "LOCAL-E17885C34DE5", "subject_type": "institution", "subject_id": "SRC-LOCAL-E8FD545384", "original_subject_type": "institution", "original_subject_id": "SRC-LOCAL-E8FD545384", "status": "confirmed", "version": 1, "manual_revision": 1, "created_by": "researcher", "updated_by": "researcher", "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00"}, {"id": "subject-31cbc6750b4e487883be1d2968e3ff3a", "note_id": "LOCAL-E17885C34DE5", "original_note_id": "LOCAL-E17885C34DE5", "subject_type": "person", "subject_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "original_subject_type": "person", "original_subject_id": "person-86c54443e4ab47d2bb92c1947f2f99c3", "status": "confirmed", "version": 1, "manual_revision": 1, "created_by": "researcher", "updated_by": "researcher", "created_at": "2026-10-24T06:35:08+00:00", "updated_at": "2026-10-24T06:35:08+00:00"}]}');
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "settings" VALUES('schema_version','8');
CREATE TABLE sources (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT DEFAULT '', kind TEXT NOT NULL,
 classification TEXT DEFAULT '', location TEXT DEFAULT '', country TEXT DEFAULT '',
 research_scope TEXT DEFAULT '', website TEXT DEFAULT '', catalogue_url TEXT DEFAULT '',
 host_id TEXT DEFAULT '', publisher_id TEXT DEFAULT '', issn TEXT DEFAULT '',
 scope_status TEXT DEFAULT 'candidate', status TEXT NOT NULL DEFAULT 'pending',
 notes TEXT DEFAULT '', upstream_status TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, institution_types TEXT NOT NULL DEFAULT '[]', relationships TEXT NOT NULL DEFAULT '[]', country_evidence TEXT NOT NULL DEFAULT '', host_evidence TEXT NOT NULL DEFAULT '', host_country_status TEXT NOT NULL DEFAULT 'auto', international_status TEXT NOT NULL DEFAULT 'unknown', international_evidence TEXT NOT NULL DEFAULT '', introduction_html TEXT NOT NULL DEFAULT '', introduction_text TEXT NOT NULL DEFAULT '', aliases TEXT NOT NULL DEFAULT '', merged_into TEXT REFERENCES sources(id));
INSERT INTO "sources" VALUES('SRC-LOCAL-E8FD545384','冻结八版合成机构','','institution','','','','','','','','','','candidate','pending','','','{}',1,'2026-10-24T06:35:08+00:00','2026-10-24T06:35:08+00:00','[]','[]','','','auto','unknown','','','','',NULL);
CREATE TABLE users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, credential_version INTEGER NOT NULL DEFAULT 0);
INSERT INTO "users" VALUES('admin','admin','资料管理员','scrypt:32768:8:1$fHVtCkMzJMBMACq8$af844632865687b177f0e4126fbbd0eef8f9170b0a554d0142ec1dbc21bf63ee3ba876b7dd83cfa923c2fdaff817e7d0ba936f92dd3cbc7b52ed63f39282528d','admin',1,0);
INSERT INTO "users" VALUES('researcher','researcher','研究员 · 林','scrypt:32768:8:1$2yJyMY5h6sBtAqQf$3e71b3c9fc579db7fed968898abae14b1139e925a7f8e7d64b8deef4adda9ee29e485889d5f0f202029434a2880296ecc650614a7f0984cf0da1340b6c4a4c98','researcher',1,0);
INSERT INTO "users" VALUES('colleague','colleague','研究员 · 周','scrypt:32768:8:1$q5phFX8A2ailbHz8$305213eed56b215b8a3e3c9a722bf64b9c890d69498d4f0941cef16b73ec4f54ac7cbbadc2ac008e0805b3bc6817cc6ee6eb0b13292dba7f6e7aa925993a20b3','researcher',1,0);
CREATE INDEX idx_records_date ON records(published_on DESC);
CREATE INDEX idx_records_source ON records(source_id);
CREATE INDEX idx_revisions_target ON revisions(target_type, target_id);
CREATE INDEX idx_record_sources_source ON record_sources(source_id);
CREATE INDEX idx_evidence_record ON records(evidence_record_id);
CREATE INDEX idx_subject_note ON research_subjects(note_id,status);
CREATE INDEX idx_subject_target ON research_subjects(subject_type,subject_id,status);
CREATE INDEX idx_byline_record ON record_bylines(record_id,position,id);
CREATE INDEX idx_byline_target ON record_bylines(target_type,target_id,status);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('revisions',4);
INSERT INTO "sqlite_sequence" VALUES('byline_changes',2);
COMMIT;
