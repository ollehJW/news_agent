"""Sample-scoped article snapshots and legacy run migration."""
import json
import uuid
from .auth import now
from .sample_storage import ensure_draft

ARTICLE_FIELDS='domain_id,url,title,published_at,content,summary,image_url,favicon_url,image_storage_path,collected_at'.split(',')
ISSUE_FIELDS='request_id,technical_score,organization_score,impact_score,recency_score,total_score,rank,is_selected,created_at'.split(',')


def copy_sample_articles(db, source_id, target_id):
    article_ids={}
    for row in db.execute('SELECT * FROM sample_articles WHERE sample_id=?',(source_id,)).fetchall():
        aid=str(uuid.uuid4());article_ids[row['article_id']]=aid
        db.execute('INSERT INTO sample_articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (aid,target_id,*(row[k] for k in ARTICLE_FIELDS)))
    rows=db.execute('SELECT * FROM sample_issues WHERE sample_id=?',(source_id,)).fetchall()
    issue_ids={r['issue_id']:str(uuid.uuid4()) for r in rows}
    for row in rows:
        db.execute('''INSERT INTO sample_issues
            (issue_id,sample_id,article_id,request_id,technical_score,organization_score,impact_score,
             recency_score,total_score,rank,is_selected,created_at,duplicate_of_issue_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (issue_ids[row['issue_id']],target_id,article_ids[row['article_id']],*(row[k] for k in ISSUE_FIELDS),
             issue_ids.get(row['duplicate_of_issue_id'])))
    return article_ids,issue_ids


def import_legacy_articles(db,sid,articles,issues,preserve_ids=False):
    article_ids={};url_ids={};issue_ids={};article_issues={}
    representatives={r['representative_article_id'] for r in issues}
    for row in sorted(articles,key=lambda r:r['article_id'] not in representatives):
        if row['url'] in url_ids:
            article_ids[row['article_id']]=url_ids[row['url']]
            continue
        aid=row['article_id'] if preserve_ids else str(uuid.uuid4())
        article_ids[row['article_id']]=aid;url_ids[row['url']]=aid
        db.execute('INSERT INTO sample_articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (aid,sid,row.get('domain_id'),row['url'],row['title'],row.get('published_at'),
                    row.get('content_text'),row.get('summary'),row.get('image_url'),row.get('favicon_url'),
                    row.get('image_storage_path'),row['collected_at']))
    for row in sorted(issues,key=lambda r:r.get('rank') or 999999):
        aid=article_ids.get(row['representative_article_id'])
        if not aid:
            continue
        if aid in article_issues:
            iid=article_issues[aid];issue_ids[row['issue_id']]=iid
            if row['is_selected']:
                db.execute('UPDATE sample_issues SET is_selected=1 WHERE issue_id=?',(iid,))
            continue
        iid=row['issue_id'] if preserve_ids else str(uuid.uuid4())
        issue_ids[row['issue_id']]=iid;article_issues[aid]=iid
        db.execute('''INSERT INTO sample_issues (issue_id,sample_id,article_id,technical_score,organization_score,
            impact_score,recency_score,total_score,rank,is_selected,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (iid,sid,aid,row.get('technical_score'),row.get('organization_score'),row.get('impact_score'),
             row.get('recency_score'),row.get('total_score'),row.get('rank'),int(bool(row['is_selected'])),row['created_at']))
    for row in articles:
        aid=article_ids.get(row['article_id']);parent=issue_ids.get(row.get('issue_id'))
        if aid and parent and aid not in article_issues:
            iid=str(uuid.uuid4());article_issues[aid]=iid
            db.execute('''INSERT INTO sample_issues (issue_id,sample_id,article_id,is_selected,duplicate_of_issue_id,created_at)
                VALUES (?,?,?,0,?,?)''',(iid,sid,aid,parent,row['collected_at']))


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
