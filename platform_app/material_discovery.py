"""Read-only distributions over the same visible, frozen query as the list."""
from flask import jsonify, request, g
from . import countries, saved_searches
from .automatic_processing import projection
from .reading_feed import terms
from collections import Counter
from .publication_dates import interval


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
        dates = {}
        for role, field in [('published', 'published_on'), ('collected', 'created_at'), ('updated', 'updated_at')]:
            years, precision, unknown = Counter(), {'year':0, 'month':0, 'day':0}, 0
            for row in rows:
                value = row[field] if role == 'published' else row[field][:10]
                if interval(value) is None:
                    unknown += 1
                    continue
                years[value[:4]] += 1
                precision[{4:'year', 7:'month', 10:'day'}[len(value)]] += 1
            dates[role] = {'years':[{'year':year, 'count':count} for year,count in sorted(years.items(), reverse=True)],
                           'unknown':unknown, 'precision':precision}
        return jsonify(total=len(rows), countries=countries.facet(groups),
                       dates=dates, country_context=country_context,
                       reading_confirmation=confirmation)
