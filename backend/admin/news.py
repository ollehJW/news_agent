"""Paginated, administrator-only access to the global collected article store."""
from fastapi import APIRouter,Depends,HTTPException,Query
from backend.core.auth import admin_user,database

router=APIRouter(prefix='/api/admin/news',dependencies=[Depends(admin_user)])
PAGE_SIZE=20


@router.get('')
def list_news(page: int=Query(1,ge=1)):
    with database() as db:
        total=db.execute('SELECT count(*) FROM articles').fetchone()[0]
        items=[dict(r) for r in db.execute('''SELECT article_id,title,newsletter_title,published_at,total_score,url,collected_at
            FROM articles ORDER BY collected_at DESC,article_id DESC LIMIT ? OFFSET ?''',(PAGE_SIZE,(page-1)*PAGE_SIZE))]
    return dict(items=items,total=total,page=page,page_size=PAGE_SIZE,has_next=page*PAGE_SIZE<total)


@router.get('/{article_id}')
def preview_news(article_id: str):
    with database() as db:
        row=db.execute('''SELECT a.article_id,a.title,a.newsletter_title,a.published_at,a.total_score,a.url,
            a.summary,a.content,a.image_url,a.technical_score,a.organization_score,a.impact_score,d.host
            FROM articles a LEFT JOIN domains d USING(domain_id) WHERE a.article_id=?''',(article_id,)).fetchone()
        if not row:raise HTTPException(404,'기사를 찾을 수 없습니다.')
        return dict(row)
