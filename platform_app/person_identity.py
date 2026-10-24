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
        relation_history = {}
        for key, table, query in [
                ("bylines", "record_bylines", "SELECT byline_id AS relation_id,identity_event_id,before_json,after_json FROM byline_changes ORDER BY id"),
                ("employments", "person_employments", "SELECT relation_id,identity_event_id,before_json,after_json FROM affiliation_changes WHERE relation_type='employment' ORDER BY id"),
                ("affiliations", "record_affiliations", "SELECT relation_id,identity_event_id,before_json,after_json FROM affiliation_changes WHERE relation_type='article_affiliation' ORDER BY id"),
                ("subjects", "research_subjects", "SELECT relation_id,identity_event_id,NULL AS before_json,snapshot_json AS after_json FROM research_subject_history ORDER BY id")]:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            histories = {}
            for change in db.execute(query):
                after = json.loads(change["after_json"])
                history = histories.setdefault(change["relation_id"], {})
                previous = history.get(after["version"] - 1)
                history[after["version"]] = {
                    "after": {name: after[name] for name in columns},
                    "before": ({name: json.loads(change["before_json"])[name] for name in columns} if change["before_json"]
                               else previous["after"] if previous else None), "event_id": change["identity_event_id"]}
            relation_history[key] = histories

        def complete_relations(event_id, before, after):
            for key, histories in relation_history.items():
                prior = {row["id"]: row for row in before[key]}
                following = {row["id"]: row for row in after[key]}
                if len(prior) != len(before[key]) or len(following) != len(after[key]) or set(prior) != set(following):
                    raise ValueError("身份操作前后关系集合不完整。")
                changed = {}
                for rid, history in histories.items():
                    own = [entry for entry in history.values() if entry["event_id"] == event_id]
                    if own:
                        changed[rid] = own
                        if rid not in prior or prior[rid] != own[0]["before"] or following[rid] != own[-1]["after"]:
                            raise ValueError("身份操作缺少关系转接前后依据。")
                for rid in prior:
                    for snapshot in [prior[rid], following[rid]]:
                        entry = histories.get(rid, {}).get(snapshot["version"])
                        if not entry or entry["after"] != snapshot:
                            raise ValueError("身份操作关系快照与修改历史不一致。")
                    if prior[rid] != following[rid] and rid not in changed:
                        raise ValueError("身份操作的关系变化缺少历史。")

        def complete_events(event, state, inclusive=False):
            profiles = {person["id"]: person for person in state["people"]}
            participants = {event["keep_id"], event["duplicate_id"]}
            members = set()
            for pid in profiles:
                seen, current = set(), pid
                while current in profiles and current not in participants and current not in seen:
                    seen.add(current)
                    current = profiles[current].get("merged_into")
                if current in participants:
                    members.add(pid)
            prior = {rid: row for rid, row in events.items() if
                     (row["sequence"] < event["sequence"] or inclusive and row["sequence"] == event["sequence"])}
            expected = {rid for rid, row in prior.items() if row["keep_id"] in members or row["duplicate_id"] in members}
            if {row["id"] for row in state["events"]} != expected or len(state["events"]) != len(expected):
                raise ValueError("人物身份事件上下文不完整。")
            for snapshot in state["events"]:
                original = prior[snapshot["id"]]
                if any(snapshot[key] != original[key] for key in ["id", "event_type", "merge_event_id", "keep_id", "duplicate_id", "dependencies_json"]):
                    raise ValueError("人物身份事件历史与原操作不一致。")
                splits = [row for row in prior.values() if row["event_type"] == "split" and row["merge_event_id"] == original["id"]]
                if len(splits) > 1:
                    raise ValueError("同一次人物合并存在重复拆回。")
                status = ("split" if splits else "active") if original["event_type"] == "merge" else None
                version = (2 if splits else 1) if original["event_type"] == "merge" else None
                if (snapshot["status"] != status or snapshot["version"] != version
                        or snapshot["split_event_id"] != (splits[0]["id"] if splits else None)):
                    raise ValueError("人物身份事件历史状态不一致。")

        def state_snapshot(value):
            state = json.loads(value)
            required_state = {"people", "events", "bylines", "employments", "subjects", "affiliations", "records", "collections"}
            if not required_state <= set(state) or set(state) - required_state - {"endpoint_sources"}:
                raise ValueError("人物合并前后依据不完整。")
            for source in state.get("endpoint_sources", []):
                exists("sources", source["id"])
                if type(source["version"]) is not int or source["version"] < 1:
                    raise ValueError("身份关系端点历史版本不完整。")
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
            complete_relations(event["id"], before, after)
            complete_events(event, before)
            complete_events(event, after, inclusive=True)
            if not {event["keep_id"], event["duplicate_id"]} <= {row["id"] for row in before["people"]}:
                raise ValueError("身份参与档案不完整。")
            if event["id"] not in {row["id"] for row in after["events"]}:
                raise ValueError("身份结果未包含本次操作。")
            dependencies = json.loads(event["dependencies_json"])
            if not isinstance(dependencies, list) or len(dependencies) != len(set(dependencies)):
                raise ValueError("人物合并依赖不完整。")
            if set(dependencies) != {row["id"] for row in before["events"] if row["status"] == "active"}:
                raise ValueError("人物合并依赖与当时身份状态不一致。")
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
                allocations = json.loads(event["choices_json"])
                tables = {"bylines": "record_bylines", "employments": "person_employments", "subjects": "research_subjects"}
                if not isinstance(allocations, dict) or set(allocations) - set(tables):
                    raise ValueError("人物拆回的新增关系选择不完整。")
                merged = json.loads(merge["after_json"])
                for key, selected in allocations.items():
                    allowed = {"keep", "duplicate"} if key == "employments" else {"keep", "duplicate", "pending"}
                    if not isinstance(selected, dict) or any(value not in allowed for value in selected.values()):
                        raise ValueError("人物拆回的归属选择不正确。")
                    candidates = {row["id"] for row in before[key]} - {row["id"] for row in merged[key]}
                    for rid in selected:
                        exists(tables[key], rid)
                        if rid not in candidates:
                            raise ValueError("人物拆回的关系选择缺少新增来历。")
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
        for row in db.execute("SELECT action,identity_event_id FROM research_subject_history WHERE action IN ('person_merge','person_split','person_split_review')"):
            event = events.get(row["identity_event_id"])
            if not event or event["event_type"] != ("merge" if row["action"] == "person_merge" else "split"):
                raise ValueError("笔记身份转接或待复核缺少相应身份依据。")
        for row in db.execute("SELECT id,version FROM research_subjects WHERE status='needs_review'"):
            basis = db.execute("SELECT snapshot_json FROM research_subject_history WHERE relation_id=? AND action='person_split_review' AND identity_event_id IS NOT NULL ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if not basis or json.loads(basis[0])["status"] != "needs_review":
                raise ValueError("笔记研究对象待复核缺少拆回依据。")
        for request in db.execute("SELECT * FROM person_identity_requests"):
            event = events[request["event_id"]]
            result = json.loads(request["result_json"])
            if (result != {"event_id": event["id"], "action": event["event_type"], "keep_id": event["keep_id"], "duplicate_id": event["duplicate_id"]} or
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
        people_ids, source_ids = set(members), set()
        for row in byline_rows:
            for prefix in ["target", "original_target", "selected_target"]:
                if row[prefix + "_id"]:
                    (people_ids if row[prefix + "_type"] == "person" else source_ids).add(row[prefix + "_id"])
        for row in employment_rows + units:
            source_ids.update(row[key] for key in ["institution_id", "original_institution_id", "selected_institution_id"])
            if "person_id" in row:
                people_ids.update(row[key] for key in ["person_id", "original_person_id", "selected_person_id"])
        for row in subjects:
            for prefix in ["", "original_"]:
                (people_ids if row[prefix + "subject_type"] == "person" else source_ids).add(row[prefix + "subject_id"])
        profiles = [dict(self.db.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()) for pid in sorted(people_ids)]
        endpoint_sources = [dict(self.db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()) for sid in sorted(source_ids)]
        collections = {}
        for table, owner, owners in [("record_byline_state", "record_id", work_ids),
                                     ("record_affiliation_state", "record_id", work_ids),
                                     ("person_employment_state", "person_id", members)]:
            collections[table] = [{owner: rid, "version": (self.db.execute(f"SELECT version FROM {table} WHERE {owner}=?", (rid,)).fetchone() or [0])[0]}
                                  for rid in sorted(owners)]
        return {"people": profiles, "events": events, "bylines": byline_rows, "employments": employment_rows,
                "subjects": subjects, "affiliations": units, "records": records, "collections": collections,
                "endpoint_sources": endpoint_sources}

    def public_relations(self, state):
        works, notes, units = {}, {}, []
        byline_service = bylines.Bylines(self.db, self.actor, self.access, self.summary)
        unit_service = affiliations.ArticleAffiliations(self.db, self.actor, self.access)

        def readable(rid):
            record = identity.resolve(self.db, "records", rid)
            return record if record and self.access.visible(record) else None

        def public_summary(record):
            return identity.readable_record(self.db, self.summary(record), self.access.visible)

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
        if self.split_order(event["id"]):
            return "后续合并仍依赖这次身份整理，请按所列顺序先拆回后续合并，再重新比较本次。"
        return ""

    def split_order(self, event_id):
        dependent = {event_id}
        active = []
        for row in self.db.execute("""SELECT e.*,s.status FROM person_identity_events e
                LEFT JOIN person_merge_state s ON s.event_id=e.id ORDER BY e.rowid"""):
            if row["event_type"] == "merge" and dependent.intersection(json.loads(row["dependencies_json"])):
                dependent.add(row["id"])
                if row["status"] == "active":
                    active.append({"event_id": row["id"], "keep_id": row["keep_id"], "duplicate_id": row["duplicate_id"],
                                   "keep_name": self.db.execute("SELECT name FROM people WHERE id=?", (row["keep_id"],)).fetchone()[0],
                                   "duplicate_name": self.db.execute("SELECT name FROM people WHERE id=?", (row["duplicate_id"],)).fetchone()[0],
                                   "evidence": row["evidence"], "created_at": row["created_at"]})
        return list(reversed(active))

    def split_plan(self, event, state):
        """Classify by provenance and human decisions, never by system version bumps."""
        before, after = [json.loads(event[key]) for key in ["before_json", "after_json"]]
        plan = {}
        for key, endpoint in [("bylines", "target_id"), ("employments", "person_id"), ("subjects", "subject_id")]:
            originals = {row["id"]: row for row in before[key]}
            merged = {row["id"]: row for row in after[key]}
            plan[key] = []
            for row in state[key]:
                old, joined = originals.get(row["id"]), merged.get(row["id"])
                removed = row.get("removed_at") or row.get("status") == "removed"
                manual = self.identity_decided(key, row["id"], joined["version"] if joined else 1)
                classification, restore_id = "unchanged", None
                if removed:
                    classification = "removed"
                elif joined and (manual or row[endpoint] != joined[endpoint]):
                    classification = "corrected"
                elif not joined:
                    classification = "corrected" if manual else "added"
                elif old and old[endpoint] != joined[endpoint]:
                    classification, restore_id = "transferred", old[endpoint]
                plan[key].append({"id": row["id"], "classification": classification, "restore_id": restore_id})
        return plan

    def identity_decided(self, key, relation_id, since_version):
        if key == "subjects":
            for row in self.db.execute("SELECT * FROM research_subject_history WHERE relation_id=?", (relation_id,)):
                if json.loads(row["snapshot_json"])["version"] <= since_version:
                    continue
                if row["action"] == "manual":
                    return True
                if row["identity_event_id"]:
                    event = self.event(row["identity_event_id"])
                    if event["event_type"] == "split" and json.loads(event["choices_json"]).get(key, {}).get(relation_id) in {"keep", "duplicate"}:
                        return True
            return False
        if key == "bylines":
            changes = self.db.execute("SELECT * FROM byline_changes WHERE byline_id=?", (relation_id,))
            fields = ["target_type", "target_id", "selected_target_type", "selected_target_id", "status"]
        else:
            changes = self.db.execute("SELECT * FROM affiliation_changes WHERE relation_type='employment' AND relation_id=?", (relation_id,))
            fields = ["person_id", "selected_person_id"]
        for change in changes:
            after = json.loads(change["after_json"])
            before = json.loads(change["before_json"]) if change["before_json"] else None
            if not before or after["version"] <= since_version:
                continue
            if change["identity_event_id"]:
                event = self.event(change["identity_event_id"])
                if event["event_type"] == "split" and json.loads(event["choices_json"]).get(key, {}).get(relation_id) in {"keep", "duplicate"}:
                    return True
            if change["change_kind"] not in {"manual", "manual_confirmation"}:
                continue
            if any(before[field] != after[field] for field in fields) or change["change_kind"] == "manual_confirmation":
                return True
            if key == "bylines" and all(before[field] == after[field] for field in bylines.FIELDS):
                # Schema 8–10 recorded no-op explicit confirmations as manual changes.
                return True
        return False

    def public_plan(self, plan, state):
        visible = self.public_relations(state)
        rows = {"bylines": [row for work in visible["works"] for row in work["bylines"]],
                "employments": visible["employments"],
                "subjects": [row for note in visible["notes"] for row in note["subjects"]]}
        def can_assign(key, row):
            if key != "subjects":
                return True
            record = identity.resolve(self.db, "records", row["note_id"])
            return bool(record and self.access.editable(record))
        return {key: [{**row, **entry, "can_assign": can_assign(key, row)}
                      for entry in plan[key] for row in rows[key] if row["id"] == entry["id"]]
                for key in plan}

    def assign_added(self, preview, data, plan, state, event_id):
        allocations = data.get("allocations", {})
        if not isinstance(allocations, dict) or set(allocations) - set(plan):
            abort(400, "新增关系的归属选择格式不正确。")
        public = self.public_plan(plan, state)
        choices = {}
        for key in plan:
            selected = allocations.get(key, {})
            if not isinstance(selected, dict):
                abort(400, "请逐项选择新增关系的归属。")
            allowed = {row["id"] for row in public[key] if row["classification"] == "added" and row["can_assign"]}
            if set(selected) - allowed:
                abort(403, "没有权限为所选关系重新指定研究对象或归属。")
            if any(not isinstance(value, str) or value not in ({"keep", "duplicate"} if key == "employments" else {"keep", "duplicate", "pending"}) for value in selected.values()):
                abort(400, "请选择原人物之一，或将允许延后处理的关系保留待确认。")
            choices[key] = {row["id"]: selected.get(row["id"], "pending") for row in plan[key] if row["classification"] == "added"}
            if key == "employments" and "pending" in choices[key].values():
                abort(400, "请为合并后新增的每条任职经历明确选择人物归属。")
        byline_service = bylines.Bylines(self.db, self.actor, self.access)
        employment_service = affiliations.Employments(self.db, self.actor)
        changed_records, changed_people, subjects = set(), set(), {}
        for key, endpoint, service in [("bylines", "target_id", byline_service), ("employments", "person_id", employment_service)]:
            for row in state[key]:
                choice = choices[key].get(row["id"])
                if not choice:
                    continue
                if choice == "pending":
                    values, kind = {"status": "pending"}, "person_split_review"
                else:
                    pid = preview[choice + "_id"]
                    values, kind = {endpoint: pid}, "manual"
                    if key == "bylines":
                        values.update(target_type="person", selected_target_type="person", selected_target_id=pid, status="confirmed")
                    else:
                        values["selected_person_id"] = pid
                        changed_people.add(pid)
                service.change(row, values, kind=kind, note=data["evidence"], event_id=event_id)
                (changed_records if key == "bylines" else changed_people).add(row["record_id"] if key == "bylines" else row["person_id"])
        for rid in changed_records:
            byline_service.bump(rid)
        for pid in changed_people:
            employment_service.bump(pid)
        for row in state["subjects"]:
            choice = choices["subjects"].get(row["id"])
            if choice:
                subjects[row["id"]] = {"status": "needs_review"} if choice == "pending" else {
                    "subject_id": preview[choice + "_id"], "status": "confirmed", "manual_revision": row["manual_revision"] + 1}
        self.change_targets(state, event_id, data["evidence"], "person_split_review", {}, {}, subjects)

    def preview_split(self, event_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            event = self.event(event_id)
            keep, duplicate = event["keep_id"], event["duplicate_id"]
            state = self.state(keep, duplicate)
            denial = self.split_denial(event, state)
            merged_people = json.loads(event["after_json"])["people"]
            profile_changes = [{"person_id": pid, "fields": sorted(self.edited_profile_fields(pid, next(p["version"] for p in merged_people if p["id"] == pid))
                               - {"id", "version", "created_at", "updated_at", "change_note"})} for pid in [keep, duplicate]]
            return {"preview_id": self.preview_token("split", keep, duplicate, state, event_id),
                    "allowed": not denial, "reason": denial, "merge": self.present_event(event),
                    "relationships": self.public_relations(state), "changes": self.public_plan(self.split_plan(event, state), state),
                    "split_order": self.split_order(event_id), "profile_changes": profile_changes}

    def present_event(self, event):
        result = {key: event[key] for key in ["id", "event_type", "merge_event_id", "keep_id", "duplicate_id", "actor_id", "evidence", "created_at"]}
        result["actor_name"] = self.db.execute("SELECT name FROM users WHERE id=?", (event["actor_id"],)).fetchone()[0]
        result["choices"] = json.loads(event["choices_json"])
        status = self.db.execute("SELECT * FROM person_merge_state WHERE event_id=?", (event["id"],)).fetchone()
        result["status"] = status["status"] if status else "completed"
        before = json.loads(event["before_json"])
        snapshots = {person["id"]: person for person in before["people"]}
        def original_component(pid):
            seen = set()
            while pid in snapshots and snapshots[pid].get("merged_into") and pid not in seen:
                seen.add(pid)
                pid = snapshots[pid]["merged_into"]
            return pid
        components = {original_component(event["keep_id"]), original_component(event["duplicate_id"])}
        result["people_before"] = [{**person, "avatar": self.profiles().avatar(person["id"], person["avatar_id"])}
                                   for person in before["people"] if original_component(person["id"]) in components]
        result["relationships"] = self.public_relations(before)
        if event["event_type"] == "split":
            visible = result["relationships"]
            ids = {"bylines": {row["id"] for work in visible["works"] for row in work["bylines"]},
                   "employments": {row["id"] for row in visible["employments"]},
                   "subjects": {row["id"] for note in visible["notes"] for row in note["subjects"]}}
            result["choices"] = {key: {rid: value for rid, value in selected.items() if rid in ids.get(key, set())}
                                 for key, selected in result["choices"].items() if any(rid in ids.get(key, set()) for rid in selected)}
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

    def reverse_transfer(self, plan, current, event_id, evidence):
        self.change_targets(current, event_id, evidence, "person_split",
                            *[{row["id"]: row["restore_id"] for row in plan[key] if row["restore_id"]}
                              for key in ["bylines", "employments", "subjects"]])

    def edited_profile_fields(self, pid, version):
        system_revisions = {}
        for event in self.db.execute("SELECT after_json FROM person_identity_events WHERE keep_id=? OR duplicate_id=?", (pid, pid)):
            # Completed event snapshots identify the system-written person version.
            # The current transaction's event still has {} until both people save.
            for person in json.loads(event["after_json"]).get("people", []):
                if person["id"] == pid:
                    system_revisions[person["version"]] = person
        edited, previous = set(), None
        for revision in self.db.execute("SELECT snapshot_json FROM revisions WHERE target_type='person' AND target_id=? ORDER BY id", (pid,)):
            current = json.loads(revision["snapshot_json"])
            if current["version"] > version and previous and current != system_revisions.get(current["version"]):
                edited.update(key for key in current if current[key] != previous.get(key))
            previous = current
        return edited

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
                selection = subject_targets[row["id"]]
                values = selection if isinstance(selection, dict) else {"subject_id": selection}
                self.db.execute(f"UPDATE research_subjects SET {','.join(key+'=?' for key in values)},version=version+1,updated_by=?,updated_at=? WHERE id=?",
                                [*values.values(), self.actor["id"], now(), row["id"]])
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
        merged = json.loads(event["after_json"])
        plan = self.split_plan(event, state)
        for pid in [preview["keep_id"], preview["duplicate_id"]]:
            old = next(person for person in original["people"] if person["id"] == pid)
            joined = next(person for person in merged["people"] if person["id"] == pid)
            edited = self.edited_profile_fields(pid, joined["version"])
            fields = {key: value for key, value in old.items() if key not in {"id", "version", "created_at", "updated_at", *edited}}
            self.save_person(pid, {**fields, "change_note": data["evidence"]}, "人物拆回：" + event_id)
        self.reverse_transfer(plan, state, event_id, data["evidence"])
        self.assign_added(preview, data, plan, state, event_id)
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
                             data["evidence"], encoded(data.get("choices", {}) if action == "merge" else data.get("allocations", {})),
                             encoded(dependencies), encoded(state), "{}", now()))
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
