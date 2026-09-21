"""Re-render stored WiaNews HTML as an inline-styled, table-based email."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from jinja2 import Environment, FileSystemLoader, select_autoescape


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


def email_html(html,image_sources=None):
    root=Document(html).root
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
        articles.append({'title':first_text(article,'h2'), 'tag':paragraphs[0].text().strip() if paragraphs else '',
            'summary':summary, 'image':image_sources.get(original_image,'') if image_sources is not None else original_image,
            'image_link':original_image,
            'image_alt':images[0].attrs.get('alt','') if images else '',
            'url':safe_url(source.attrs.get('href')) if source else '',
            'date':paragraphs[-1].text().strip() if paragraphs else ''})
    env=Environment(loader=FileSystemLoader(Path(__file__).parent),autoescape=select_autoescape(['html']))
    return env.get_template('newsletter_email.html').render(title=first_text(root,'h1') or first_text(root,'title') or 'WiaNews',
        dates=dates,highlights=highlights,articles=articles,
        fallback=[p.text().strip() for p in root.find('p')] if not articles else [])
