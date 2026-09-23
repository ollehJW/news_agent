"""Evaluate unscored subscription articles using the shared article cache."""
import asyncio
from backend.core.auth import database
from backend.core.error_storage import record_error
from backend.core.tracking import llm_user_context,subscription_collection_context
from backend.news.article_repository import decode
from backend.news.scoring_rules import evaluation_complete
from backend.news.news_scoring import score_articles


async def score_sample_articles(sample_id,day,user_id):
    # Include older failures, not only articles inserted by today's collection.
    with database() as db:
        articles=[decode(row) for row in db.execute("""SELECT a.* FROM articles a
            JOIN subscripted_articles sa USING(article_id)
            WHERE sa.sample_id=? ORDER BY sa.collected_at,a.article_id""",(sample_id,))]
    pending=[article for article in articles if not evaluation_complete(article)]
    if not pending:return {'evaluated_count':0,'reused_count':len(articles)}
    user_token=llm_user_context.set(user_id)
    collection_token=subscription_collection_context.set(None)
    async def progress(*args):pass
    try:
        async with asyncio.timeout(360):
            await score_articles('',pending,day,progress,operation='subscription_article_scoring')
        return {'evaluated_count':len(pending),'reused_count':len(articles)-len(pending)}
    except Exception as error:
        record_error(user_id,'subscription_article_scoring',error)
        raise
    finally:
        subscription_collection_context.reset(collection_token)
        llm_user_context.reset(user_token)
