"""Shared article identity and reusable, topic-independent evaluations."""
import json
import uuid
from backend.core.auth import database,now
from backend.integrations.exa_search import canonical_url
from backend.news.article_images import article_image_url
from backend.news.scoring_rules import BASE_SCORES,SCORE_VERSION,evaluation_complete

ARTICLE_FIELDS=('domain_id','url','title','newsletter_title','published_at','content','summary','highlights','image_url','image_storage_path','collected_at','request_id',*BASE_SCORES,'total_score','scored_at','score_version')

def decode(row):
    if row is None:return None
    value=dict(row)
    value['highlights']=json.loads(value['highlights']) if value['highlights'] else []
    return value


def cached_article(url):
    with database() as db:return decode(db.execute('SELECT * FROM articles WHERE url=?',(canonical_url(url),)).fetchone())


def prepare_articles(articles):
    for article in articles:
        article['url']=canonical_url(article['url'])
        existing=cached_article(article['url'])
        article['article_id']=existing['article_id'] if existing else str(uuid.uuid4())
        if existing:
            # Preprocessing uses the current retrieved excerpts; a missing excerpt can reuse cached ones.
            if not article.get('highlights'):article['highlights']=existing['highlights']
    return articles


def store_evaluation(article,score):
    record={**article,**score,'scored_at':now(),'score_version':SCORE_VERSION}
    record['collected_at']=article.get('collected_at') or now()
    record['image_url']=article_image_url(article.get('image_url'),article.get('favicon_url'))
    record['highlights']=json.dumps(article['highlights'],ensure_ascii=False) if article.get('highlights') is not None else None
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=decode(db.execute('SELECT * FROM articles WHERE url=?',(record['url'],)).fetchone())
        if existing and evaluation_complete(existing):return existing
        if existing:
            aid=existing['article_id']
            db.execute('UPDATE articles SET '+','.join(f'{k}=?' for k in ARTICLE_FIELDS)+' WHERE article_id=?',(*[record.get(k) for k in ARTICLE_FIELDS],aid))
        else:
            aid=record['article_id']
            fields=('article_id',*ARTICLE_FIELDS)
            db.execute(f"INSERT INTO articles ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",[record.get(k) for k in fields])
        return decode(db.execute('SELECT * FROM articles WHERE article_id=?',(aid,)).fetchone())
