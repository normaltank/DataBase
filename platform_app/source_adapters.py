"""Bounded official source adapters. Registration alone never enables collection."""
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from . import intake, workflow, journal_metadata

ADAPTERS = (
    dict(id='liia-opinions-v1', name='LIIA Opinions', kinds={'institution', 'think_tank'},
         hosts={'liia.lv', 'www.liia.lv'}, roots={'/', '/en', '/en/'},
         feed='https://liia.lv/en/opinions/rss.xml', column='https://liia.lv/en/opinions',
         article=r'/en/opinions/[A-Za-z0-9_-]+/?', format='LIIA RSS', mode='rss',
         scope='仅当前固定 RSS；没有遍历栏目或历史回填'),
    dict(id='gssc-publications-v1', name='GSSC Publications', kinds={'institution', 'think_tank'},
         hosts={'www.gssc.lt', 'gssc.lt'}, roots={'/', '/en', '/en/'},
         feed='https://www.gssc.lt/en/publications/', column='https://www.gssc.lt/en/publications/',
         article=r'/en/publication/[A-Za-z0-9_-]+/?', format='GSSC HTML listing', mode='html',
         scope='仅官方 Publications 列表当前页；未遍历分页或完整历史'),
    dict(id='cjir-rss-v1', name='CJIR RSS', kinds={'journal'}, hosts={'cjir.iir.cz'},
         roots={'/', '/index.php/cjir', '/index.php/cjir/'},
         feed='https://cjir.iir.cz/index.php/cjir/gateway/plugin/WebFeedGatewayPlugin/rss2',
         column='https://cjir.iir.cz/index.php/cjir/issue/current',
         article=r'/index.php/cjir/article/view/\d+/?', format='CJIR RSS', mode='rss',
         scope='仅官方声明 RSS 当前响应；不代表完整卷期或 ahead-of-print 覆盖'),
    dict(id='intersections-rss-v1', name='Intersections RSS', kinds={'journal'}, hosts={'intersections.tk.hu'},
         roots={'/', '/index.php/intersections', '/index.php/intersections/'},
         feed='https://intersections.tk.hu/index.php/intersections/gateway/plugin/WebFeedGatewayPlugin/rss2',
         column='https://intersections.tk.hu/index.php/intersections/issue/current',
         article=r'/index.php/intersections/article/view/\d+/?', format='Intersections RSS', mode='rss',
         scope='仅官方声明 RSS 当前响应；刊期年份与上线日期分别保留，近期可为零'),
) + journal_metadata.ADAPTERS


def for_source(source):
    try:
        p = urlsplit(intake.normalize_url(source['website']))
        if p.scheme != 'https' or p.port not in {None, 443} or p.query or p.fragment:
            return None
        # The existing SER-SSE-BJE archive uses its SSE Riga journal page.
        # Keep that identity and website; collection still uses fixed Crossref.
        if (source['kind']=='journal' and p.hostname in {'www.sseriga.edu','sseriga.edu'}
                and p.path.rstrip('/')=='/centres/biceps/bje'
                and set(re.split(r'[\s;,|]+',source['issn'] or '')) & {'1406-099X','2334-4385'}):
            return next(a for a in ADAPTERS if a['id']=='bje-crossref-v1')
        return next((a for a in ADAPTERS if source['kind'] in a['kinds'] and p.hostname in a['hosts'] and p.path in a['roots']), None)
    except ValueError:
        return None


def article_url(adapter, value):
    p = urlsplit(intake.normalize_url(value))
    return (p.scheme == 'https' and p.hostname in adapter['hosts'] and p.port in {None, 443}
            and not p.query and not p.fragment and bool(re.fullmatch(adapter['article'], p.path)))


def canonical(value):
    url = intake.normalize_url(value)
    url = url.replace('https://www.liia.lv/', 'https://liia.lv/')
    url = url.replace('https://gssc.lt/', 'https://www.gssc.lt/')
    return url.rstrip('/')


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs or {}, parent, []

    def matches(self, tag=None, classes=()):
        return (tag is None or self.tag == tag) and set(classes) <= set(self.attrs.get('class', '').split())

    def find(self, tag=None, classes=()):
        return [n for n in self.walk() if n.matches(tag, classes)]

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def html(self):
        return ''.join(c.render() if isinstance(c, Node) else escape(c) for c in self.children)

    def render(self):
        return '<' + self.tag + ''.join(' ' + k + '="' + escape(v, quote=True) + '"' for k, v in self.attrs.items()) + '>' + self.html() + '</' + self.tag + '>'

    def text(self):
        return intake.plain(self.html(), 40000)


class Tree(HTMLParser):
    """Small bounded selector tree for the two known official layouts."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.count = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 30000:
            raise intake.AcquisitionError('官方页面结构超过解析上限。')
        node = Node(tag, {k: v or '' for k, v in attrs}, self.current)
        depth, ancestor = 0, self.current
        while ancestor.parent is not None:
            depth, ancestor = depth + 1, ancestor.parent
        if depth >= 100:
            raise intake.AcquisitionError('官方页面嵌套超过解析上限。')
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, text):
        self.current.children.append(text)


def first(nodes):
    return nodes[0] if nodes else Node()


def gssc_date(value):
    # Explicit English month names; independent of the server's locale.
    months = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
    match = re.fullmatch(r'([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})', value.strip())
    if not match or match[1] not in months:
        return ''
    try:
        return datetime(int(match[3]), months[match[1]], int(match[2]), tzinfo=timezone.utc).date().isoformat()
    except ValueError:
        return ''


def listing_nodes(content):
    tree = Tree(content.decode('utf-8', errors='replace')).root
    articles = tree.find('article', ('single-article',))
    if not articles:
        raise intake.AcquisitionError('未辨认 GSSC 官方列表；可能为空壳或挑战页面。')
    result = []
    for article in articles:
        link = first(article.find('a', ('title',)))
        displayed = first(article.find(classes=('date',))).text()
        date = gssc_date(displayed)
        node = ET.Element('item')
        values = dict(title=link.text(), link=link.attrs.get('href', ''), guid='',
                      pubDate=format_datetime(datetime.fromisoformat(date).replace(tzinfo=timezone.utc)) if date else '',
                      displayed_date=displayed, description=first(article.find(classes=('text',))).text(),
                      authors='; '.join(n.text() for n in article.find(classes=('author',))))
        for key, value in values.items():
            ET.SubElement(node, key).text = value
        result.append(node)
    return result


def bound_authors(document):
    """Bind identifiers only inside one author li, or an explicit GSSC byline."""
    tree = Tree(document['text']).root
    result = []
    for section in tree.find(classes=('item', 'authors')):
        for row in section.find('li'):
            name = first(row.find(classes=('name',))).text()
            links = [link.attrs.get('href', '') for group in row.find(classes=('orcid',)) for link in group.find('a')]
            orcids = {intake._orcid({'identifiers': {'ORCID': value}}) for value in links} - {''}
            if name:
                result.append(dict(raw_name=name, identifiers={'ORCID': next(iter(orcids))} if len(orcids) == 1 else {},
                                   affiliations=[n.text() for n in row.find(classes=('affiliation',))], profile_url=''))
    if result:
        return result[:100]
    if urlsplit(document['url']).hostname not in {'gssc.lt', 'www.gssc.lt'}:
        return []
    main = first(tree.find(classes=('single-publication',)))
    # The first explicit byline precedes the body. The later biography cards
    # repeat these names and must not become duplicate work signatures.
    for section in main.find(classes=('authors',))[:1]:
        for link in section.find('a', ('title',)):
            url = intake.normalize_url(urljoin(document['url'], link.attrs.get('href', '')))
            if link.text() and urlsplit(url).hostname in {'gssc.lt', 'www.gssc.lt'} and re.fullmatch(r'/en/autoriai/[A-Za-z0-9_-]+/?', urlsplit(url).path):
                result.append(dict(raw_name=link.text(), identifiers={}, affiliations=[], profile_url=url))
    return result[:100]


def article(document, adapter):
    if not article_url(adapter, document['url']):
        raise intake.AcquisitionError('文章响应已离开固定官方文章路径；未作为取得成功。')
    tree = Tree(document['text']).root
    fields, authors, identifiers, hints, provenance, raw, warnings = intake.page_metadata(document)
    bindings = bound_authors(document)
    if bindings:
        authors = bindings
        fields['authors'] = '; '.join(a['raw_name'] for a in authors)
        provenance['authors'] = '逐作者官方署名容器'
    body_html = ''
    pdf_links = []
    if adapter['mode'] == 'html':
        main = first(tree.find(classes=('single-publication',)))
        title = first(main.find('h1')).text()
        if not title:
            raise intake.AcquisitionError('未辨认 GSSC 文章标题；不将空壳视为成功。')
        fields['title'], provenance['title'] = title, '.single-publication h1'
        displayed = first(main.find(classes=('date',))).text()
        date = gssc_date(displayed)
        if date:
            fields['published_on'], provenance['published_on'] = date, '.single-publication .meta .date'
        raw['displayed_date'] = displayed
        blocks = [n for block in main.find(classes=('content-block',)) for n in block.find(classes=('text', 'excerpt'))]
        if len(blocks) == 1:
            body_html = blocks[0].html()
        abstract_html = ''
    else:
        # Citation metadata alone can be a login/challenge page; require the
        # actual known article title and the original abstract container.
        if not fields.get('title') or provenance.get('title', '').startswith('HTML title'):
            raise intake.AcquisitionError('未取得正式期刊文章题录；可能为挑战或登录页面。')
        abstracts = tree.find(classes=('item', 'abstract'))
        abstract_basis = '.item.abstract（原摘要）'
        if not abstracts and adapter['id'] == 'cjir-rss-v1':
            abstracts = [section for main in tree.find(classes=('article-details-main',))
                         for section in main.find('section')
                         if any(isinstance(c, Node) and c.tag == 'h2' and c.text() == 'Abstract' for c in section.children)]
            abstract_basis = '.article-details-main section > h2 Abstract（原摘要）'
        abstract_html = first(abstracts).html()
        if abstracts:
            abstract_html = ''.join(c.render() if isinstance(c, Node) else escape(c)
                                    for c in abstracts[0].children if not isinstance(c, Node) or c.tag not in {'h2', 'h3'})
            fields['abstract'] = workflow.clean_rich(abstract_html)[1]
            provenance['abstract'] = abstract_basis
        else:
            fields.pop('abstract', None)
        for value in raw['meta'].get('citation_pdf_url', []):
            url = intake.normalize_url(urljoin(document['url'], value))
            p = urlsplit(url)
            if p.scheme == 'https' and p.hostname in adapter['hosts'] and '/article/download/' in p.path:
                pdf_links.append(url)
    raw['date_fields'] = {key: values for key, values in raw['meta'].items() if 'date' in key or key == 'article:published_time'}
    cleaned, text = workflow.clean_rich(body_html or abstract_html)
    return dict(fields=fields, authors=authors, identifiers=identifiers, provenance=provenance, raw=raw, warnings=warnings), cleaned, text, bool(body_html and text), sorted(set(pdf_links))
