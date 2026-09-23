"""Re-render stored WiaNews HTML as an inline-styled, table-based email."""
from html.parser import HTMLParser
from urllib.parse import urlsplit
from backend.news.newsletter_rendering import render_document


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag=tag
        self.attrs=dict(attrs)
        self.children=[]

    def find(self, tag):
        return [child for child in self.walk() if child.tag==tag]

    def walk(self):
        for child in self.children:
            if isinstance(child,Node):
                yield child
                yield from child.walk()

    def text(self):
        if self.tag in ('script','style'):return ''
        if self.tag=='br':return '\n'
        return ''.join(child.text() if isinstance(child,Node) else child for child in self.children)


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root=Node()
        self.stack=[self.root]
        self.feed(html)

    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs)
        self.stack[-1].children.append(node)
        if tag not in ('img','br','hr','meta','link','input','wbr','source','area','base','embed','param','col'):
            self.stack.append(node)

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        self.handle_endtag(tag)

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:]
                break

    def handle_data(self,data):
        self.stack[-1].children.append(data)


def safe_url(value):
    try:
        parsed=urlsplit(value or '')
        return value if parsed.scheme in ('http','https') and parsed.hostname else ''
    except ValueError:return ''


def first_text(node,tag):
    matches=node.find(tag)
    return matches[0].text().strip() if matches else ''


def article_nodes(root):
    marked=[node for node in root.walk() if 'data-newsletter-article' in node.attrs]
    return marked or root.find('article')


def field(node,name):
    return next((child for child in node.walk() if child.attrs.get('data-newsletter-field')==name),None)


def field_text(node,name):
    value=field(node,name)
    return value.text().strip() if value else ''


def newsletter_data(html):
    root=Document(html).root
    if any(node.attrs.get('data-newsletter-version') for node in root.walk()):
        articles=[]
        for article in article_nodes(root):
            images=article.find('img');image=safe_url(images[0].attrs.get('src')) if images else ''
            source=field(article,'source')
            articles.append({'title':field_text(article,'article-title'),'summary':field_text(article,'summary'),
                'image':image,'image_link':image,'image_alt':images[0].attrs.get('alt','') if images else '',
                'url':safe_url(source.attrs.get('href')) if source else '', 'date':field_text(article,'article-date')})
        return {'title':field_text(root,'title') or first_text(root,'title'),'dates':field_text(root,'dates'),
            'highlights':[node.text().strip() for node in root.walk() if node.attrs.get('data-newsletter-field')=='highlight'],
            'articles':articles,'fallback':[node.text().strip() for node in root.walk() if node.attrs.get('data-newsletter-field')=='fallback']}
    header=root.find('header')
    dates=first_text(header[0],'span').lstrip('/ \u00a0') if header else ''
    highlights=[]
    for section in root.find('section'):
        if '이번 호 핵심 요약' in first_text(section,'h2'):
            highlights.extend(li.text().strip() for li in section.find('li') if li.text().strip())
    articles=[]
    for article in root.find('article'):
        paragraphs=article.find('p')
        summary=next((p.text().strip() for p in paragraphs if 'pre-line' in p.attrs.get('style','')), '')
        if not summary and len(paragraphs)>1:summary=paragraphs[1].text().strip()
        images=article.find('img')
        source=next((a for a in article.find('a') if a.find('svg') or '출처' in a.attrs.get('title','')),None)
        original_image=safe_url(images[0].attrs.get('src')) if images else ''
        articles.append({'title':first_text(article,'h2'),
            'summary':summary, 'image':original_image,
            'image_link':original_image,
            'image_alt':images[0].attrs.get('alt','') if images else '',
            'url':safe_url(source.attrs.get('href')) if source else '',
            'date':paragraphs[-1].text().strip().replace('-','.') if paragraphs else ''})
    return {'title':first_text(root,'h1') or first_text(root,'title') or 'WiaNews',
        'dates':dates,'highlights':highlights,'articles':articles,
        'fallback':[p.text().strip() for p in root.find('p')] if not articles else []}


def email_html(html,image_sources=None):
    data=newsletter_data(html)
    if image_sources is not None:
        for article in data['articles']:
            article['image']=image_sources.get(article['image'],'')
    return render_document(**data)
