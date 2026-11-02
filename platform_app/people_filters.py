"""Read-only country projections over complete, permission-checked relationships."""
from . import countries, identity, source_catalog
from .automatic_processing import projection

DIMENSIONS = ('employment_country', 'subject_country')


def country_sets(db, access, people):
    result = {person['id']:{dimension:set() for dimension in DIMENSIONS} for person in people}
    if not result:
        return result
    catalog = source_catalog.catalog(db)
    resolved_people, resolved_sources = {}, {}

    def resolved(table, value, cache):
        if value not in cache:
            row = identity.resolve(db, table, value)
            cache[value] = row['id'] if row else None
        return cache[value]

    for row in db.execute("SELECT * FROM person_employments WHERE removed_at IS NULL AND evidence<>'' AND role<>''"):
        pid = resolved('people', row['person_id'], resolved_people)
        sid = resolved('sources', row['institution_id'], resolved_sources)
        source = catalog.get(sid)
        if pid in result and source and source['kind'] in source_catalog.INSTITUTIONS:
            result[pid]['employment_country'].update(source_catalog.ids(source['country']))

    records = {row['id']:row for row in db.execute('SELECT * FROM records')}
    access.prefetched_records = records
    subjects = {}
    for row in db.execute("SELECT * FROM record_bylines WHERE target_type='person' AND status='confirmed' AND removed_at IS NULL"):
        pid = resolved('people', row['target_id'], resolved_people)
        record = records.get(row['record_id'])
        origin = records.get(row['origin_record_id'])
        if pid not in result or not record or record['merged_into'] or not origin:
            continue
        if not access.visible(record) or not access.visible(origin):
            continue
        if record['id'] not in subjects:
            subjects[record['id']] = countries.terms(projection(db, record)['subject_countries'])
        result[pid]['subject_country'].update(subjects[record['id']])
    return {pid:{dimension:values or {'__unknown__'} for dimension,values in dimensions.items()} for pid,dimensions in result.items()}


def filter_people(rows, values, args):
    selected = {dimension:countries.keys(str(args.get(dimension, '')).split('|')) for dimension in DIMENSIONS}
    matched = [row for row in rows if all(not selected[dimension] or selected[dimension].intersection(countries.keys(values[row['id']][dimension])) for dimension in DIMENSIONS)]
    facets = {dimension:countries.facet([values[row['id']][dimension] for row in matched]) for dimension in DIMENSIONS}
    options = {}
    for dimension in DIMENSIONS:
        other = next(key for key in DIMENSIONS if key != dimension)
        options[dimension] = countries.facet([values[row['id']][dimension] for row in rows
                                            if not selected[other] or selected[other].intersection(countries.keys(values[row['id']][other]))])
    return matched, facets, options
