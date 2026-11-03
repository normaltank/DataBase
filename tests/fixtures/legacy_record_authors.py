"""Frozen synthetic-fixture parser from dab439a; historical evidence must keep its meaning."""
import json
from platform_app import intake


def legacy_native_authors(document, base):
    """Exact per-author metadata binding; an unrelated name/ORCID in a quote is insufficient."""
    text, kind = document['text'], document['content_type']
    result = []
    if 'json' in kind:
        payload = json.loads(text)
        if 'message' in payload:
            item = payload['message']
            if intake.normalize_doi(item.get('DOI')) != intake.normalize_doi(base['doi']):
                raise ValueError('正式题录 DOI 与本文不一致。')
            authors = item.get('author', [])
            if not isinstance(authors, list) or any(not isinstance(a, dict) for a in authors):
                raise ValueError('正式作者题录列表格式无效。')
            for author in authors[:100]:
                name = intake.plain(author.get('name') or ' '.join([author.get('given', ''), author.get('family', '')]))
                result.append({'raw_name': name, 'kind': 'institution' if author.get('name') else 'person',
                    'orcid': intake._orcid({'identifiers': {'ORCID': author.get('ORCID')}}), 'profile_url': '',
                    'native': author, 'affiliations': [x['name'] for x in author.get('affiliation', []) if isinstance(x, dict) and isinstance(x.get('name'), str)]})
            return result
        raise ValueError('未取得适用的正式作者题录。')
    metadata = intake.page_metadata(document)
    for author in metadata[1]:
        result.append({'raw_name': author['raw_name'], 'kind': 'person', 'orcid': intake._orcid(author),
                       'profile_url': '', 'native': author, 'affiliations': author.get('affiliations', [])})
    parser = intake.ArticleParser()
    parser.feed(text)
    articles = [a for script in parser.scripts for a in intake._articles(script)]
    if len(articles) > 1:
        articles = [a for a in articles if intake.normalize_url(a.get('url') or a.get('@id')) == intake.normalize_url(document['url'])]
    if len(articles) == 1:
        article = articles[0]
        if intake.plain(article.get('headline') or article.get('name')) == metadata[0].get('title'):
            authors = article.get('author', [])
            authors = authors if isinstance(authors, list) else [authors]
            if len(authors) == len(result):
                for existing, native in zip(result, authors):
                    if isinstance(native, dict) and intake.plain(native.get('name')) == existing['raw_name']:
                        existing.update(kind='institution' if native.get('@type') == 'Organization' else 'person',
                            orcid=intake._orcid({'identifiers': {'sameAs': native.get('sameAs')}}),
                            profile_url=intake.normalize_url(native.get('url')), native=native)
                        units = native.get('affiliation', [])
                        units = units if isinstance(units, list) else [units]
                        existing['affiliations'] = [intake.plain(u.get('name')) for u in units if isinstance(u, dict) and u.get('name')]
    return result
