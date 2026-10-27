"""Independent reader only. Never imports application modules or reads a database."""
from pathlib import Path
import argparse
from datetime import date
import hashlib
import importlib.metadata
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_vendor"))
import rispy
VERSION = importlib.metadata.version("rispy")
if VERSION != "0.10.0":
    raise RuntimeError("Expected isolated rispy==0.10.0, found " + VERSION)
EXPECTED = json.loads((ROOT / "expected.json").read_text(encoding="utf-8"))

def load_default(name):
    # Deliberate BOM handling is outside rispy.
    return rispy.loads((ROOT / name).read_bytes().decode("utf-8-sig"))

def tagged_read(path):
    # Public rispy options keep every supported tag as a list; no application parser.
    mapping = {key: key for key in rispy.TAG_KEY_MAPPING}
    return rispy.loads(path.read_bytes().decode("utf-8-sig"),
        mapping=mapping,
        list_tags=[tag for tag in mapping if tag not in {"TY", "ER", "UK"}],
        delimiter_tags_mapping={})

def values(record, *tags):
    result = []
    for tag in tags:
        value = record.get(tag, [])
        result.extend(value if isinstance(value, list) else [value])
    return [value for value in result if value != ""]

def single(record, *tags):
    found = values(record, *tags)
    distinct = list(dict.fromkeys(found))
    if len(distinct) > 1:
        raise ValueError("Conflicting exported scalar aliases: " + "/".join(tags))
    return distinct[0] if distinct else ""

def date_value(record):
    found = []
    for raw in values(record, "PY", "Y1", "DA"):
        text = raw.rstrip("/")
        if not re.fullmatch(r"\d{4}(?:[-/]\d{2}(?:[-/]\d{2})?)?", text):
            raise ValueError("Unsupported exported date: " + raw)
        normalized = text.replace("/", "-")
        parts = [int(x) for x in normalized.split("-")]
        date(*(parts + [1] * (3 - len(parts))))
        found.append(normalized)
    if not found:
        return ""
    winner = max(found, key=len)
    if any(not (winner == value or winner.startswith(value + "-")) for value in found):
        raise ValueError("Inconsistent exported dates: " + repr(found))
    return winner

def projection(record):
    # Only semantic normalization between RIS standard tag aliases. No app field logic.
    start, end = single(record, "SP"), single(record, "EP")
    pages = (start + "-" + end) if start and end and start != end else start or end
    result = dict(type=record.get("TY", ""), title=single(record, "TI", "T1"),
        authors=values(record, "AU", "A1"), publication_title=single(record, "JF", "JO", "T2"),
        published_on=date_value(record), volume=single(record, "VL"),
        issue=single(record, "IS"), pages=pages, issn=values(record, "SN"),
        doi=single(record, "DO"), url=single(record, "UR"),
        abstract=single(record, "AB", "N2"), keywords=values(record, "KW"),
        language=single(record, "LA"))
    if values(record, "TT"):
        result["translated_title"] = single(record, "TT")
    return result

ALLOWED_OUTPUT_TAGS = {"TY","ER","TI","T1","AU","A1","JF","JO","T2","PY","Y1","DA",
    "VL","IS","SP","EP","SN","DO","UR","AB","N2","KW","LA","TT","N1"}

def check_export(path, case):
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Canonical export probe requires UTF-8 without BOM.")
    text = raw.decode("utf-8")
    if not raw.endswith(b"\r\n") or b"\n" in raw.replace(b"\r\n", b"") or b"\r" in raw.replace(b"\r\n", b""):
        raise ValueError("Expected canonical CRLF line endings including final newline.")
    # A small structural guard complements rispy's permissive reader; not a second parser.
    # No values are extracted by this guard.
    inside = False
    structural_count = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9])  - (.*)", line)
        if not match:
            raise ValueError("Noncanonical tag line at " + str(number))
        tag, value = match.groups()
        if tag not in ALLOWED_OUTPUT_TAGS:
            raise ValueError("Unexpected standard-output tag " + tag)
        if tag == "TY":
            if inside:
                raise ValueError("Nested TY")
            inside = True
        elif tag == "ER":
            if not inside or value:
                raise ValueError("Unexpected or nonempty ER")
            inside = False
            structural_count += 1
        elif not inside:
            raise ValueError("Tag outside TY/ER")
    if inside:
        raise ValueError("Unterminated output")
    parsed = tagged_read(path)
    wanted = EXPECTED["export_cases"][case]["records"]
    actual = [projection(record) for record in parsed]
    if structural_count != len(actual):
        raise ValueError("Reader/structure record-count mismatch")
    if actual != wanted:
        raise AssertionError(json.dumps({"expected": wanted, "actual": actual}, ensure_ascii=False, indent=2))
    return {"status":"PASS","case":case,"rispy":VERSION,"records":len(actual),
        "sha256":hashlib.sha256(raw).hexdigest(),
        "scope":"Independent standard-output reader comparison only; not application acceptance."}

def self_check():
    wanted = EXPECTED["rispy_default_limitations_expected"]
    core = load_default("01_core_utf8_lf.ris")
    conflict = load_default("03_alias_conflicts_unknown.ris")[0]
    list_tags = [*rispy.LIST_TYPE_TAGS, "SN"]
    configured = rispy.loads((ROOT/"01_core_utf8_lf.ris").read_text(encoding="utf-8"), list_tags=list_tags)
    configured_conflict = rispy.loads((ROOT/"03_alias_conflicts_unknown.ris").read_text(encoding="utf-8"), list_tags=list_tags)[0]
    tt = load_default("09_translated_title_reader_probe.ris")[0]
    observed = {
        "core_count":len(core),
        "default_core_first_issn":core[0]["issn"],
        "configured_core_first_issn":configured[0]["issn"],
        "default_conflict_issn":conflict["issn"],
        "configured_conflict_issn":configured_conflict["issn"],
        "default_alias_keys_distinct":[key for key in wanted["default_alias_keys_distinct"] if key in conflict],
        "default_unterminated_records":len(load_default("06_unterminated_structure.ris")),
        "tt_title":tt["title"], "tt_translated_title":tt["translated_title"],
    }
    for key,value in observed.items():
        if value != wanted[key]:
            raise AssertionError(key + ": " + repr(value) + " != " + repr(wanted[key]))
    equivalent = tagged_read(ROOT/"01_core_utf8_lf.ris") == tagged_read(ROOT/"02_core_bom_crlf.ris")
    if not equivalent:
        raise AssertionError("LF/BOM+CRLF semantic mismatch after deliberate UTF-8-sig decode")
    reference = check_export(ROOT/"08_reference_standard_export.ris", "core")
    # Exercise the whole checker against an independently fixed wrong-title fixture.
    try:
        check_export(ROOT/"10_negative_changed_title_export.ris", "core")
    except AssertionError:
        pass
    else:
        raise AssertionError("Wrong-title export was incorrectly accepted")
    report={"status":"PASS","rispy":VERSION,
        "observations":observed,"bom_crlf_after_deliberate_decode":equivalent,
        "default_book_parse_count":len(load_default("04_unsupported_book_and_valid.ris")),
        "default_nested_ty_parse":load_default("07_nested_ty_structure.ris"),
        "reference_harness_check":reference,
        "negative_control":"Whole export checker rejected fixed wrong-title file 10.",
        "boundary":"Self-check validates these fixtures and the reader harness only. No app, app tests, real materials or databases were accessed."}
    (ROOT/"rispy-observations.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_file", nargs="?", type=Path)
    parser.add_argument("--case", choices=list(EXPECTED["export_cases"]), default="core")
    parser.add_argument("--self-check", action="store_true")
    args=parser.parse_args()
    if args.self_check:
        result=self_check()
    elif args.export_file:
        result=check_export(args.export_file.resolve(strict=True),args.case)
    else:
        parser.error("Provide --self-check or an explicitly selected synthetic export file.")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
