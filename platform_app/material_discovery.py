"""Read-only distributions over the same visible, frozen query as the list."""
from flask import jsonify, request, g
from . import countries, saved_searches
from .automatic_processing import projection
from .reading_feed import terms
from collections import Counter
from .publication_dates import interval


DATE_FIELDS = {'published':'published_on', 'collected':'created_at', 'updated':'updated_at'}


def date_value(row, role):
    value = row[DATE_FIELDS[role]] or ''
    return value if role == 'published' else value[:10]


def date_distribution(rows):
    dates = {}
    for role in DATE_FIELDS:
        years, precision, unknown = Counter(), {'year':0, 'month':0, 'day':0}, 0
        for row in rows:
            value = date_value(row, role)
            if interval(value) is None:
                unknown += 1
                continue
            years[value[:4]] += 1
            precision[{4:'year', 7:'month', 10:'day'}[len(value)]] += 1
        dates[role] = {'years':[{'year':year, 'count':count} for year,count in sorted(years.items(), reverse=True)],
                       'unknown':unknown, 'precision':precision}
    return dates


def register(app, ctx):
    @app.get('/api/material-discovery')
    def distribution():
        rows, _ = ctx.filtered_records(request.args)
        groups = [terms(projection(ctx.db(), row)['subject_countries']) or ['__unknown__'] for row in rows]
        confirmation = g.get('reading_confirmation')
        context_args = dict(saved_searches.resolve(ctx.db(), ctx.user()['id'], request.args))
        context_args.pop('country', None)
        context_rows, _ = ctx.filtered_records(context_args)
        context_groups = [terms(projection(ctx.db(), row)['subject_countries']) or ['__unknown__'] for row in context_rows]
        country_context = {'scope':'query_without_country', 'total':len(context_rows),
                           'countries':countries.facet(context_groups)}
        extra = {}
        if request.args.get('visual_window') == '1':
            args = dict(saved_searches.resolve(ctx.db(), ctx.user()['id'], request.args))
            role = args.get('date_field', 'published')
            for key in ('from', 'to', 'date_unknown', 'date_field'):
                args.pop(key, None)
            time_rows, _ = ctx.filtered_records(args)
            extra['time_context'] = {'scope':'query_without_time', 'total':len(time_rows),
                                     'dates':date_distribution(time_rows)}
            items = []
            for row in rows[:300]:
                value = date_value(row, role)
                precision = {4:'year', 7:'month', 10:'day'}.get(len(value), 'unknown') if interval(value) else 'unknown'
                items.append({'id':row['id'], 'title':row['title'], 'kind':projection(ctx.db(), row)['classified_kind'],
                              'date':value, 'year':int(value[:4]) if precision != 'unknown' else None, 'precision':precision})
            extra['timeline_window'] = {'date_field':role, 'items':items, 'total':len(rows),
                                         'loaded':len(items), 'limit':300, 'has_more':len(rows)>len(items)}
        return jsonify(total=len(rows), countries=countries.facet(groups),
                       dates=date_distribution(rows), country_context=country_context, **extra,
                       reading_confirmation=confirmation)
