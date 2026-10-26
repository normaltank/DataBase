"""Complete record changes: policy, relations, versions, history and upload rollback.

Each public mutation owns one SQLite transaction. Source merges use the same
transaction for the source graph and affected records; their graph rules stay
in identity. Callers never arrange the table writes or commit nested work.
"""
import hashlib
import io
import json
import re
import uuid
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort

from . import evidence, identity, source_catalog, workflow, note_subjects, bylines, affiliations, intake, reviews
from .store import now, save_revision

RECORD_FIELDS = ["kind", "title", "original_title", "authors", "source_id", "serial_id", "publication_title",
                 "volume", "issue", "pages", "issn", "published_on", "language", "abstract", "keywords", "countries", "doi", "url", "visibility", "unresolved_refs"] + list(workflow.RECORD_DEFAULTS) + workflow.EVIDENCE_FIELDS
KINDS = {"research_article", "journal_article", "report", "compilation", "book_section", "book", "book_review",
         "conference_abstract", "thesis", "presentation", "speech", "policy", "news", "other"}
KINDS |= workflow.CONTENT_KINDS


def validate_text(data, fields, base=None):
    values = {}
    for field in fields:
        value = data.get(field, base[field] if base else "")
        if value is None:
            value = ""
        limit = 500000 if field in ["body_html", "body_text", "introduction_html", "introduction_text"] else 40000 if field in ["abstract", "notes", "unresolved_refs", "quote", "translation", "interpretation"] else 4000
        if not isinstance(value, str) or len(value) > limit:
            abort(400, "字段格式或长度不正确。")
        values[field] = value.strip()
    for field in ["url", "website", "catalogue_url"]:
        if values.get(field):
            try:
                parsed = urlsplit(values[field])
                valid = parsed.scheme in ["https", "http"] and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid:
                abort(400, "网址需要使用有效的 http:// 或 https:// 地址。")
    return values


def check_version(data, row):
    if type(data.get("version")) is not int or data["version"] != row["version"]:
        abort(409, "这条内容已被更新，请重新打开后再保存。")


def snapshot(db, rid):
    """Keep the existing on-disk snapshot shape, including pre-upgrade databases."""
    result = dict(db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone())
    result["linked_ids"] = [r[0] for r in db.execute(
        "SELECT original_id FROM record_links WHERE report_id=? ORDER BY original_id", (rid,))]
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='record_sources'").fetchone():
        result["related_source_ids"] = workflow.source_ids(db, rid)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_links'").fetchone():
        result["evidence_citations"] = [dict(r) for r in db.execute(
            "SELECT * FROM evidence_links WHERE report_id=?", (rid,))]
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='research_subjects'").fetchone():
        result["research_subjects"] = note_subjects.snapshot(db, rid)
    return result


class RecordRevisions:
    def __init__(self, db, actor, upload_dir):
        self.db = db
        self.actor = actor
        self.upload_dir = Path(upload_dir)
        self._new_files = None
        self.prefetched_records = None

    @contextmanager
    def _transaction(self):
        if self.db.in_transaction:
            raise RuntimeError("Record revisions must own the transaction; nesting would commit unrelated work.")
        self._new_files = []
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            for path in self._new_files:
                path.unlink(missing_ok=True)
            raise
        finally:
            self._new_files = None

    def _history(self, rid, action, review_event=None):
        save_revision(self.db, "record", rid, action, self.actor["id"], review_event)

    def _initial_history(self, rid, action="导入初始版本", actor="admin"):
        if not self.db.execute("SELECT 1 FROM revisions WHERE target_type='record' AND target_id=?", (rid,)).fetchone():
            save_revision(self.db, "record", rid, action, actor)

    def _finish(self, row, values, action, review_event=None):
        values = {**values, "version": row["version"] + 1, "updated_at": now()}
        changed = self.db.execute(
            f"UPDATE records SET {','.join(k+'=?' for k in values)} WHERE id=? AND version=?",
            [*values.values(), row["id"], row["version"]]).rowcount
        if not changed:
            abort(409, "内容已变化，请刷新。")
        self._history(row["id"], action, review_event)

    def _relations(self, rid, linked, associated, cited, refresh=False):
        self.db.execute("DELETE FROM record_links WHERE report_id=?", (rid,))
        self.db.executemany("INSERT INTO record_links VALUES (?,?)", [(rid, x) for x in linked])
        workflow.set_sources(self.db, rid, associated)
        evidence.save_links(self.db, rid, cited, self.get, refresh, self.visible)

    def _unique_doi(self, doi, rid=""):
        key = intake.normalize_doi(doi) or doi.casefold()
        if key and any((intake.normalize_doi(row["doi"]) or row["doi"].casefold()) == key
                       for row in self.db.execute("SELECT doi FROM records WHERE id<>? AND merged_into IS NULL", (rid,))):
            abort(409, "该 DOI 已登记，请联系管理员核对重复条目。")

    def visible(self, r):
        u = self.actor
        if r["evidence_record_id"]:
            if self.prefetched_records is None:
                original = identity.resolve(self.db, "records", r["evidence_record_id"])
            else:
                original = self.prefetched_records.get(r["evidence_record_id"])
                seen = set()
                while original and original["merged_into"]:
                    if original["id"] in seen:
                        abort(409, "编号转向存在循环，请检查合并记录。")
                    seen.add(original["id"])
                    original = self.prefetched_records.get(original["merged_into"])
            if not original or original["id"] == r["id"] or not self.visible(original):
                return False
        return r["visibility"] == "shared" or u["role"] == "admin" or r["owner_id"] == u["id"] or r["author_id"] == u["id"] or (u["id"] in json.loads(r["editors"]) and (r["kind"] not in workflow.PERSONAL_KINDS or r["author_confirmed"]))

    def editable(self, r):
        u = self.actor
        if not self.visible(r):
            return False
        if r["kind"] in workflow.AUTHOR_CONTROLLED_KINDS:
            return bool(r["author_confirmed"]) and (r["author_id"] == u["id"] or u["id"] in json.loads(r["editors"]))
        return True

    def manages_access(self, r):
        if r["kind"] == "directory_translation":
            return False
        if r["kind"] in workflow.PERSONAL_KINDS:
            return bool(r["author_confirmed"]) and r["author_id"] == self.actor["id"]
        return r["owner_id"] == self.actor["id"] or self.actor["role"] == "admin"

    def get(self, rid, edit=False):
        r = identity.resolve(self.db, "records", rid)
        if not r or not self.visible(r):
            abort(404, "资料不存在，或当前账号没有查看权限。")
        if edit and not self.editable(r):
            abort(403, "此内容尚待作者确认，或当前账号没有正文编辑授权。")
        return r

    def source(self, sid):
        row = identity.resolve(self.db, "sources", sid)
        if not row:
            abort(404, "来源不存在。")
        return row

    def _values(self, data, base=None):
        values = validate_text(data, RECORD_FIELDS, base)
        values["doi"] = intake.normalize_doi(values["doi"]) or values["doi"]
        if base:
            values["aliases"] = identity.retained_aliases(self.db, "records", base["id"], values["aliases"])
        values["kind"] = values["kind"] or "report"
        values["visibility"] = values["visibility"] or "shared"
        if not values["title"]:
            abort(400, "请填写题名。")
        if values["kind"] not in KINDS or values["visibility"] not in ["shared", "restricted"]:
            abort(400, "资料类型或共享范围不正确。")
        try:
            values["body_html"], values["body_text"] = workflow.clean_rich(values["body_html"])
        except ValueError as error:
            abort(400, str(error))
        if base and base["kind"] != values["kind"] and (base["kind"] in workflow.CONTENT_KINDS or values["kind"] == "directory_translation"):
            abort(400, "已保存内容的维护类型不能改变；请分别新建，避免改变既有编辑责任。")
        if base and base["kind"] != values["kind"] and values["kind"] in workflow.PERSONAL_KINDS and not self.manages_access(base):
            abort(403, "共同编辑不包含重新指定负责作者或改变可见范围的权限。")
        if values["kind"] == "directory_translation":
            if values["visibility"] != "shared" or data.get("editors", []):
                abort(400, "目录译稿由中心全体有效成员共同维护。")
            if not values["authors"] or not values["coverage"]:
                abort(400, "请填写编译者及年份、卷期或覆盖范围。")
        if values["kind"] in workflow.PERSONAL_KINDS:
            if base and base["kind"] in workflow.PERSONAL_KINDS:
                if "author_id" in data and data["author_id"] != base["author_id"]:
                    abort(403, "负责作者请通过确认流程维护。")
            else:
                author_id = data.get("author_id") or self.actor["id"]
                if not isinstance(author_id, str):
                    abort(400, "负责作者账号格式不正确。")
                if not self.db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (author_id,)).fetchone():
                    abort(400, "请选择有效的负责作者账号。")
                values.update(author_id=author_id, author_confirmed=int(author_id == self.actor["id"]))
        if values["published_on"] and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", values["published_on"]):
            abort(400, "日期请填写为 YYYY、YYYY-MM 或 YYYY-MM-DD。")
        if values["published_on"]:
            try:
                parts = [int(x) for x in values["published_on"].split("-")]
                date(*(parts + [1] * (3-len(parts))))
            except ValueError:
                abort(400, "日期不存在，请检查年月日。")
        if base and values["kind"] in workflow.CONTENT_KINDS and base["kind"] not in workflow.CONTENT_KINDS:
            bylines.validate_record_kind(self.db, base["id"], values["kind"])
            if self.db.execute("SELECT 1 FROM record_links WHERE original_id=?", (base["id"],)).fetchone() or self.db.execute("SELECT 1 FROM records WHERE evidence_record_id=?", (base["id"],)).fetchone():
                abort(409, "此资料已被成果或摘录作为原文引用，不能改成研究内容类型。")
        for field in ["source_id", "serial_id"]:
            values[field] = values[field] or None
            if values[field]:
                src = self.source(values[field])
                values[field] = src["id"]
                if field == "serial_id" and src["kind"] not in ["journal", "serial"]:
                    abort(400, "请选择期刊或连续出版物。")
        editors = data.get("editors", json.loads(base["editors"]) if base else [])
        if not isinstance(editors, list) or not all(isinstance(x, str) for x in editors):
            abort(400, "授权同事格式不正确。")
        manages_acl = not base or self.manages_access(base)
        if base and not manages_acl:
            if set(editors) != set(json.loads(base["editors"])) or values["visibility"] != base["visibility"]:
                abort(403, "只有负责作者可调整个人成果授权；其他资料由提交者或管理员调整。")
        if values["kind"] in workflow.PERSONAL_KINDS and not base and not values["author_confirmed"]:
            editors = []
        valid_users = {r[0] for r in self.db.execute("SELECT id FROM users WHERE active=1")}
        retained_editors = set(json.loads(base["editors"])) if base else set()
        if not set(editors) <= valid_users | retained_editors:
            abort(400, "授权人员不存在。")
        values["editors"] = json.dumps(sorted(set(editors)))
        existing_linked = [r[0] for r in self.db.execute("SELECT original_id FROM record_links WHERE report_id=?", (base["id"],))] if base else []
        unseen_linked = {rid for rid in existing_linked if (original := identity.resolve(self.db, "records", rid)) and not self.visible(original)}
        linked = data.get("linked_ids", None)
        if linked is None:
            linked = [rid for rid in existing_linked if rid not in unseen_linked]
        if not isinstance(linked, list) or not all(isinstance(x, str) for x in linked) or len(linked) > 100:
            abort(400, "原文关联格式不正确。")
        if linked and values["kind"] not in workflow.CONTENT_KINDS:
            abort(400, "编译成果可以关联原始资料。")
        # The editor receives only readable relations. Omitting a hidden existing
        # relation cannot silently remove it while saving unrelated common text.
        canonical_links = list(unseen_linked)
        for rid in set(linked):
            original = self.get(rid)
            if original["kind"] in workflow.CONTENT_KINDS or (base and rid == base["id"]):
                abort(400, "请关联原始资料，不可关联成果本身。")
            canonical_links.append(original["id"])
        if len(set(canonical_links)) > 100:
            abort(400, "原文关联最多保留 100 条。")
        associated = data.get("related_source_ids", workflow.source_ids(self.db, base["id"]) if base else [])
        if not isinstance(associated, list) or len(associated) > 100 or not all(isinstance(s, str) for s in associated):
            abort(400, "关联来源格式不正确。")
        associated = [self.source(sid)["id"] for sid in associated]
        if values["kind"] == "directory_translation" and not associated:
            abort(400, "请至少选择一个关联来源。")
        cited = evidence.validate(self.db, data, values, base, self.get, self.upload_dir.parent)
        return values, sorted(set(canonical_links)), sorted(set(associated)), cited

    def _upload(self, rid, data, current_ids, file):
        if not file or not file.filename:
            return current_ids
        if data.get("sharing_confirmed") is not True:
            abort(400, "请确认附件可在所选范围内共享。")
        name = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if len(name) > 180 or any(ord(c) < 32 for c in name):
            abort(400, "文件名过长或包含无效字符。")
        suffix = Path(name).suffix.lower()
        if suffix not in [".pdf", ".docx", ".txt", ".md"]:
            abort(400, "支持 PDF、DOCX、TXT 和 Markdown，单文件最多 20 MB。")
        content = file.read(20 * 1024 * 1024 + 1)
        if not content or len(content) > 20 * 1024 * 1024:
            abort(400, "文件为空或超过 20 MB。")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            abort(400, "文件内容不是有效的 PDF。")
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if "word/document.xml" not in archive.namelist():
                        raise ValueError()
            except (ValueError, zipfile.BadZipFile):
                abort(400, "文件内容不是有效的 DOCX。")
        if suffix in [".txt", ".md"]:
            try:
                content.decode("utf-8-sig")
            except UnicodeDecodeError:
                abort(400, "文本文件请使用 UTF-8 编码。")
        aid = uuid.uuid4().hex
        path = self.upload_dir / (aid + suffix)
        # Track before writing: even a partial write or failed INSERT is cleaned.
        self._new_files.append(path)
        path.write_bytes(content)
        self.db.execute("INSERT INTO attachments VALUES (?,?,?,?,?,?,?)",
                        (aid, rid, name, path.name, len(content), hashlib.sha256(content).hexdigest(), now()))
        return current_ids + [aid]

    def create(self, data, file=None):
        with self._transaction():
            values, linked, associated, cited = self._values(data)
            self._unique_doi(values["doi"])
            acquired = None
            if data.get("intake_token"):
                acquired = intake.read_token(data["intake_token"], self.actor)
                if values["kind"] in workflow.CONTENT_KINDS:
                    abort(400, "辅助题录只用于外部原始资料。")
                if values["source_id"] and self.source(values["source_id"])["kind"] not in {"institution", "think_tank"}:
                    abort(400, "文章发布机构须选择机构；期刊请在所属刊物中关联。")
                key = intake.normalize_url(values["url"])
                acquisition_id = hashlib.sha256(data["intake_token"].encode()).hexdigest()
                for existing in self.db.execute("SELECT url,raw_json FROM records WHERE merged_into IS NULL"):
                    previous = json.loads(existing["raw_json"] or "{}")
                    if (key and intake.normalize_url(existing["url"]) == key) or any(e.get("acquisition_id") == acquisition_id for e in previous.get("intake_evidence", [])):
                        abort(409, "此次保存与已登记资料重复，请核对已有条目或联系管理员。")
                acquired = {**acquired, "acquisition_id": acquisition_id,
                            "saved_fields": {key: values[key] for key in acquired["fields"] if key in values}}
            rid = "LOCAL-" + uuid.uuid4().hex[:12].upper()
            values.update(id=rid, owner_id=self.actor["id"], created_at=now(), updated_at=now())
            self.db.execute(f"INSERT INTO records ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
            attachments = self._upload(rid, data, [], file)
            self.db.execute("UPDATE records SET attachment_ids=? WHERE id=?", (json.dumps(attachments), rid))
            self._relations(rid, linked, associated, cited)
            if acquired:
                raw = {"intake_evidence": [acquired]}
                self.db.execute("UPDATE records SET raw_json=? WHERE id=?", (json.dumps(raw, ensure_ascii=False), rid))
                items = data.get("intake_bylines")
                if items is None:
                    items = [{"raw_name": item["raw_name"], "status": "pending"} for item in acquired["authors"]]
                bylines.Bylines(self.db, self.actor, self).initialize(rid, items, "辅助录入：依据原始题录核对署名")
            if "research_subjects" in data:
                note_subjects.save(self.db, rid, values["kind"], data["research_subjects"], self.actor["id"])
            self._history(rid, "提交资料")
        return rid

    def edit(self, rid, data, file=None):
        with self._transaction():
            row = self.get(rid, edit=True)
            rid = row["id"]
            check_version(data, row)
            values, linked, associated, cited = self._values(data, row)
            self._unique_doi(values["doi"], rid)
            self._initial_history(rid)
            attachments = self._upload(rid, data, json.loads(row["attachment_ids"]), file)
            self._relations(rid, linked, associated, cited, data.get("refresh_citations") is True)
            if "research_subjects" in data:
                note_subjects.save(self.db, rid, values["kind"], data["research_subjects"], self.actor["id"])
            self._finish(row, {**values, "attachment_ids": json.dumps(attachments), "status": "pending"}, "修订资料")
        return rid

    def confirm_author(self, rid, data):
        with self._transaction():
            row = self.get(rid)
            rid = row["id"]
            check_version(data, row)
            if row["kind"] not in workflow.PERSONAL_KINDS or row["author_confirmed"]:
                abort(409, "此内容无需确认，或作者已经确认。")
            author_id = data.get("author_id", row["author_id"])
            if not isinstance(author_id, str):
                abort(400, "请选择负责作者账号。")
            if author_id != row["author_id"] and self.actor["id"] != row["owner_id"]:
                abort(403, "只有原提交者可以指定待确认的负责作者。")
            if not self.db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (author_id,)).fetchone():
                abort(400, "请选择有效的负责作者。")
            confirmed = data.get("confirm") is True
            if confirmed and author_id != self.actor["id"]:
                abort(403, "必须由负责作者本人确认。")
            if not confirmed and row["owner_id"] != self.actor["id"]:
                abort(403, "只有提交者可以指定作者。")
            self._initial_history(rid, "作者确认前版本", self.actor["id"])
            self._finish(row, {"author_id": author_id, "author_confirmed": int(confirmed), "editors": "[]"},
                         "负责作者本人确认" if confirmed else "指定负责作者，等待本人确认")
        return rid

    def change_subjects(self, rid, data):
        with self._transaction():
            row = self.get(rid, edit=True)
            check_version(data, row)
            if row["kind"] != "research_note":
                abort(400, "只有研究笔记可以选择研究对象。")
            self._initial_history(row["id"])
            note_subjects.save(self.db, row["id"], row["kind"], data["research_subjects"], self.actor["id"])
            self._finish(row, {"status": "pending"}, "调整笔记研究对象")
        return row["id"]

    def review(self, rid, data):
        with self._transaction():
            if self.actor["role"] != "admin":
                abort(403, "此操作需要资料管理员权限。")
            row = self.get(rid)
            check_version(data, row)
            event = reviews.facts(self.db, "record", row, self.actor, data)
            self._initial_history(row["id"])
            self._finish(row, {"status": "verified"}, reviews.ACTION, event)

    def restore(self, revision_id, data):
        with self._transaction():
            revision = self.db.execute("SELECT * FROM revisions WHERE id=? AND target_type='record'", (revision_id,)).fetchone()
            if not revision:
                abort(404)
            rid = revision["target_id"]
            current = self.get(rid, edit=True)
            if current["id"] != rid:
                abort(409, "此历史属于已合并的原记录，只供查阅；请在保留记录中手工修订。")
            check_version(data, current)
            old = json.loads(revision["snapshot_json"])
            if old["kind"] in workflow.CONTENT_KINDS and (self.db.execute("SELECT 1 FROM record_links WHERE original_id=?", (rid,)).fetchone() or self.db.execute("SELECT 1 FROM records WHERE evidence_record_id=?", (rid,)).fetchone()):
                abort(409, "此资料现已被成果或摘录引用，不能恢复为研究内容类型。")
            values = {k: old[k] for k in RECORD_FIELDS + ["attachment_ids", "evidence_version", "evidence_snapshot_json", "raw_json"] if k in old}
            self._unique_doi(intake.normalize_doi(values.get("doi")) or values.get("doi", ""), rid)
            bylines.validate_record_kind(self.db, rid, values["kind"])
            # Current permissions and responsible author are never restored from old content.
            values["visibility"] = current["visibility"]
            values["aliases"] = identity.retained_aliases(self.db, "records", rid, values.get("aliases", current["aliases"]))
            for key in ["source_id", "serial_id"]:
                if values.get(key):
                    values[key] = self.source(values[key])["id"]
            if values["kind"] != current["kind"] and (current["kind"] in workflow.CONTENT_KINDS or values["kind"] in workflow.AUTHOR_CONTROLLED_KINDS):
                abort(409, "历史类型不符合当前维护责任，请手工修订内容。")
            if values.get("evidence_record_id"):
                original = self.get(values["evidence_record_id"])
                if original["kind"] in workflow.CONTENT_KINDS:
                    abort(409, "历史证据对象的类型已改变，请手工修订。")
                values["evidence_record_id"] = original["id"]
            if "evidence_citations" in old:
                self.db.execute("DELETE FROM evidence_links WHERE report_id=?", (rid,))
                for link in old["evidence_citations"]:
                    cited = self.get(link["excerpt_id"])
                    self.db.execute("INSERT INTO evidence_links VALUES (?,?,?,?,?,?)", (rid, cited["id"], link["excerpt_version"], link["snapshot_json"], link.get("stance", "unclassified"), link.get("claim_note", "")))
            if "related_source_ids" in old:
                workflow.set_sources(self.db, rid, sorted({self.source(sid)["id"] for sid in old["related_source_ids"]}))
            unseen_linked = {link[0] for link in self.db.execute("SELECT original_id FROM record_links WHERE report_id=?", (rid,))
                             if (original := identity.resolve(self.db, "records", link[0])) and not self.visible(original)}
            self.db.execute("DELETE FROM record_links WHERE report_id=?", (rid,))
            self.db.executemany("INSERT INTO record_links VALUES (?,?)", [(rid, original_id) for original_id in unseen_linked])
            for linked_id in old.get("linked_ids", []):
                if linked_id in unseen_linked:
                    continue
                original = self.get(linked_id)
                if original["kind"] in workflow.CONTENT_KINDS:
                    abort(409, "历史关联对象的类型已改变，请手工修订。")
                self.db.execute("INSERT OR IGNORE INTO record_links VALUES (?,?)", (rid, original["id"]))
            if "research_subjects" in old:
                note_subjects.restore(self.db, rid, values["kind"], old["research_subjects"], self.actor["id"])
            self._finish(current, {**values, "status": "pending"}, f"恢复版本 {old['version']}")
        return rid

    def _merge_pair(self, data):
        kind = data.get("type")
        if kind not in {"source", "record"}:
            abort(400, "请选择来源或资料。")
        table = "sources" if kind == "source" else "records"
        loader = self.source if kind == "source" else self.get
        keep, duplicate = loader(data.get("keep_id", "")), loader(data.get("duplicate_id", ""))
        if keep["id"] == duplicate["id"]:
            abort(400, "两个编号已经指向同一条内容。")
        return kind, table, keep, duplicate

    def _merge_denial(self, kind, keep, duplicate):
        if kind == "source":
            if self.actor["role"] != "admin":
                return "来源合并需要资料管理员执行。"
            if keep["kind"] != duplicate["kind"] and not ({keep["kind"], duplicate["kind"]} <= {"think_tank", "institution"}):
                return "对象类型不同，不能合并。"
        else:
            if keep["kind"] != duplicate["kind"]:
                return "资料类型不同，不能合并。"
            if keep["kind"] in workflow.PERSONAL_KINDS:
                if not all(row["author_confirmed"] and (row["author_id"] == self.actor["id"] or self.actor["id"] in json.loads(row["editors"])) for row in [keep, duplicate]):
                    return "合并个人内容需要两条记录的作者编辑授权。"
            elif self.actor["role"] != "admin":
                return "公共资料合并需要资料管理员执行。"
            for key in ["visibility", "owner_id", "author_id", "author_confirmed"]:
                if keep[key] != duplicate[key]:
                    return "可见范围、提交责任或作者确认不同，不能安全合并。"
            if set(json.loads(keep["editors"])) != set(json.loads(duplicate["editors"])):
                return "编辑授权不同，不能安全合并。"
            if keep["evidence_record_id"] != duplicate["evidence_record_id"]:
                return "摘录对应的原始资料不同，不能合并。"
        return ""

    def _merge_impact(self, kind, keep, duplicate):
        did = duplicate["id"]
        if kind == "record":
            return {"附件": self.db.execute("SELECT count(*) FROM attachments WHERE record_id=?", (did,)).fetchone()[0],
                    "收藏": self.db.execute("SELECT count(*) FROM favorites WHERE record_id=?", (did,)).fetchone()[0],
                    "专题": self.db.execute("SELECT count(*) FROM collection_items WHERE record_id=?", (did,)).fetchone()[0],
                    "原文引用": self.db.execute("SELECT count(*) FROM record_links WHERE report_id=? OR original_id=?", (did, did)).fetchone()[0],
                    "证据引用": self.db.execute("SELECT count(*) FROM evidence_links WHERE report_id=? OR excerpt_id=?", (did, did)).fetchone()[0],
                    "历史": self.db.execute("SELECT count(*) FROM revisions WHERE target_type='record' AND target_id=?", (did,)).fetchone()[0]}
        return {"关联资料": self.db.execute("SELECT count(*) FROM records WHERE source_id=? OR serial_id=?", (did, did)).fetchone()[0],
                "一般内容关联": self.db.execute("SELECT count(*) FROM record_sources WHERE source_id=?", (did,)).fetchone()[0],
                "历史": self.db.execute("SELECT count(*) FROM revisions WHERE target_type='source' AND target_id=?", (did,)).fetchone()[0],
                "来源关系": sum(did in (str(s["host_id"]) + " " + str(s["publisher_id"]) + " " + s["relationships"]) for s in self.db.execute("SELECT * FROM sources WHERE merged_into IS NULL"))}

    def _move_pair(self, table, first, second, old, new):
        rows = self.db.execute(f"SELECT {first},{second} FROM {table} WHERE {first}=? OR {second}=?", (old, old)).fetchall()
        for row in rows:
            a, b = new if row[0] == old else row[0], new if row[1] == old else row[1]
            if table == "record_links" and a == b:
                abort(409, "合并会形成自引用，已阻止。")
            self.db.execute(f"INSERT OR IGNORE INTO {table}({first},{second}) VALUES (?,?)", (a, b))
        self.db.execute(f"DELETE FROM {table} WHERE {first}=? OR {second}=?", (old, old))

    def _merge_records(self, keep, duplicate):
        kid, did = keep["id"], duplicate["id"]
        note_subjects.rewire(self.db, did, kid, self.actor["id"], record=True)
        # All citation snapshots must survive; ambiguous collisions are not silently discarded.
        links = self.db.execute("SELECT * FROM evidence_links WHERE report_id=? OR excerpt_id=?", (did, did)).fetchall()
        for link in links:
            report, excerpt = kid if link["report_id"] == did else link["report_id"], kid if link["excerpt_id"] == did else link["excerpt_id"]
            other = self.db.execute("SELECT * FROM evidence_links WHERE report_id=? AND excerpt_id=?", (report, excerpt)).fetchone()
            if report == excerpt or (other and (other["snapshot_json"] != link["snapshot_json"] or other["excerpt_version"] != link["excerpt_version"] or other["stance"] != link["stance"] or other["claim_note"] != link["claim_note"])):
                abort(409, "合并会冲突于不同版本的证据引用，请先人工整理。")
            self.db.execute("INSERT OR IGNORE INTO evidence_links VALUES (?,?,?,?,?,?)", (report, excerpt, link["excerpt_version"], link["snapshot_json"], link["stance"], link["claim_note"]))
        self.db.execute("DELETE FROM evidence_links WHERE report_id=? OR excerpt_id=?", (did, did))
        self._move_pair("record_links", "report_id", "original_id", did, kid)
        for item in self.db.execute("SELECT * FROM collection_items WHERE record_id=?", (did,)).fetchall():
            cid = item["collection_id"]
            other = self.db.execute("SELECT * FROM collection_items WHERE collection_id=? AND record_id=?", (cid, kid)).fetchone()
            if other and (other["disposition"], other["rationale"]) != (item["disposition"], item["rationale"]):
                abort(409, "合并会冲突于专题纳入／排除决定或理由，请先人工整理。")
            save_revision(self.db, "collection", cid, "资料合并前专题版本", self.actor["id"])
            self.db.execute("INSERT OR IGNORE INTO collection_items(collection_id,record_id,disposition,rationale) VALUES (?,?,?,?)", (cid, kid, item["disposition"], item["rationale"]))
            self.db.execute("DELETE FROM collection_items WHERE collection_id=? AND record_id=?", (cid, did))
            self.db.execute("UPDATE collections SET version=version+1,updated_at=? WHERE id=?", (now(), cid))
            save_revision(self.db, "collection", cid, "资料合并转接专题条目", self.actor["id"])
        for table, owner in [("favorites", "user_id"), ("record_sources", "source_id")]:
            self.db.execute(f"INSERT OR IGNORE INTO {table}({owner},record_id) SELECT {owner},? FROM {table} WHERE record_id=?", (kid, did))
            self.db.execute(f"DELETE FROM {table} WHERE record_id=?", (did,))
        self.db.execute("UPDATE attachments SET record_id=? WHERE record_id=?", (kid, did))
        self.db.execute("UPDATE records SET evidence_record_id=? WHERE evidence_record_id=?", (kid, did))
        attachments = sorted(set(json.loads(keep["attachment_ids"]) + json.loads(duplicate["attachment_ids"])))
        names = identity.aliases(keep["aliases"], duplicate["aliases"], duplicate["title"], duplicate["original_title"], did)
        if len(names) > 4000:
            abort(409, "合并后的别名过长，请先人工整理别名。")
        self.db.execute("UPDATE records SET attachment_ids=?,aliases=? WHERE id=?", (json.dumps(attachments), names, kid))
        bylines.Bylines(self.db, self.actor, self).merge_records(kid, did)
        affiliations.ArticleAffiliations(self.db, self.actor, self).merge_records(kid, did)

    def preview_merge(self, data):
        kind, table, keep, duplicate = self._merge_pair(data)
        blocked = self._merge_denial(kind, keep, duplicate)
        excluded = {"raw_json", "body_text", "introduction_text", "evidence_snapshot_json", "merged_into"}
        return dict(type=kind, keep={k: keep[k] for k in keep.keys() if k not in excluded},
                    duplicate={k: duplicate[k] for k in duplicate.keys() if k not in excluded},
                    allowed=not blocked, blocked_reason=blocked, impact=self._merge_impact(kind, keep, duplicate),
                    explanation="保留所选主记录的当前内容，补充旧名称与编号线索并转接关联。另一记录原文与历史归档保留；不会把两份正文自动拼接。")

    def _rewire_source_record_links(self, keep_id, duplicate_id):
        note_subjects.rewire(self.db, duplicate_id, keep_id, self.actor["id"])
        for field in ["source_id", "serial_id"]:
            self.db.execute(f"UPDATE records SET {field}=? WHERE {field}=?", (keep_id, duplicate_id))
        self.db.execute("INSERT OR IGNORE INTO record_sources(record_id,source_id) SELECT record_id,? FROM record_sources WHERE source_id=?", (keep_id, duplicate_id))
        self.db.execute("DELETE FROM record_sources WHERE source_id=?", (duplicate_id,))
        bylines.Bylines(self.db, self.actor, self).merge_sources(keep_id, duplicate_id)
        affiliations.Employments(self.db, self.actor).merge_sources(keep_id, duplicate_id)
        affiliations.ArticleAffiliations(self.db, self.actor, self).merge_sources(keep_id, duplicate_id)

    def merge(self, data, validate_source):
        with self._transaction():
            if data.get("confirmed") is not True:
                abort(400, "请先比较影响并确认合并。")
            kind, table, keep, duplicate = self._merge_pair(data)
            reason = self._merge_denial(kind, keep, duplicate)
            if reason:
                abort(403, reason)
            if data.get("keep_version") != keep["version"] or data.get("duplicate_version") != duplicate["version"]:
                abort(409, "记录已改变，请重新比较后再确认。")
            before = {"keep": dict(keep), "duplicate": dict(duplicate), "impact": self._merge_impact(kind, keep, duplicate)}
            kid, did = keep["id"], duplicate["id"]
            affected_records, affected_sources = set(), set()
            if kind == "record":
                affected_records.update(r[0] for r in self.db.execute("SELECT report_id FROM record_links WHERE original_id=?", (did,)))
                affected_records.update(r[0] for r in self.db.execute("SELECT report_id FROM evidence_links WHERE excerpt_id=?", (did,)))
                affected_records.update(r[0] for r in self.db.execute("SELECT id FROM records WHERE evidence_record_id=?", (did,)))
                affected_records -= {kid, did}
            else:
                affected_records.update(r[0] for r in self.db.execute("SELECT id FROM records WHERE source_id=? OR serial_id=?", (did, did)))
                affected_records.update(r[0] for r in self.db.execute("SELECT record_id FROM record_sources WHERE source_id=?", (did,)))
                affected_records.update(bylines.source_records(self.db, did))
                affected_records.update(affiliations.source_records(self.db, did))
                affected_records.update(r[0] for r in self.db.execute("SELECT note_id FROM research_subjects WHERE subject_id=? AND subject_type<>'person'", (did,)))
                affected_sources = identity.source_merge_dependents(self.db, did) - {kid, did}
            records_before = {rid: self.db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone() for rid in affected_records}
            for affected_kind, ids in [("record", affected_records), ("source", affected_sources)]:
                for aid in sorted(ids):
                    save_revision(self.db, affected_kind, aid, "合并转接前版本", self.actor["id"])
            for row in [keep, duplicate]:
                save_revision(self.db, kind, row["id"], "人工合并前快照", self.actor["id"])
            if kind == "record":
                self._merge_records(keep, duplicate)
            else:
                identity.rewrite_source_graph(self.db, keep, duplicate, validate_source)
                self._rewire_source_record_links(kid, did)
            self.db.execute(f"UPDATE {table} SET merged_into=?,version=version+1,updated_at=? WHERE id=?", (kid, now(), did))
            if kind == "source":
                self.db.execute("UPDATE sources SET version=version+1,status='pending',updated_at=? WHERE id=?", (now(), kid))
            for aid in sorted(affected_records):
                self._finish(records_before[aid], {"status": "pending"}, "合并转接编号：" + did + " → " + kid)
            for aid in sorted(affected_sources):
                self.db.execute("UPDATE sources SET version=version+1,status='pending',updated_at=? WHERE id=?", (now(), aid))
                save_revision(self.db, "source", aid, "合并转接编号：" + did + " → " + kid, self.actor["id"])
            self.db.execute("INSERT INTO merge_events(target_type,keep_id,duplicate_id,actor_id,created_at,snapshot_json) VALUES (?,?,?,?,?,?)",
                            (kind, kid, did, self.actor["id"], now(), json.dumps(before, ensure_ascii=False)))
            if kind == "record":
                self._finish(keep, {"status": "pending"}, "人工合并：保留旧编号 " + did)
            else:
                save_revision(self.db, kind, kid, "人工合并：保留旧编号 " + did, self.actor["id"])
        return dict(id=kid, previous_id=did)
