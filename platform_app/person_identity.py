"""Member-confirmed person identity operations, with reversible provenance."""
import hashlib
import json
import secrets
import sqlite3
import uuid
from pathlib import Path

from flask import abort, jsonify

from . import identity, bylines, affiliations, note_subjects
from .store import connect, now, save_revision


SCHEMA_VERSION = 10
CHOICES = ("name", "original_name", "chinese_name", "introduction", "avatar")
STALE = "档案、关系或身份记录已改变，请重新比较；你的选择和依据仍可保留。"
UNSUPPORTED = "合并后已有变化，当前基础拆回不能安全处理；请保留现状，使用后续变化拆回流程。"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def migrate(data_dir):
    db = connect(Path(data_dir) / "platform.sqlite3")
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if int(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]) >= SCHEMA_VERSION:
                return
            from .maintenance import create_backup
            backup = create_backup(data_dir)
            db.execute("ALTER TABLE people ADD COLUMN merged_into TEXT REFERENCES people(id)")
            db.execute("""CREATE TABLE person_identity_events (
                id TEXT PRIMARY KEY, event_type TEXT NOT NULL CHECK(event_type IN ('merge','split')),
                merge_event_id TEXT REFERENCES person_identity_events(id),
                keep_id TEXT NOT NULL REFERENCES people(id), duplicate_id TEXT NOT NULL REFERENCES people(id),
                actor_id TEXT NOT NULL REFERENCES users(id), evidence TEXT NOT NULL, choices_json TEXT NOT NULL,
                dependencies_json TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                created_at TEXT NOT NULL, CHECK(keep_id<>duplicate_id))""")
            db.execute("""CREATE TABLE person_merge_state (
                event_id TEXT PRIMARY KEY REFERENCES person_identity_events(id),
                status TEXT NOT NULL CHECK(status IN ('active','split')), version INTEGER NOT NULL,
                split_event_id TEXT REFERENCES person_identity_events(id))""")
            db.execute("""CREATE TABLE person_identity_previews (
                id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
                keep_id TEXT NOT NULL REFERENCES people(id), duplicate_id TEXT NOT NULL REFERENCES people(id),
                event_id TEXT REFERENCES person_identity_events(id), fingerprint TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE person_identity_requests (
                actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL, request_key TEXT NOT NULL,
                intent_hash TEXT NOT NULL, result_json TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES person_identity_events(id),
                PRIMARY KEY(actor_id,action,request_key))""")
            db.execute("ALTER TABLE research_subject_history ADD COLUMN identity_event_id TEXT REFERENCES person_identity_events(id)")
            db.execute("UPDATE settings SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('person_identity_migration_backup',?)", (str(backup),))
    finally:
        db.close()


def validate_backup(db):
    """Identity JSON is restore data too: verify its references and reversible graph."""
    required = {"person_identity_events", "person_merge_state", "person_identity_previews", "person_identity_requests"}
    if not required <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        raise ValueError("备份缺少人物身份操作与拆回依据。")

    def exists(table, rid):
        if not isinstance(rid, str) or not db.execute(f"SELECT 1 FROM {table} WHERE id=?", (rid,)).fetchone():
            raise ValueError("人物身份历史引用不完整。")

    def person_snapshot(person):
        exists("people", person["id"])
        if person.get("avatar_id"):
            exists("person_avatars", person["avatar_id"])
        if person.get("merged_into"):
            exists("people", person["merged_into"])
        if type(person["version"]) is not int or person["version"] < 1:
            raise ValueError("人物历史版本不完整。")

    try:
        people = {row["id"]: dict(row) for row in db.execute("SELECT * FROM people")}
        for person in people.values():
            person_snapshot(person)
            seen, current = set(), person["id"]
            while current:
                if current in seen or current not in people:
                    raise ValueError("人物身份转向存在循环或缺失。")
                seen.add(current)
                current = people[current]["merged_into"]
        for revision in db.execute("SELECT target_id,snapshot_json FROM revisions WHERE target_type='person'"):
            person = json.loads(revision["snapshot_json"])
            if person["id"] != revision["target_id"]:
                raise ValueError("人物历史对象不一致。")
            person_snapshot(person)
        events = {row["id"]: dict(row) for row in db.execute("SELECT rowid AS sequence,* FROM person_identity_events")}
        states = {row["event_id"]: dict(row) for row in db.execute("SELECT * FROM person_merge_state")}

        def state_snapshot(value):
            state = json.loads(value)
            if set(state) != {"people", "events", "bylines", "employments", "subjects", "affiliations", "records", "collections"}:
                raise ValueError("人物合并前后依据不完整。")
            for person in state["people"]:
                person_snapshot(person)
            for row in state["events"]:
                exists("person_identity_events", row["id"])
            for row in state["records"]:
                exists("records", row["id"])
            for key, table in [("bylines", "record_bylines"), ("employments", "person_employments"),
                               ("subjects", "research_subjects"), ("affiliations", "record_affiliations")]:
                for row in state[key]:
                    exists(table, row["id"])
                    if type(row["version"]) is not int or row["version"] < 1 or row["manual_revision"] < 1:
                        raise ValueError("人物身份关系历史版本不完整。")
                    for name in ["record_id", "origin_record_id", "note_id", "original_note_id"]:
                        if name in row:
                            exists("records", row[name])
                    for name in ["person_id", "original_person_id", "selected_person_id"]:
                        if name in row:
                            exists("people", row[name])
                    for name in ["institution_id", "original_institution_id", "selected_institution_id"]:
                        if name in row:
                            exists("sources", row[name])
                    for name in ["byline_id", "original_byline_id", "selected_byline_id"]:
                        if name in row:
                            exists("record_bylines", row[name])
                    for prefix in ["target", "original_target", "selected_target"] if key == "bylines" else []:
                        if row[prefix + "_id"]:
                            if row[prefix + "_type"] not in {"person", "institution"}:
                                raise ValueError("身份关系类型不正确。")
                            exists("people" if row[prefix + "_type"] == "person" else "sources", row[prefix + "_id"])
                    if key == "subjects":
                        for prefix in ["", "original_"]:
                            if row[prefix + "subject_type"] not in note_subjects.SUBJECT_TYPES:
                                raise ValueError("身份研究对象类型不正确。")
                            exists("people" if row[prefix + "subject_type"] == "person" else "sources", row[prefix + "subject_id"])
            for table, owner, target_table in [("record_byline_state", "record_id", "records"),
                                                ("record_affiliation_state", "record_id", "records"),
                                                ("person_employment_state", "person_id", "people")]:
                for row in state["collections"][table]:
                    exists(target_table, row[owner])
                    if type(row["version"]) is not int or row["version"] < 0:
                        raise ValueError("身份关系集合版本不完整。")
            return state

        for event in events.values():
            exists("people", event["keep_id"])
            exists("people", event["duplicate_id"])
            before, after = state_snapshot(event["before_json"]), state_snapshot(event["after_json"])
            if not {event["keep_id"], event["duplicate_id"]} <= {row["id"] for row in before["people"]}:
                raise ValueError("身份参与档案不完整。")
            if event["id"] not in {row["id"] for row in after["events"]}:
                raise ValueError("身份结果未包含本次操作。")
            dependencies = json.loads(event["dependencies_json"])
            if not isinstance(dependencies, list) or len(dependencies) != len(set(dependencies)):
                raise ValueError("人物合并依赖不完整。")
            for dependency in dependencies:
                prior = events.get(dependency)
                if not prior or prior["event_type"] != "merge" or prior["sequence"] >= event["sequence"]:
                    raise ValueError("人物合并依赖存在循环或缺失。")
            if event["event_type"] == "merge":
                choices = json.loads(event["choices_json"])
                if set(choices) != set(CHOICES) or any(choice not in {"keep", "duplicate"} for choice in choices.values()):
                    raise ValueError("人物合并当前内容选择不完整。")
                state = states.get(event["id"])
                if not state or state["version"] < 1:
                    raise ValueError("人物合并状态缺失。")
                if state["status"] == "active":
                    if state["split_event_id"] or people[event["duplicate_id"]]["merged_into"] != event["keep_id"]:
                        raise ValueError("人物合并状态与转向不一致。")
                else:
                    split = events.get(state["split_event_id"])
                    if not split or split["event_type"] != "split" or split["merge_event_id"] != event["id"]:
                        raise ValueError("人物拆回依据缺失。")
            else:
                merge = events.get(event["merge_event_id"])
                if (not merge or merge["event_type"] != "merge" or merge["sequence"] >= event["sequence"]
                        or any(merge[key] != event[key] for key in ["keep_id", "duplicate_id"])):
                    raise ValueError("人物拆回与原合并不一致。")
        for person in people.values():
            if person["merged_into"]:
                matching = [event for event in events.values() if event["event_type"] == "merge" and
                            event["duplicate_id"] == person["id"] and event["keep_id"] == person["merged_into"] and
                            states[event["id"]]["status"] == "active"]
                if len(matching) != 1:
                    raise ValueError("人物旧编号缺少唯一合并来历。")
        for table in ["byline_changes", "affiliation_changes", "research_subject_history"]:
            for row in db.execute(f"SELECT identity_event_id FROM {table} WHERE identity_event_id IS NOT NULL"):
                exists("person_identity_events", row[0])
        for request in db.execute("SELECT * FROM person_identity_requests"):
            event = events[request["event_id"]]
            result = json.loads(request["result_json"])
            if (result["event_id"] != event["id"] or result["action"] != event["event_type"] or
                    request["action"] != event["event_type"] or request["actor_id"] != event["actor_id"]):
                raise ValueError("身份操作重试结果不完整。")
    except (KeyError, TypeError, IndexError, AttributeError, sqlite3.DatabaseError) as error:
        raise ValueError("人物身份、历史或拆回依据格式不完整。") from error


class PersonIdentity:
    def __init__(self, db, actor, data_dir, access, summary):
        self.db, self.actor, self.data_dir = db, actor, data_dir
        self.access, self.summary = access, summary

    def profiles(self):
        from .people import PersonProfiles
        return PersonProfiles(self.db, self.actor, self.data_dir)

    def pair(self, data):
        if data.get("type", "person") != "person":
            abort(400, "人物身份只能与人物档案比较，不能与机构混合。")
        keep, duplicate = [identity.resolve(self.db, "people", data.get(key, "")) for key in ["keep_id", "duplicate_id"]]
        if not keep or not duplicate:
            abort(404, "人物档案不存在。")
        if keep["id"] == duplicate["id"]:
            abort(400, "两个编号已指向同一人物，不能自合并或形成循环。")
        return keep["id"], duplicate["id"]

    def state(self, keep, duplicate):
        members = sorted(set(identity.origins(self.db, "people", keep) + identity.origins(self.db, "people", duplicate)))
        profiles = [dict(self.db.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()) for pid in members]
        events = []
        for row in self.db.execute("""SELECT e.id,e.event_type,e.merge_event_id,e.keep_id,e.duplicate_id,
            e.dependencies_json,s.status,s.version,s.split_event_id FROM person_identity_events e
            LEFT JOIN person_merge_state s ON s.event_id=e.id ORDER BY e.rowid"""):
            if row["keep_id"] in members or row["duplicate_id"] in members:
                events.append(dict(row))
        byline_rows = [dict(row) for row in self.db.execute("SELECT * FROM record_bylines ORDER BY id")
                       if any(row[prefix + "_type"] == "person" and row[prefix + "_id"] in members
                              for prefix in ["target", "original_target", "selected_target"])]
        employment_rows = [dict(row) for row in self.db.execute("SELECT * FROM person_employments ORDER BY id")
                           if any(row[key] in members for key in ["person_id", "original_person_id", "selected_person_id"])]
        subjects = [dict(row) for row in self.db.execute("SELECT * FROM research_subjects ORDER BY id")
                    if any(row[prefix + "subject_type"] == "person" and row[prefix + "subject_id"] in members for prefix in ["", "original_"])]
        work_ids = {row["record_id"] for row in byline_rows}
        byline_ids = {row["id"] for row in byline_rows}
        units = [dict(row) for row in self.db.execute("SELECT * FROM record_affiliations ORDER BY id")
                 if row["record_id"] in work_ids or any(row[key] in byline_ids for key in ["byline_id", "selected_byline_id", "original_byline_id"])]
        record_ids = {row[key] for row in byline_rows + units for key in ["record_id", "origin_record_id"]}
        record_ids.update(row[key] for row in subjects for key in ["note_id", "original_note_id"])
        records = [dict(self.db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()) for rid in sorted(record_ids)]
        collections = {}
        for table, owner, owners in [("record_byline_state", "record_id", work_ids),
                                     ("record_affiliation_state", "record_id", work_ids),
                                     ("person_employment_state", "person_id", members)]:
            collections[table] = [{owner: rid, "version": (self.db.execute(f"SELECT version FROM {table} WHERE {owner}=?", (rid,)).fetchone() or [0])[0]}
                                  for rid in sorted(owners)]
        return {"people": profiles, "events": events, "bylines": byline_rows, "employments": employment_rows,
                "subjects": subjects, "affiliations": units, "records": records, "collections": collections}

    def public_relations(self, state):
        works, notes, units = {}, {}, []
        byline_service = bylines.Bylines(self.db, self.actor, self.access, self.summary)
        unit_service = affiliations.ArticleAffiliations(self.db, self.actor, self.access)

        def readable(rid):
            record = identity.resolve(self.db, "records", rid)
            return record if record and self.access.visible(record) else None

        def public_summary(record):
            result, private_names = self.summary(record), set()
            for original_id in identity.origins(self.db, "records", record["id"]):
                original = self.db.execute("SELECT * FROM records WHERE id=?", (original_id,)).fetchone()
                if not self.access.visible(original):
                    private_names.add(original_id)
                    private_names.update(line.strip() for key in ["title", "original_title", "aliases"] for line in original[key].splitlines())
            result["aliases"] = "\n".join(line for line in result["aliases"].splitlines() if line not in private_names)
            return result

        for row in state["bylines"]:
            record = readable(row["record_id"])
            if not record or not byline_service.readable(row):
                continue
            works.setdefault(record["id"], {**public_summary(record), "bylines": []})["bylines"].append(byline_service.historical(encoded(row)))
        for row in state["subjects"]:
            record = readable(row["note_id"])
            origin = self.db.execute("SELECT * FROM records WHERE id=?", (row["original_note_id"],)).fetchone()
            if not record:
                continue
            public_row = {**row, "note_id": record["id"],
                          "subject_name": note_subjects.target(self.db, row["subject_type"], row["subject_id"])["name"]}
            if not origin or not self.access.visible(origin):
                public_row.pop("original_note_id", None)
            notes.setdefault(record["id"], {**public_summary(record), "subjects": []})["subjects"].append(public_row)
        for row in state["affiliations"]:
            record = readable(row["record_id"])
            if record and unit_service.readable(row):
                units.append({**unit_service.historical(row), "record": public_summary(record)})
        employment_service = affiliations.Employments(self.db, self.actor)
        return {"works": list(works.values()), "employments": [employment_service.historical(row) for row in state["employments"]],
                "notes": list(notes.values()), "affiliations": units}

    def preview_token(self, action, keep, duplicate, state, event=None):
        token = secrets.token_hex(32)
        self.db.execute("INSERT INTO person_identity_previews VALUES (?,?,?,?,?,?,?,?)",
                        (token, self.actor["id"], action, keep, duplicate, event, digest(state), now()))
        return token

    def compare(self, data):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            keep, duplicate = self.pair(data)
            state = self.state(keep, duplicate)
            profiles = self.profiles()
            first, second = profiles.detail(keep), profiles.detail(duplicate)
            conflicts = [key for key in CHOICES if first["introduction_html" if key == "introduction" else "avatar_id" if key == "avatar" else key]
                         != second["introduction_html" if key == "introduction" else "avatar_id" if key == "avatar" else key]]
            return {"preview_id": self.preview_token("merge", keep, duplicate, state), "allowed": True,
                    "keep": first, "duplicate": second, "conflicts": conflicts,
                    "relationships": self.public_relations(state)}

    def event(self, event_id):
        row = self.db.execute("SELECT * FROM person_identity_events WHERE id=?", (event_id,)).fetchone()
        if not row:
            abort(404, "身份操作记录不存在。")
        return row

    def split_denial(self, event, state):
        status = self.db.execute("SELECT * FROM person_merge_state WHERE event_id=?", (event["id"],)).fetchone()
        if event["event_type"] != "merge" or not status or status["status"] != "active":
            return "这次合并已经拆回，或所选事件不是合并。"
        if digest(state) != digest(json.loads(event["after_json"])):
            return UNSUPPORTED
        return ""

    def preview_split(self, event_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            event = self.event(event_id)
            keep, duplicate = event["keep_id"], event["duplicate_id"]
            state = self.state(keep, duplicate)
            denial = self.split_denial(event, state)
            return {"preview_id": self.preview_token("split", keep, duplicate, state, event_id),
                    "allowed": not denial, "reason": denial, "merge": self.present_event(event),
                    "relationships": self.public_relations(state)}

    def present_event(self, event):
        result = {key: event[key] for key in ["id", "event_type", "merge_event_id", "keep_id", "duplicate_id", "actor_id", "evidence", "created_at"]}
        result["actor_name"] = self.db.execute("SELECT name FROM users WHERE id=?", (event["actor_id"],)).fetchone()[0]
        result["choices"] = json.loads(event["choices_json"])
        status = self.db.execute("SELECT * FROM person_merge_state WHERE event_id=?", (event["id"],)).fetchone()
        result["status"] = status["status"] if status else "completed"
        before = json.loads(event["before_json"])
        result["people_before"] = [{**person, "avatar": self.profiles().avatar(person["id"], person["avatar_id"])} for person in before["people"]]
        result["relationships"] = self.public_relations(before)
        return result

    def history(self, pid):
        current = identity.resolve(self.db, "people", pid)
        if not current:
            abort(404, "人物档案不存在。")
        related = {pid, *identity.origins(self.db, "people", current["id"])}
        return [self.present_event(row) for row in self.db.execute("SELECT * FROM person_identity_events ORDER BY rowid DESC")
                if row["keep_id"] in related or row["duplicate_id"] in related]

    def save_person(self, pid, values, action):
        self.db.execute(f"UPDATE people SET {','.join(key+'=?' for key in values)},version=version+1,updated_at=? WHERE id=?",
                        [*values.values(), now(), pid])
        save_revision(self.db, "person", pid, action, self.actor["id"])

    def transfer(self, before, keep, duplicate, event_id, evidence):
        duplicate_members = set(identity.origins(self.db, "people", duplicate))
        self.change_targets(before, event_id, evidence, "person_merge",
                            {row["id"]: keep for row in before["bylines"] if row["target_type"] == "person" and row["target_id"] in duplicate_members},
                            {row["id"]: keep for row in before["employments"] if row["person_id"] in duplicate_members},
                            {row["id"]: keep for row in before["subjects"] if row["subject_type"] == "person" and row["subject_id"] in duplicate_members})

    def reverse_transfer(self, original, current, event_id, evidence):
        existing = {key: {row["id"]: row for row in current[key]} for key in ["bylines", "employments", "subjects"]}
        self.change_targets(current, event_id, evidence, "person_split",
                            {row["id"]: row["target_id"] for row in original["bylines"] if row["target_id"] != existing["bylines"][row["id"]]["target_id"]},
                            {row["id"]: row["person_id"] for row in original["employments"] if row["person_id"] != existing["employments"][row["id"]]["person_id"]},
                            {row["id"]: row["subject_id"] for row in original["subjects"] if row["subject_id"] != existing["subjects"][row["id"]]["subject_id"]})

    def change_targets(self, state, event_id, evidence, kind, byline_targets, employment_targets, subject_targets):
        """System transfers retain original selections, tombstones and manual revisions."""
        byline_service = bylines.Bylines(self.db, self.actor, self.access)
        employment_service = affiliations.Employments(self.db, self.actor)
        changed_records, changed_people, changed_notes = set(), set(), set()
        for row in state["bylines"]:
            if row["id"] in byline_targets:
                byline_service.change(row, {"target_id": byline_targets[row["id"]]}, kind=kind, note=evidence, event_id=event_id)
                changed_records.add(row["record_id"])
        for row in state["employments"]:
            if row["id"] in employment_targets:
                pid = employment_targets[row["id"]]
                employment_service.change(row, {"person_id": pid}, kind=kind, note=evidence, event_id=event_id)
                changed_people.update([row["person_id"], pid])
        for row in state["subjects"]:
            if row["id"] in subject_targets:
                self.db.execute("UPDATE research_subjects SET subject_id=?,version=version+1,updated_by=?,updated_at=? WHERE id=?",
                                (subject_targets[row["id"]], self.actor["id"], now(), row["id"]))
                note_subjects.audit(self.db, row["id"], self.actor["id"], kind, event_id=event_id)
                changed_notes.add(row["note_id"])
        for rid in changed_records:
            byline_service.bump(rid)
        for pid in changed_people:
            employment_service.bump(pid)
        for rid in changed_notes:
            self.db.execute("UPDATE records SET version=version+1,updated_at=? WHERE id=?", (now(), rid))
            save_revision(self.db, "record", rid, "人物身份转接：" + event_id, self.actor["id"])

    def merge(self, preview, data, state, event_id):
        choices = data.get("choices")
        if not isinstance(choices, dict) or set(choices) != set(CHOICES) or any(value not in ("keep", "duplicate") for value in choices.values()):
            abort(400, "请逐项选择当前姓名、原名、中文名、介绍和头像。")
        keep, duplicate = preview["keep_id"], preview["duplicate_id"]
        first, second = [next(person for person in state["people"] if person["id"] == pid) for pid in [keep, duplicate]]
        selected = {key: first if value == "keep" else second for key, value in choices.items()}
        values = {key: selected[key][key] for key in ["name", "original_name", "chinese_name"]}
        values.update({key: selected["introduction"][key] for key in ["introduction_html", "introduction_text"]})
        values.update({key: selected["avatar"][key] for key in ["avatar_id", "avatar_source"]})
        values.update(aliases=identity.aliases(first["aliases"], second["aliases"], second["name"], second["original_name"],
                                              second["chinese_name"], first["name"], first["original_name"], first["chinese_name"]),
                      sources=identity.aliases(first["sources"], second["sources"]), change_note=data["evidence"])
        values["aliases"] = "\n".join(line for line in values["aliases"].splitlines() if line not in {person["id"] for person in state["people"]})
        if any(len(values[key]) > 40000 for key in ["aliases", "sources"]):
            abort(409, "合并后的姓名写法或出处过长，请先整理后重新比较。")
        self.save_person(keep, values, "人物合并：" + event_id)
        self.save_person(duplicate, {"merged_into": keep, "change_note": data["evidence"]}, "人物合并转向：" + event_id)
        self.transfer(state, keep, duplicate, event_id, data["evidence"])

    def split(self, preview, data, state, event_id):
        event = self.event(preview["event_id"])
        denial = self.split_denial(event, state)
        if denial:
            abort(409, denial)
        original = json.loads(event["before_json"])
        for pid in [preview["keep_id"], preview["duplicate_id"]]:
            old = next(person for person in original["people"] if person["id"] == pid)
            fields = {key: value for key, value in old.items() if key not in {"id", "version", "created_at", "updated_at"}}
            self.save_person(pid, {**fields, "change_note": data["evidence"]}, "人物拆回：" + event_id)
        self.reverse_transfer(original, state, event_id, data["evidence"])
        self.db.execute("UPDATE person_merge_state SET status='split',version=version+1,split_event_id=? WHERE event_id=?", (event_id, event["id"]))

    def execute(self, action, data):
        key = data.get("idempotency_key")
        if not isinstance(key, str) or not 8 <= len(key) <= 200:
            abort(400, "请携带本次确认的操作键。")
        intent_hash = digest({key: value for key, value in data.items() if key != "idempotency_key"})
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT * FROM person_identity_requests WHERE actor_id=? AND action=? AND request_key=?",
                                  (self.actor["id"], action, key)).fetchone()
            if old:
                if old["intent_hash"] != intent_hash:
                    abort(409, "此操作键已用于另一次确认，请重新比较并使用新的操作键。")
                return json.loads(old["result_json"])
            preview_id = data.get("preview_id")
            if not isinstance(preview_id, str):
                abort(400, "请先比较并确认影响。")
            preview = self.db.execute("SELECT * FROM person_identity_previews WHERE id=? AND actor_id=? AND action=?",
                                      (preview_id, self.actor["id"], action)).fetchone()
            if not preview:
                abort(409, "比较已失效，请重新比较。")
            state = self.state(preview["keep_id"], preview["duplicate_id"])
            if digest(state) != preview["fingerprint"]:
                abort(409, STALE)
            evidence = data.get("evidence")
            if data.get("confirmed") is not True or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 4000:
                abort(400, "请填写可核查的身份依据，并明确确认本次影响。")
            data = {**data, "evidence": evidence.strip()}
            event_id = "identity-" + uuid.uuid4().hex
            dependencies = [event["id"] for event in state["events"] if event["status"] == "active"]
            self.db.execute("INSERT INTO person_identity_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (event_id, action, preview["event_id"], preview["keep_id"], preview["duplicate_id"], self.actor["id"],
                             data["evidence"], encoded(data.get("choices", {})), encoded(dependencies), encoded(state), "{}", now()))
            if action == "merge":
                self.merge(preview, data, state, event_id)
                self.db.execute("INSERT INTO person_merge_state VALUES (?,'active',1,NULL)", (event_id,))
            else:
                self.split(preview, data, state, event_id)
            after = self.state(preview["keep_id"], preview["duplicate_id"])
            self.db.execute("UPDATE person_identity_events SET after_json=? WHERE id=?", (encoded(after), event_id))
            result = {"event_id": event_id, "action": action, "keep_id": preview["keep_id"], "duplicate_id": preview["duplicate_id"]}
            self.db.execute("INSERT INTO person_identity_requests VALUES (?,?,?,?,?,?)",
                            (self.actor["id"], action, key, intent_hash, encoded(result), event_id))
            return result


def register(app, ctx):
    def service():
        return PersonIdentity(ctx.db(), ctx.user(), ctx.data_dir, ctx.records(), ctx.record_summary)

    @app.post("/api/people/merge-preview")
    def person_compare():
        return jsonify(service().compare(ctx.body()))

    @app.post("/api/people/merge")
    def person_merge():
        return jsonify(service().execute("merge", ctx.body()))

    @app.get("/api/people/<pid>/identity-history")
    def person_identity_history(pid):
        return jsonify(items=service().history(pid))

    @app.post("/api/people/identity-events/<event_id>/split-preview")
    def person_split_preview(event_id):
        return jsonify(service().preview_split(event_id))

    @app.post("/api/people/split")
    def person_split():
        return jsonify(service().execute("split", ctx.body()))
