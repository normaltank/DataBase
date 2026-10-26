"""Consistent accent-insensitive substring matching; original text stays intact."""
import unicodedata


def normalize(value):
    return ''.join(char for char in unicodedata.normalize('NFD', value).casefold()
                   if not unicodedata.combining(char))


def match_start(text, query):
    normalized = normalize(text)
    start = min((normalized.find(word) for word in normalize(query).split() if word in normalized), default=0)
    # Case folding can expand characters and decomposed marks can disappear.
    offsets = [index for index, char in enumerate(text) for _ in normalize(char)]
    return offsets[start] if offsets and start < len(offsets) else 0


class RecordSearch:
    """One request's current graph; permission checks precede text admission."""
    def __init__(self, db, access):
        from collections import defaultdict
        self.sources = {row['id']: row for row in db.execute('SELECT * FROM sources')}
        self.associated = defaultdict(list)
        for row in db.execute('SELECT record_id,source_id FROM record_sources ORDER BY source_id'):
            self.associated[row['record_id']].append(row['source_id'])
        people = {row['id']: row for row in db.execute('SELECT * FROM people')}
        self.bylines = defaultdict(list)
        for row in db.execute('SELECT * FROM record_bylines WHERE removed_at IS NULL OR removed_at="" ORDER BY position,created_at,id'):
            origin = access.prefetched_records.get(row['origin_record_id'])
            if not origin or not access.visible(origin):
                continue
            text = [row['raw_name']]
            if row['status'] == 'confirmed' and row['target_id']:
                target = (people if row['target_type'] == 'person' else self.sources).get(row['target_id'])
                if target:
                    text.extend(target[key] for key in ['name', 'original_name', 'aliases'])
                    if row['target_type'] == 'person':
                        text.append(target['chinese_name'])
            self.bylines[row['record_id']].extend(text)

    def source_text(self, sid):
        source = self.sources.get(sid)
        return ' '.join(source[key] for key in ['name', 'original_name', 'aliases']) if source else ''
