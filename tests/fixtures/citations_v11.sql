BEGIN TRANSACTION;
CREATE TABLE affiliation_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, relation_type TEXT NOT NULL, relation_id TEXT NOT NULL,
                actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                change_kind TEXT NOT NULL, change_note TEXT NOT NULL, identity_event_id TEXT,
                before_json TEXT, after_json TEXT NOT NULL);
CREATE TABLE attachments (
 id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id), name TEXT NOT NULL,
 stored_name TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE byline_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                change_kind TEXT NOT NULL, change_note TEXT NOT NULL, identity_event_id TEXT,
                before_json TEXT, after_json TEXT NOT NULL);
CREATE TABLE collection_items (
 collection_id TEXT NOT NULL REFERENCES collections(id), record_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(collection_id, record_id));
CREATE TABLE collections (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
 visibility TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, research_question TEXT NOT NULL DEFAULT '', comparison_html TEXT NOT NULL DEFAULT '', comparison_text TEXT NOT NULL DEFAULT '', stage_judgment TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE evidence_links(report_id TEXT NOT NULL REFERENCES records(id), excerpt_id TEXT NOT NULL REFERENCES records(id), excerpt_version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, PRIMARY KEY(report_id,excerpt_id), CHECK(report_id<>excerpt_id));
INSERT INTO "evidence_links" VALUES('LOCAL-D542ED159725','LOCAL-2CD562B1C477',1,'{"id": "LOCAL-2CD562B1C477", "kind": "research_note", "title": "旧摘录", "original_title": "", "authors": "", "published_on": "", "url": "", "doi": "", "version": 1, "body_html": "", "body_text": "", "abstract": "", "quote": "旧原句", "translation": "", "interpretation": "", "locator": "第1段", "evidence_record_id": "LOCAL-C210F2BAB9B0", "evidence_version": 1, "evidence_url": "", "evidence_attachment_id": "", "evidence_snapshot_json": "{\"id\": \"LOCAL-C210F2BAB9B0\", \"kind\": \"report\", \"title\": \"旧原文\", \"original_title\": \"\", \"authors\": \"\", \"published_on\": \"\", \"url\": \"\", \"doi\": \"\", \"version\": 1}"}');
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
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, merged_into TEXT REFERENCES people(id));
CREATE TABLE person_avatars (
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id), name TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE person_employment_state (
                person_id TEXT PRIMARY KEY REFERENCES people(id), version INTEGER NOT NULL);
CREATE TABLE person_employments (
                id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id),
                original_person_id TEXT NOT NULL REFERENCES people(id),
                selected_person_id TEXT NOT NULL REFERENCES people(id),
                institution_id TEXT NOT NULL REFERENCES sources(id),
                original_institution_id TEXT NOT NULL REFERENCES sources(id),
                selected_institution_id TEXT NOT NULL REFERENCES sources(id),
                role TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                evidence TEXT NOT NULL, version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE person_identity_events (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL CHECK(event_type IN ('merge','split')),
                merge_event_id TEXT REFERENCES person_identity_events(id),
                keep_id TEXT NOT NULL REFERENCES people(id), duplicate_id TEXT NOT NULL REFERENCES people(id),
                actor_id TEXT NOT NULL REFERENCES users(id), evidence TEXT NOT NULL, choices_json TEXT NOT NULL,
                dependencies_json TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                created_at TEXT NOT NULL, CHECK(keep_id<>duplicate_id));
CREATE TABLE person_identity_previews (
                id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
                keep_id TEXT NOT NULL REFERENCES people(id), duplicate_id TEXT NOT NULL REFERENCES people(id),
                event_id TEXT REFERENCES person_identity_events(id), fingerprint TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE person_identity_requests (
                actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, request_key TEXT NOT NULL,
                intent_hash TEXT NOT NULL, result_json TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES person_identity_events(id),
                PRIMARY KEY(actor_id,action,request_key));
CREATE TABLE person_merge_state (
                event_id TEXT PRIMARY KEY REFERENCES person_identity_events(id),
                status TEXT NOT NULL CHECK(status IN ('active','split')), version INTEGER NOT NULL,
                split_event_id TEXT REFERENCES person_identity_events(id));
CREATE TABLE record_affiliation_state (
                record_id TEXT PRIMARY KEY REFERENCES records(id), version INTEGER NOT NULL);
CREATE TABLE record_affiliations (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
                origin_record_id TEXT NOT NULL REFERENCES records(id),
                byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                original_byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                selected_byline_id TEXT NOT NULL REFERENCES record_bylines(id),
                original_byline_json TEXT NOT NULL, byline_snapshot_json TEXT NOT NULL,
                institution_id TEXT NOT NULL REFERENCES sources(id),
                original_institution_id TEXT NOT NULL REFERENCES sources(id),
                selected_institution_id TEXT NOT NULL REFERENCES sources(id),
                evidence TEXT NOT NULL, version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE record_byline_state (
                record_id TEXT PRIMARY KEY REFERENCES records(id), version INTEGER NOT NULL);
CREATE TABLE record_bylines (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id),
                origin_record_id TEXT NOT NULL REFERENCES records(id), original_authors TEXT NOT NULL,
                raw_name TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL,
                original_target_type TEXT NOT NULL, original_target_id TEXT,
                selected_target_type TEXT NOT NULL, selected_target_id TEXT,
                target_type TEXT NOT NULL, target_id TEXT, evidence TEXT NOT NULL,
                version INTEGER NOT NULL, manual_revision INTEGER NOT NULL,
                removed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
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
INSERT INTO "records" VALUES('LOCAL-C210F2BAB9B0','report','旧原文','','',NULL,NULL,'','','','','','','','','pending','shared','researcher','[]','[]','','','{}',1,'2026-10-26T17:59:22+00:00','2026-10-26T17:59:22+00:00','','','','','',NULL,0,NULL,'','','','','','','',NULL,'{}');
INSERT INTO "records" VALUES('LOCAL-2CD562B1C477','research_note','旧摘录','','',NULL,NULL,'','','','','','','','','pending','shared','researcher','[]','[]','','','{}',1,'2026-10-26T17:59:22+00:00','2026-10-26T17:59:22+00:00','','','','','','researcher',1,NULL,'旧原句','','','第1段','','LOCAL-C210F2BAB9B0','',1,'{"id": "LOCAL-C210F2BAB9B0", "kind": "report", "title": "旧原文", "original_title": "", "authors": "", "published_on": "", "url": "", "doi": "", "version": 1}');
INSERT INTO "records" VALUES('LOCAL-D542ED159725','research_report','旧报告','','',NULL,NULL,'','','','','','','','','pending','shared','researcher','[]','[]','','','{}',1,'2026-10-26T17:59:22+00:00','2026-10-26T17:59:22+00:00','','','','','','researcher',1,NULL,'','','','','','','',NULL,'{}');
CREATE TABLE research_subject_history (
                id INTEGER PRIMARY KEY, relation_id TEXT NOT NULL REFERENCES research_subjects(id),
                action TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL, snapshot_json TEXT NOT NULL, identity_event_id TEXT REFERENCES person_identity_events(id));
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
CREATE TABLE revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 action TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 snapshot_json TEXT NOT NULL);
INSERT INTO "revisions" VALUES(1,'record','LOCAL-C210F2BAB9B0','提交资料','researcher','2026-10-26T17:59:22+00:00','{"id": "LOCAL-C210F2BAB9B0", "kind": "report", "title": "旧原文", "original_title": "", "authors": "", "source_id": null, "serial_id": null, "publication_title": "", "published_on": "", "language": "", "abstract": "", "keywords": "", "countries": "", "doi": "", "url": "", "status": "pending", "visibility": "shared", "owner_id": "researcher", "editors": "[]", "attachment_ids": "[]", "unresolved_refs": "", "upstream_status": "", "raw_json": "{}", "version": 1, "created_at": "2026-10-26T17:59:22+00:00", "updated_at": "2026-10-26T17:59:22+00:00", "body_html": "", "body_text": "", "coverage": "", "original_catalogue": "", "aliases": "", "author_id": null, "author_confirmed": 0, "merged_into": null, "quote": "", "translation": "", "interpretation": "", "locator": "", "evidence_url": "", "evidence_record_id": "", "evidence_attachment_id": "", "evidence_version": null, "evidence_snapshot_json": "{}", "linked_ids": [], "related_source_ids": [], "evidence_citations": [], "research_subjects": []}');
INSERT INTO "revisions" VALUES(2,'record','LOCAL-2CD562B1C477','提交资料','researcher','2026-10-26T17:59:22+00:00','{"id": "LOCAL-2CD562B1C477", "kind": "research_note", "title": "旧摘录", "original_title": "", "authors": "", "source_id": null, "serial_id": null, "publication_title": "", "published_on": "", "language": "", "abstract": "", "keywords": "", "countries": "", "doi": "", "url": "", "status": "pending", "visibility": "shared", "owner_id": "researcher", "editors": "[]", "attachment_ids": "[]", "unresolved_refs": "", "upstream_status": "", "raw_json": "{}", "version": 1, "created_at": "2026-10-26T17:59:22+00:00", "updated_at": "2026-10-26T17:59:22+00:00", "body_html": "", "body_text": "", "coverage": "", "original_catalogue": "", "aliases": "", "author_id": "researcher", "author_confirmed": 1, "merged_into": null, "quote": "旧原句", "translation": "", "interpretation": "", "locator": "第1段", "evidence_url": "", "evidence_record_id": "LOCAL-C210F2BAB9B0", "evidence_attachment_id": "", "evidence_version": 1, "evidence_snapshot_json": "{\"id\": \"LOCAL-C210F2BAB9B0\", \"kind\": \"report\", \"title\": \"旧原文\", \"original_title\": \"\", \"authors\": \"\", \"published_on\": \"\", \"url\": \"\", \"doi\": \"\", \"version\": 1}", "linked_ids": [], "related_source_ids": [], "evidence_citations": [], "research_subjects": []}');
INSERT INTO "revisions" VALUES(3,'record','LOCAL-D542ED159725','提交资料','researcher','2026-10-26T17:59:22+00:00','{"id": "LOCAL-D542ED159725", "kind": "research_report", "title": "旧报告", "original_title": "", "authors": "", "source_id": null, "serial_id": null, "publication_title": "", "published_on": "", "language": "", "abstract": "", "keywords": "", "countries": "", "doi": "", "url": "", "status": "pending", "visibility": "shared", "owner_id": "researcher", "editors": "[]", "attachment_ids": "[]", "unresolved_refs": "", "upstream_status": "", "raw_json": "{}", "version": 1, "created_at": "2026-10-26T17:59:22+00:00", "updated_at": "2026-10-26T17:59:22+00:00", "body_html": "", "body_text": "", "coverage": "", "original_catalogue": "", "aliases": "", "author_id": "researcher", "author_confirmed": 1, "merged_into": null, "quote": "", "translation": "", "interpretation": "", "locator": "", "evidence_url": "", "evidence_record_id": "", "evidence_attachment_id": "", "evidence_version": null, "evidence_snapshot_json": "{}", "linked_ids": [], "related_source_ids": [], "evidence_citations": [{"report_id": "LOCAL-D542ED159725", "excerpt_id": "LOCAL-2CD562B1C477", "excerpt_version": 1, "snapshot_json": "{\"id\": \"LOCAL-2CD562B1C477\", \"kind\": \"research_note\", \"title\": \"旧摘录\", \"original_title\": \"\", \"authors\": \"\", \"published_on\": \"\", \"url\": \"\", \"doi\": \"\", \"version\": 1, \"body_html\": \"\", \"body_text\": \"\", \"abstract\": \"\", \"quote\": \"旧原句\", \"translation\": \"\", \"interpretation\": \"\", \"locator\": \"第1段\", \"evidence_record_id\": \"LOCAL-C210F2BAB9B0\", \"evidence_version\": 1, \"evidence_url\": \"\", \"evidence_attachment_id\": \"\", \"evidence_snapshot_json\": \"{\\\"id\\\": \\\"LOCAL-C210F2BAB9B0\\\", \\\"kind\\\": \\\"report\\\", \\\"title\\\": \\\"旧原文\\\", \\\"original_title\\\": \\\"\\\", \\\"authors\\\": \\\"\\\", \\\"published_on\\\": \\\"\\\", \\\"url\\\": \\\"\\\", \\\"doi\\\": \\\"\\\", \\\"version\\\": 1}\"}"}], "research_subjects": []}');
CREATE TABLE saved_searches (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
                name_key TEXT NOT NULL, conditions_json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(owner_id,name_key));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "settings" VALUES('schema_version','11');
INSERT INTO "settings" VALUES('people_migration_backup','/tmp/i42-schema11-myq99mfv/backups/research-backup-2026-10-26T17-59-22-f20e17.zip');
INSERT INTO "settings" VALUES('note_subjects_migration_backup','/tmp/i42-schema11-myq99mfv/backups/research-backup-2026-10-26T17-59-22-0c3beb.zip');
INSERT INTO "settings" VALUES('byline_migration_backup','/tmp/i42-schema11-myq99mfv/backups/research-backup-2026-10-26T17-59-22-cc2ee9.zip');
INSERT INTO "settings" VALUES('affiliations_migration_backup','/tmp/i42-schema11-myq99mfv/backups/research-backup-2026-10-26T17-59-22-90bf51.zip');
INSERT INTO "settings" VALUES('person_identity_migration_backup','/tmp/i42-schema11-myq99mfv/backups/research-backup-2026-10-26T17-59-22-5581e5.zip');
INSERT INTO "settings" VALUES('saved_searches_migration_backup','/tmp/i42-schema11-myq99mfv/backups/research-backup-2026-10-26T17-59-22-2290d6.zip');
CREATE TABLE sources (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, original_name TEXT DEFAULT '', kind TEXT NOT NULL,
 classification TEXT DEFAULT '', location TEXT DEFAULT '', country TEXT DEFAULT '',
 research_scope TEXT DEFAULT '', website TEXT DEFAULT '', catalogue_url TEXT DEFAULT '',
 host_id TEXT DEFAULT '', publisher_id TEXT DEFAULT '', issn TEXT DEFAULT '',
 scope_status TEXT DEFAULT 'candidate', status TEXT NOT NULL DEFAULT 'pending',
 notes TEXT DEFAULT '', upstream_status TEXT DEFAULT '', raw_json TEXT DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, institution_types TEXT NOT NULL DEFAULT '[]', relationships TEXT NOT NULL DEFAULT '[]', country_evidence TEXT NOT NULL DEFAULT '', host_evidence TEXT NOT NULL DEFAULT '', host_country_status TEXT NOT NULL DEFAULT 'auto', international_status TEXT NOT NULL DEFAULT 'unknown', international_evidence TEXT NOT NULL DEFAULT '', introduction_html TEXT NOT NULL DEFAULT '', introduction_text TEXT NOT NULL DEFAULT '', aliases TEXT NOT NULL DEFAULT '', merged_into TEXT REFERENCES sources(id));
CREATE TABLE users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, credential_version INTEGER NOT NULL DEFAULT 0);
INSERT INTO "users" VALUES('admin','admin','资料管理员','scrypt:32768:8:1$w8eEyRloKfmNk7hT$0c8cba1d33d024ff3c8ef37ab4cd48b7d921e71c2fc8493adfbaa4420aa07415297d82b4779b5612f39a8e5d59ab1ca69deabd1b50e5dfbbc2cf1600ce40a3b7','admin',1,0);
INSERT INTO "users" VALUES('researcher','researcher','研究员 · 林','scrypt:32768:8:1$XMeSogKDUDIeNYVY$19722c0920d72b970b680678d77da7b7a34e23b9f5741ca64eb05d1d8bc250e61f69cb1a11da6b18ad305c9e77b6de9692ff508423e40475dd2cff401bf1e4e8','researcher',1,0);
INSERT INTO "users" VALUES('colleague','colleague','研究员 · 周','scrypt:32768:8:1$GohOdiR1sRuldRU3$247256bff2f122f93d099137fe4c03c958d72aa444d145a2813a0ddec9cc5cd9099ece2354c48cd7f047f0a6d5a64291be3172f0bbcb239843f6cb1cfc120f07','researcher',1,0);
CREATE INDEX idx_records_date ON records(published_on DESC);
CREATE INDEX idx_records_source ON records(source_id);
CREATE INDEX idx_revisions_target ON revisions(target_type, target_id);
CREATE INDEX idx_record_sources_source ON record_sources(source_id);
CREATE INDEX idx_evidence_record ON records(evidence_record_id);
CREATE INDEX idx_subject_note ON research_subjects(note_id,status);
CREATE INDEX idx_subject_target ON research_subjects(subject_type,subject_id,status);
CREATE INDEX idx_byline_record ON record_bylines(record_id,position,id);
CREATE INDEX idx_byline_target ON record_bylines(target_type,target_id,status);
CREATE INDEX idx_employment_person ON person_employments(person_id);
CREATE INDEX idx_employment_institution ON person_employments(institution_id);
CREATE INDEX idx_affiliation_record ON record_affiliations(record_id);
CREATE INDEX idx_affiliation_institution ON record_affiliations(institution_id);
CREATE INDEX idx_affiliation_history ON affiliation_changes(relation_type,relation_id,id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('revisions',3);
COMMIT;
