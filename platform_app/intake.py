"""Bounded public metadata acquisition and evidence-backed intake drafts.

The preview is data, never executable markup. Signed evidence belongs to the
requesting member; record revisions own the only database write transaction.
"""
import html
import http.client
import ipaddress
import json
import queue
import re
import socket
import threading
import time
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from flask import abort, current_app, jsonify
from itsdangerous import BadSignature, URLSafeSerializer

from .store import now
from .public_dns import DeadlineConnection, resolve_proxy_alias

MAX_BYTES = 1024 * 1024
MAX_SECONDS = 15
_slots = threading.BoundedSemaphore(4)
_dns_slots = threading.BoundedSemaphore(4)


def normalize_doi(value):
    value = str(value or "").strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    value = unquote(value).strip().lower()
    return value if re.fullmatch(r"10\.\d{4,9}/[^\s?#]+", value) else ""


def normalize_url(value):
    try:
        p = urlsplit(str(value or "").strip())
        if p.scheme.lower() not in {"http", "https"} or not p.hostname or p.username or p.password:
            return ""
        host = p.hostname.encode("idna").decode().lower()
        if ":" in host:
            host = "[" + host + "]"
        port = p.port
        netloc = host + (":" + str(port) if port and port != (443 if p.scheme.lower() == "https" else 80) else "")
        return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))
    except (ValueError, UnicodeError):
        return ""


class AcquisitionError(ValueError):
    pass


def _public_ip(value):
    ip = ipaddress.ip_address(value)
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified and not ip.is_reserved and not (getattr(ip, "ipv4_mapped", None) and not _public_ip(str(ip.ipv4_mapped)))


def _resolve(host, port, deadline):
    # getaddrinfo has no Python timeout. A bounded daemon worker keeps the
    # request deadline real, including a stalled resolver.
    results = queue.Queue(maxsize=1)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AcquisitionError("解析站点超时；原链接仍可手工登记。")
    if not _dns_slots.acquire(blocking=False):
        raise AcquisitionError("域名解析繁忙，请稍后重试或继续手填。")
    def lookup():
        try:
            results.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError as error:
            results.put(error)
        finally:
            _dns_slots.release()
    threading.Thread(target=lookup, daemon=True).start()
    try:
        addresses = results.get(timeout=max(.001, deadline - time.monotonic()))
    except queue.Empty:
        raise AcquisitionError("解析站点超时；原链接仍可手工登记。") from None
    if isinstance(addresses, OSError):
        raise AcquisitionError("无法解析站点；请检查链接或继续手填。")
    ips = list(dict.fromkeys(a[4][0] for a in addresses))
    try:
        ips = resolve_proxy_alias(host, ips, deadline) or ips
    except ValueError as error:
        raise AcquisitionError(str(error)) from error
    if not ips or any(not _public_ip(ip) for ip in ips):
        raise AcquisitionError("只允许公开网站，不能读取本机或内部网络地址。")
    return ips[0]


def fetch_document(url, deadline):
    """Public network boundary: validate every redirect, pin DNS and check peer."""
    for hop in range(4):
        canonical = normalize_url(url)
        if not canonical:
            raise AcquisitionError("请使用有效的公开 HTTP(S) 文章链接。")
        p = urlsplit(canonical)
        port = p.port or (443 if p.scheme == "https" else 80)
        if port not in {80, 443}:
            raise AcquisitionError("提取仅支持公开网站的 80 或 443 端口。")
        ip = _resolve(p.hostname, port, deadline)
        connection = DeadlineConnection(p.hostname, port, ip, p.scheme == "https", deadline)
        response = None
        try:
            path = quote(p.path, safe="/%:@!$&'()*+,;=-._~") + ("?" + quote(p.query, safe="=&/%:@!$'()*+,;?-._~") if p.query else "")
            connection.request("GET", path, headers={"Accept": "text/html, application/json, application/ld+json", "Accept-Encoding": "identity", "User-Agent": "ResearchCommonsMetadata/1.0"})
            response = connection.getresponse()
            connection.remaining()
            if response.status in {301, 302, 303, 307, 308}:
                if hop == 3 or not response.getheader("Location"):
                    raise AcquisitionError("站点跳转过多或缺少目标；请直接粘贴文章地址。")
                url = urljoin(canonical, response.getheader("Location"))
                continue
            if response.status != 200:
                raise AcquisitionError(f"站点返回 HTTP {response.status}；可能限制访问，请继续手填。")
            mime = response.getheader("Content-Type", "").split(";")[0].strip().lower()
            if mime not in {"text/html", "application/xhtml+xml", "application/json", "application/ld+json"}:
                raise AcquisitionError("此链接不是支持的题录网页；不会下载全文或附件，可继续手填。")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_BYTES):
                raise AcquisitionError("页面超过提取大小限制，请继续手填。")
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AcquisitionError("提取超时，请重试或继续手填。")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                connection.remaining()
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise AcquisitionError("页面超过提取大小限制，请继续手填。")
            content = b"".join(chunks)
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                text = content.decode(charset, errors="replace")
            except LookupError:
                text = content.decode("utf-8", errors="replace")
            return {"url": canonical, "content_type": mime, "text": text}
        except (OSError, http.client.HTTPException, UnicodeError, ValueError) as error:
            if isinstance(error, AcquisitionError):
                raise
            raise AcquisitionError("站点连接失败或超时；原链接仍可手工登记。") from error
        finally:
            if response:
                response.close()
            connection.finish()
    raise AcquisitionError("站点跳转过多，请继续手填。")


def plain(value, limit=4000):
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()[:limit]
    return text if any(c.isalnum() for c in text) else ""


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.scripts, self.title = {}, [], ""
        self.in_title, self.in_json, self.script = False, False, ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key:
                self.meta.setdefault(key, []).append(attrs.get("content", ""))
        if tag == "title":
            self.in_title = True
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.in_json, self.script = True, ""

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_json:
            try:
                self.scripts.append(json.loads(self.script))
            except (ValueError, RecursionError):
                pass
            self.in_json = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_json:
            self.script += data


def _articles(value, depth=0):
    if depth > 15:
        return []
    if isinstance(value, list):
        return [a for v in value for a in _articles(v, depth + 1)]
    if isinstance(value, dict):
        types = value.get("@type", [])
        types = [types] if isinstance(types, str) else types
        found = [value] if isinstance(types, list) and any(isinstance(t, str) and t in {"Article", "ScholarlyArticle", "NewsArticle", "Report"} for t in types) else []
        return found + _articles(value.get("@graph", []), depth + 1)
    return []


def page_metadata(document):
    parser = ArticleParser()
    parser.feed(document["text"])
    meta, warnings, provenance = parser.meta, [], {}
    fields = {"url": document["url"]}
    def set_field(field, keys):
        values = [(key, plain(v, 40000 if field == "abstract" else 4000)) for key in keys for v in meta.get(key, []) if plain(v)]
        if values:
            fields[field], provenance[field] = values[0][1], values[0][0]
            if len({v for _, v in values}) > 1:
                warnings.append(field + " 的页面标签有不同值，请核对原始依据。")
    for field, keys in {
        "title": ["citation_title", "dc.title", "dcterms.title", "og:title"],
        "publication_title": ["citation_journal_title", "prism.publicationname"],
        "published_on": ["citation_publication_date", "citation_date", "dc.date.issued", "dc.date", "article:published_time"],
        "doi": ["citation_doi", "dc.identifier.doi", "prism.doi"],
        "language": ["citation_language", "dc.language"],
        "abstract": ["citation_abstract", "dc.description", "dcterms.abstract", "description", "og:description"],
    }.items():
        set_field(field, keys)
    names = meta.get("citation_author") or meta.get("dc.creator") or []
    authors = [{"raw_name": plain(name), "identifiers": {}, "affiliations": []} for name in names if plain(name)][:100]
    affiliations = meta.get("citation_author_institution", [])
    # Repeated meta tags do not reliably map affiliations to individual authors.
    identifiers = {"issn": meta.get("citation_issn", []), "author_orcid": meta.get("citation_author_orcid", [])}
    articles = [a for script in parser.scripts for a in _articles(script)]
    if len(articles) > 1:
        def is_main(article):
            addresses = [article.get("url"), article.get("@id"), article.get("mainEntityOfPage")]
            return any(normalize_url(a.get("@id", "") if isinstance(a, dict) else a) == document["url"] for a in addresses if isinstance(a, (str, dict)))
        selected = [article for article in articles if is_main(article)]
        articles = selected if len(selected) == 1 else []
        if not articles:
            warnings.append("网页含多篇 Article，无法确定主文；未拼接各篇字段，请人工补充。")
    for article in articles[:1]:
        article_title = plain(article.get("headline") or article.get("name"))
        if fields.get("title") and article_title and fields["title"] != article_title:
            warnings.append("JSON-LD 题名与页面标签不同，未混合该节点的作者与日期，请核对。")
            continue
        mappings = {"title": article.get("headline") or article.get("name"), "published_on": article.get("datePublished"),
                    "abstract": article.get("abstract") or article.get("description"), "language": article.get("inLanguage")}
        part = article.get("isPartOf")
        if isinstance(part, dict):
            mappings["publication_title"] = part.get("name")
            if part.get("issn"):
                identifiers["issn"] = [part["issn"]] if isinstance(part["issn"], str) else part["issn"]
        for field, value in mappings.items():
            if isinstance(value, str) and plain(value):
                value = plain(value, 40000 if field == "abstract" else 4000)
                if field in fields and fields[field] != value:
                    warnings.append(field + " 的 JSON-LD 与页面标签不同，请核对。")
                elif field not in fields:
                    fields[field], provenance[field] = value, "JSON-LD"
        if not authors:
            people = article.get("author", [])
            people = people if isinstance(people, list) else [people]
            for person in people[:100]:
                if isinstance(person, str):
                    person = {"name": person}
                if isinstance(person, dict) and plain(person.get("name")):
                    affiliations_value = person.get("affiliation", [])
                    affiliations_value = affiliations_value if isinstance(affiliations_value, list) else [affiliations_value]
                    authors.append({"raw_name": plain(person["name"]), "identifiers": {"sameAs": person.get("sameAs", "")},
                                    "affiliations": [plain(a.get("name") if isinstance(a, dict) else a) for a in affiliations_value]})
        identifier = article.get("identifier", "")
        identifier = identifier.get("value", "") if isinstance(identifier, dict) else identifier
        if not fields.get("doi") and isinstance(identifier, str) and normalize_doi(identifier):
            fields["doi"], provenance["doi"] = normalize_doi(identifier), "JSON-LD identifier"
    if not fields.get("title") and plain(parser.title):
        fields["title"], provenance["title"] = plain(parser.title), "HTML title（低可信）"
        warnings.append("仅取得网页标题，可能包含网站名称；请人工核对题名。")
    if fields.get("doi"):
        fields["doi"] = normalize_doi(fields["doi"])
    if fields.get("published_on"):
        original = fields["published_on"]
        match = re.match(r"^(\d{4})(?:[-/](\d{2}))?(?:[-/](\d{2}))?", original)
        if match:
            fields["published_on"] = "-".join(p for p in match.groups() if p)
        else:
            fields.pop("published_on")
            warnings.append("页面日期格式无法确定，请按原始依据手填。")
    if authors:
        fields["authors"] = "; ".join(a["raw_name"] for a in authors)
        provenance["authors"] = "citation_author / dc.creator / JSON-LD"
    raw = {"meta": meta, "json_ld": parser.scripts, "html_title": parser.title}
    hints = {"publisher": meta.get("citation_publisher", []), "site_name": meta.get("og:site_name", []), "affiliations": affiliations}
    return fields, authors, identifiers, hints, provenance, raw, warnings


def registry_metadata(document, doi, provider):
    try:
        raw = json.loads(document["text"])
        if provider == "Crossref":
            item = raw["message"]
            if normalize_doi(item.get("DOI")) != doi:
                raise ValueError("Mismatched DOI")
            title = item.get("title", [""])[0]
            container = item.get("container-title", [""])
            fields = {"title": plain(title), "doi": doi, "publication_title": plain(container[0] if container else ""),
                      "abstract": plain(item.get("abstract"), 40000), "language": plain(item.get("language"))}
            fields["url"] = normalize_url(item.get("resource", {}).get("primary", {}).get("URL")) or "https://doi.org/" + doi
            parts = next((item[key]["date-parts"][0] for key in ["published", "published-online", "published-print", "issued"]
                          if item.get(key, {}).get("date-parts")), [])
            if parts and len(parts) <= 3 and all(type(n) is int for n in parts):
                fields["published_on"] = str(parts[0]) + "".join(f"-{n:02d}" for n in parts[1:])
            authors = [{"raw_name": plain(a.get("name") or " ".join([a.get("given", ""), a.get("family", "")])),
                        "identifiers": {"ORCID": a["ORCID"]} if a.get("ORCID") else {},
                        "affiliations": [plain(v.get("name")) for v in a.get("affiliation", []) if isinstance(v, dict)]}
                       for a in item.get("author", [])[:100]]
            identifiers = {"issn": item.get("ISSN", []), "isbn": item.get("ISBN", [])}
            hints = {"publisher": [plain(item.get("publisher"))], "volume": item.get("volume", ""),
                     "issue": item.get("issue", ""), "page": item.get("page", "")}
        else:
            item = raw["data"]["attributes"]
            if normalize_doi(item.get("doi")) != doi:
                raise ValueError("Mismatched DOI")
            fields = {"title": plain(item.get("titles", [{}])[0].get("title")), "doi": doi,
                      "url": normalize_url(item.get("url")) or "https://doi.org/" + doi,
                      "language": plain(item.get("language")), "published_on": str(item.get("publicationYear") or "")}
            descriptions = item.get("descriptions", [])
            fields["abstract"] = next((plain(a.get("description"), 40000) for a in descriptions if a.get("descriptionType") == "Abstract"), "")
            container = item.get("container") or {}
            fields["publication_title"] = plain(container.get("title"))
            authors = [{"raw_name": plain(a.get("name") or " ".join([a.get("givenName", ""), a.get("familyName", "")])),
                        "identifiers": {v["nameIdentifierScheme"]: v["nameIdentifier"] for v in a.get("nameIdentifiers", []) if v.get("nameIdentifierScheme") and v.get("nameIdentifier")},
                        "affiliations": [plain(v.get("name") if isinstance(v, dict) else v) for v in a.get("affiliation", [])]}
                       for a in item.get("creators", [])[:100]]
            identifiers = {"related_identifiers": item.get("relatedIdentifiers", [])}
            hints = {"publisher": [plain(item.get("publisher"))]}
        authors = [a for a in authors if a["raw_name"]]
        if authors:
            fields["authors"] = "; ".join(a["raw_name"] for a in authors)
        if not fields.get("title"):
            raise ValueError("Missing title")
        fields = {k: v for k, v in fields.items() if v}
        return fields, authors, identifiers, hints, {k: provider for k in fields}, raw, []
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        raise AcquisitionError("注册服务返回的题录不完整或格式不支持；请继续手填。") from None


def acquire(value, deadline):
    doi = normalize_doi(value)
    if doi:
        errors = []
        for provider, base in [("Crossref", "https://api.crossref.org/works/"), ("DataCite", "https://api.datacite.org/dois/")]:
            try:
                document = fetch_document(base + quote(doi, safe=""), deadline)
                metadata = registry_metadata(document, doi, provider)
                return document, metadata, provider
            except AcquisitionError as error:
                errors.append(str(error))
                if time.monotonic() >= deadline:
                    break
        raise AcquisitionError("DOI 公开题录暂不可用；请检查编号或继续手填。 " + errors[-1])
    document = fetch_document(value, deadline)
    return document, page_metadata(document), "article-page"


def _orcid(author):
    identifiers = author.get("identifiers", {})
    values = [identifiers.get("ORCID"), identifiers.get("orcid"), identifiers.get("sameAs")]
    for value in values:
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str):
                match = re.fullmatch(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])/?", item.strip(), re.I)
                if match:
                    return match[1].upper()
    return ""


def candidates(db, access, fields, authors, identifiers):
    def label(row, kind, basis):
        return {"id": row["id"], "name": row["name"], "type": kind, "basis": basis}
    verified_ids = {}
    for relation in db.execute("""SELECT b.raw_name,b.target_type,b.target_id,r.* FROM record_bylines b
                                 JOIN records r ON r.id=b.record_id WHERE b.status='confirmed'
                                 AND b.removed_at IS NULL AND r.merged_into IS NULL"""):
        if not access.visible(relation):
            continue
        for acquired in json.loads(relation["raw_json"] or "{}").get("intake_evidence", []):
            for author in acquired.get("authors", []):
                if author.get("raw_name") == relation["raw_name"] and _orcid(author):
                    verified_ids.setdefault(_orcid(author), set()).add((relation["target_type"], relation["target_id"]))
    author_matches = []
    for author in authors:
        name = author["raw_name"].casefold()
        matches = []
        for table, kind, clause in [("people", "person", ""), ("sources", "institution", " AND kind IN ('institution','think_tank')")]:
            for row in db.execute("SELECT * FROM " + table + " WHERE merged_into IS NULL" + clause):
                names = [row["name"], row["aliases"]]
                if table == "sources":
                    names += [row["original_name"]]
                else:
                    names += [row["original_name"], row["chinese_name"]]
                identified = _orcid(author) and (kind, row["id"]) in verified_ids.get(_orcid(author), set())
                if identified or name in {n.strip().casefold() for value in names for n in re.split(r"[\n|;]", value or "")}:
                    matches.append(label(row, kind, "ORCID 与可见作品已确认署名对应，仍需人工核对" if identified else "姓名／名称相同，仅为线索，需人工核对"))
        matches.sort(key=lambda item: not item["basis"].startswith("ORCID"))
        author_matches.append({"raw_name": author["raw_name"], "items": matches[:30], "total": len(matches), "truncated": len(matches) > 30})
    sources = []
    issns = identifiers.get("issn", [])
    issns = [issns] if isinstance(issns, str) else issns
    issns = {str(v).replace("-", "").strip().lower() for v in issns}
    url = normalize_url(fields.get("url"))
    for row in db.execute("SELECT * FROM sources WHERE merged_into IS NULL"):
        if row["kind"] in {"journal", "serial"}:
            stored = {v.replace("-", "").lower() for v in re.split(r"[\s;,|]+", row["issn"] or "") if v}
            name_match = fields.get("publication_title", "").casefold() in {row["name"].casefold(), row["original_name"].casefold()} - {""}
            basis = "ISSN 相同，仍需核对具体刊物" if issns.intersection(stored) else "刊名相同，仅为线索" if name_match else ""
            if basis:
                sources.append({**label(row, row["kind"], basis), "field": "serial_id"})
        elif row["kind"] in {"institution", "think_tank"} and url and normalize_url(row["website"]):
            if urlsplit(url).hostname == urlsplit(normalize_url(row["website"])).hostname:
                sources.append({**label(row, "institution", "文章站点与机构官网相同，需核对发布关系"), "field": "source_id"})
    return {"authors": author_matches, "sources": sources[:50], "source_total": len(sources), "sources_truncated": len(sources) > 50}


def duplicates(db, access, fields):
    doi, url = normalize_doi(fields.get("doi")), normalize_url(fields.get("url"))
    return [{"id": row["id"], "title": row["title"], "basis": "DOI" if doi and normalize_doi(row["doi"]) == doi else "文章网址"}
            for row in db.execute("SELECT * FROM records WHERE merged_into IS NULL")
            if ((doi and normalize_doi(row["doi"]) == doi) or (url and normalize_url(row["url"]) == url)) and access.visible(row)]


def _signer():
    return URLSafeSerializer(current_app.secret_key, salt="assisted-intake-evidence-v1")


def read_token(token, actor):
    if not isinstance(token, str) or len(token) > 3 * MAX_BYTES:
        abort(400, "取得依据格式不正确，请重新提取。")
    try:
        payload = _signer().loads(token)
    except (BadSignature, ValueError):
        abort(400, "取得依据无效，请重新提取；手填内容仍可保留。")
    if not isinstance(payload, dict) or payload.get("actor_id") != actor["id"]:
        abort(403, "取得依据不属于当前账号，请重新提取。")
    return payload["evidence"]


def register(app, ctx):
    @app.post("/api/intake/preview")
    def intake_preview():
        value = ctx.body().get("input")
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            abort(400, "请粘贴一个 DOI 或文章网页链接。")
        if not _slots.acquire(blocking=False):
            abort(429, "当前提取请求较多，请稍后重试或继续手填。")
        try:
            deadline = time.monotonic() + MAX_SECONDS
            document, metadata, provider = acquire(value.strip(), deadline)
            fields, authors, identifiers, hints, provenance, raw, warnings = metadata
            evidence = {"input": value.strip(), "retrieved_at": now(), "fields": fields, "authors": authors,
                        "identifiers": identifiers, "hints": hints, "provenance": provenance,
                        "sources": [{"url": document["url"], "provider": provider, "raw": raw}], "warnings": warnings}
            token = _signer().dumps({"actor_id": ctx.user()["id"], "evidence": evidence})
            return jsonify(**evidence, token=token, duplicates=duplicates(ctx.db(), ctx.records(), fields), candidates=candidates(ctx.db(), ctx.records(), fields, authors, identifiers))
        except AcquisitionError as error:
            abort(422, str(error))
        finally:
            _slots.release()
