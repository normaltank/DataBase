"""Deterministic display/query identities; never rewrite registered evidence.

Vendored CLDR 48.0.0 names and explicit independent historical/region labels.
Unknown terms retain their spelling and are matched case-insensitively.
"""
import json
import re
from collections import Counter
from pathlib import Path

DATA = json.loads((Path(__file__).parent/'country_data'/'territories.json').read_text(encoding='utf-8'))
ENTRIES = DATA['entries']
ALIASES = {alias.casefold(): code for code, entry in ENTRIES.items() for alias in [code, *entry['aliases']]}


def key(value):
    value = str(value or '').strip()
    return ALIASES.get(value.casefold(), value.casefold())


def label(value):
    return ENTRIES.get(key(value), {}).get('label', str(value or '').strip())


def terms(value):
    return [part.strip() for part in re.split(r'[;；,，|]', value or '') if part.strip()]


def keys(values):
    return {key(value) for value in values if str(value or '').strip()}


def labels(values):
    return list(dict.fromkeys(label(value) for value in values))


def facet(groups):
    counts, spellings = Counter(), {}
    for values in groups:
        for value in values:
            spellings.setdefault(key(value), label(value))
        counts.update(keys(values))
    return [{'value':value, 'label':spellings[value], 'count':count} for value,count in sorted(counts.items(), key=lambda pair:spellings[pair[0]])]
