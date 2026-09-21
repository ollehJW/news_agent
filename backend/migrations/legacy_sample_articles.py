"""Retained sample articles, selected issues and legacy imports."""
import json
import uuid
from backend.core.auth import now
from backend.migrations.sample_storage import ensure_draft
from backend.migrations.article_scores import SCORES

ARTICLE_FIELDS='domain_id,url,title,published_at,content,summary,image_url,favicon_url,image_storage_path,collected_at,highlights,request_id'.split(',')+list(SCORES)


def copy_sample_articles(db, source_id, target_id):
    article_ids={}
    for row in db.execute('SELECT * FROM sample_articles WHERE sample_id=?',(source_id,)).fetchall():
        aid=str(uuid.uuid4());article_ids[row['article_id']]=aid
        fields=['article_id','sample_id']+ARTICLE_FIELDS
        db.execute(f"INSERT INTO sample_articles ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                   (aid,target_id,*(row[k] for k in ARTICLE_FIELDS)))
    issue_ids={}
    for row in db.execute('SELECT * FROM sample_issues WHERE sample_id=? ORDER BY rank',(source_id,)).fetchall():
        iid=str(uuid.uuid4());issue_ids[row['issue_id']]=iid
        db.execute('INSERT INTO sample_issues (issue_id,sample_id,article_id,request_id,rank,created_at) VALUES (?,?,?,?,?,?)',
                   (iid,target_id,article_ids[row['article_id']],row['request_id'],row['rank'],row['created_at']))
    return article_ids,issue_ids


def import_legacy_articles(db,sid,articles,issues,preserve_ids=False):
    by_id={r['article_id']:r for r in articles};url_ids={};selected=set();rank=0
    for issue in sorted(issues,key=lambda r:r.get('rank') or 999999):
        row=by_id.get(issue['representative_article_id'])
        if not row:continue
        aid=url_ids.get(row['url'])
        if aid is None:
            aid=row['article_id'] if preserve_ids else str(uuid.uuid4());url_ids[row['url']]=aid
            fields=['article_id','sample_id','domain_id','url','title','published_at','content','summary','image_url','favicon_url','image_storage_path','collected_at']+list(SCORES)
            values=[aid,sid,row.get('domain_id'),row['url'],row['title'],row.get('published_at'),row.get('content_text'),row.get('summary'),row.get('image_url'),row.get('favicon_url'),row.get('image_storage_path'),row['collected_at']]+[issue.get(k) for k in SCORES]
            db.execute(f"INSERT INTO sample_articles ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",values)
        if issue['is_selected'] and aid not in selected:
            rank+=1;selected.add(aid)
            iid=issue['issue_id'] if preserve_ids else str(uuid.uuid4())
            db.execute('INSERT INTO sample_issues (issue_id,sample_id,article_id,rank,created_at) VALUES (?,?,?,?,?)',
                       (iid,sid,aid,rank,issue['created_at']))


def migrate_sample_articles(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_articles'").fetchone():
        return
    all_articles=[dict(r) for r in db.execute('SELECT * FROM run_articles')]
    all_issues=[dict(r) for r in db.execute('SELECT * FROM run_issues')]
    for run_id in {r['run_id'] for r in all_articles}:
        articles=[r for r in all_articles if r['run_id']==run_id]
        issues=[r for r in all_issues if r['run_id']==run_id]
        sid=ensure_draft(db,run_id)
        import_legacy_articles(db,sid,articles,issues,True)
    # Saved samples must reflect their own historical snapshot, not a later re-collection.
    for sample in db.execute("SELECT * FROM sample_newsletters WHERE status='completed'").fetchall():
        articles=[];issues=[]
        for rank,item in enumerate(json.loads(sample['snapshot_json']).get('issues',[]),1):
            aid=str(uuid.uuid4());iid=str(uuid.uuid4())
            domain=db.execute('SELECT domain_id FROM domains WHERE host=?',(item.get('host'),)).fetchone()
            articles.append({'article_id':aid,'domain_id':domain[0] if domain else None,
                'url':item['url'],'title':item['title'],'published_at':item.get('date'),
                'summary':item.get('summary'),'content_text':item.get('summary'),'image_url':item.get('imageUrl'),
                'collected_at':sample['created_at']})
            scores=(item.get('scores') or [None]*4)
            issues.append({'issue_id':iid,'representative_article_id':aid,
                **dict(zip(['technical_score','organization_score','impact_score','recency_score'],scores)),
                'total_score':item.get('score'),'rank':rank,'is_selected':True,'created_at':sample['created_at']})
        import_legacy_articles(db,sample['sample_id'],articles,issues)
    db.execute('DROP TABLE run_issues')
    db.execute('DROP TABLE run_articles')
