"""Permission-neutral presentation of already-authorized records and snapshots."""
import json
import re
from urllib.parse import quote

from . import workflow


def external_url(value):
    value = value.strip() if isinstance(value, str) else ""
    return value if workflow.safe_link(value) else ""


def json_value(value, expected):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return expected()
    return value if isinstance(value, expected) else expected()


def access(record, attachments, data_dir):
    row = dict(record)
    raw = json_value(row.get("raw_json"), dict)
    imported = raw.get("imported_attachments")
    official_files, seen = [], set()
    for item in imported if isinstance(imported, list) else []:
        if not isinstance(item, dict):
            continue
        url = external_url(item.get("url"))
        if url and url not in seen:
            seen.add(url)
            official_files.append({"url": url, "label": "官方文件链接"})
    platform_files = []
    for aid in dict.fromkeys(x for x in json_value(row.get("attachment_ids"), list) if isinstance(x, str)):
        attached = attachments.get(aid)
        if not attached or attached["record_id"] != row["id"]:
            continue
        stored = attached["stored_name"]
        if not re.fullmatch(r"[a-f0-9]{32}\.(pdf|docx|txt|md)", stored) or not (data_dir / "uploads" / stored).is_file():
            continue
        platform_files.append({"id": aid, "name": attached["name"], "url": "/api/attachments/" + quote(aid, safe="")})
    return {"original_url": external_url(row.get("url")), "official_files": official_files,
            "platform_files": platform_files, "has_body": bool((row.get("body_text") or "").strip())}


def fields(data, labels):
    return "\n".join(label + "：" + str(data[key]).strip() for key, label in labels
                     if data.get(key) is not None and str(data[key]).strip())


def section(label, text):
    return label + "\n" + text if text else ""


def join(parts):
    return "\n\n".join(part for part in parts if part)


def body_text(data):
    value = data.get("body_html")
    return workflow.clean_rich(value)[1] if isinstance(value, str) and value else ""


def citation(data):
    labels = [("title", "题名"), ("original_title", "原题名"), ("authors", "作者"),
              ("published_on", "日期"), ("publication_title", "刊物／出处"), ("doi", "DOI"),
              ("coverage", "覆盖范围"), ("id", "稳定编号"), ("version", "版本")]
    url = external_url(data.get("url"))
    return "\n".join(part for part in [fields(data, labels), "原文地址：" + url if url else ""] if part)


def note_header(data):
    return fields(data, [("title", "笔记题名"), ("authors", "笔记署名"), ("id", "笔记编号")])


def excerpt(data):
    original = json_value(data.get("evidence_snapshot_json"), dict)
    location_url = external_url(data.get("evidence_url"))
    return join([note_header(data), section("原文摘录", data.get("quote", "")),
                 section("译文", data.get("translation", "")),
                 section("研究说明", data.get("interpretation", "")),
                 section("位置", data.get("locator", "")),
                 section("笔记正文", body_text(data)),
                 section("原文出处（引用时保存）", citation(original) or "未保存题录快照。"),
                 fields(data, [("evidence_version", "引用原文版本")]),
                 "原文位置链接：" + location_url if location_url else ""])


def copy_text(record, citations=(), linked_records=()):
    """Callers must supply only currently visible records and adopted citations."""
    row = dict(record)
    if row["kind"] in {"research_report", "compilation"}:
        parts = []
        for adopted in citations:
            saved = dict(adopted["snapshot"])
            saved.setdefault("id", adopted["excerpt_id"])
            content = excerpt(saved) if saved.get("evidence_record_id") else join([
                note_header(saved), section("笔记正文", body_text(saved)),
                section("笔记登记出处", citation({k: saved[k] for k in ["url", "doi", "published_on"] if k in saved}))])
            parts.append("采用笔记版本：" + str(adopted["excerpt_version"]) + "\n" + content)
        return {"mode": "references", "text": join(parts) or "暂无可复制的引用。",
                "notice": "仅包含当前可查看的引用；内容按报告采用时快照整理。"}
    if row["kind"] == "research_note" and row["evidence_record_id"]:
        return {"mode": "excerpt", "text": excerpt(row), "notice": "原文出处保留引用时版本。"}
    if row["kind"] == "research_note":
        parts = [note_header(row), section("笔记正文", body_text(row))]
        parts.extend(section("关联资料（当前登记，未固定引用快照）", citation(dict(linked))) for linked in linked_records)
        return {"mode": "note", "text": join(parts), "notice": "关联资料使用当前登记信息，未固定为引用时版本。"}
    return {"mode": "citation", "text": citation(row), "notice": "由已登记信息整理，非特定引文格式；外部链接未核验可达。"}
