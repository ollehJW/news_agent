"""One Hyundai Wia newsletter template for preview, export and email."""
from urllib.parse import urlsplit
from jinja2 import Environment,FileSystemLoader,select_autoescape
from backend.core.paths import BACKEND_DIR


def safe_url(value):
    try:
        parsed=urlsplit(value or '')
        return value if parsed.scheme in ('http','https') and parsed.hostname else ''
    except ValueError:return ''


def render_document(*,title,dates='',highlights=(),articles=(),fallback=()):
    env=Environment(loader=FileSystemLoader(BACKEND_DIR/'template'),autoescape=select_autoescape(['html']))
    return env.get_template('newsletter.html').render(title=title,dates=dates,highlights=highlights,articles=articles,fallback=fallback)


def render_newsletter(*,title,dates,issues,total_summary=''):
    period=' — '.join(value for value in (dates.get('start'),dates.get('end')) if value)
    return render_document(title=title,dates=period,
        highlights=[line.strip().removeprefix('- ').strip() for line in (total_summary or '').splitlines() if line.strip()],
        articles=[{'title':article['title'],'summary':article.get('summary') or '',
            'image':safe_url(article.get('imageUrl')),'image_link':safe_url(article.get('imageUrl')),
            'image_alt':article.get('imageAlt') or article['title'],'url':safe_url(article.get('url')),
            'date':(article.get('date') or '').replace('-','.')} for article in issues])
