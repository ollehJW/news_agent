"""Merge article snapshots by canonical URL without inventing preprocessing provenance."""
import json
import sqlite3
from backend.core.paths import BACKEND_DIR
from backend.integrations.exa_search import canonical_url
from backend.news.scoring_rules import SCORE_VERSION,weighted_scores


def migrate_shared_articles(db):
    schema=(BACKEND_DIR/'migrations/pre_subscription_collection.sql').read_text()
    def create(table, replacement=False):
        start=schema.index(f'CREATE TABLE IF NOT EXISTS {table} (')
        ddl=schema[start:schema.index(';',start)+1]
        if replacement:ddl=ddl.replace(f'IF NOT EXISTS {table}',table+'_shared')
        db.execute(ddl)
    create('articles')
    samples=[dict(r) for r in db.execute('SELECT * FROM sample_articles')]
    subs=[dict(r) for r in db.execute('SELECT * FROM subscripted_articles')]
    sample_issues=[dict(r) for r in db.execute('SELECT * FROM sample_issues ORDER BY sample_id,rank')]
    sub_issues=[dict(r) for r in db.execute('SELECT * FROM subscripted_issues ORDER BY created_at,issue_id')]
    dates=dict(db.execute('SELECT sample_id,collection_end_date FROM sample_newsletters'))
    sub_evals={r['article_id']:r['request_id'] for r in sub_issues if r['request_id']}
    mapping={};fields=['article_id','domain_id','url','title','published_at','content','summary','highlights','image_url','collected_at','request_id','technical_score','organization_score','impact_score','total_score','scored_at','score_version']
    # Prefer an evaluated snapshot when multiple samples stored the same URL.
    candidates=[('sample_articles',r) for r in samples]+[('subscripted_articles',r) for r in subs]
    candidates.sort(key=lambda pair:(not all(pair[1].get(k) is not None for k in ('technical_score','organization_score','impact_score')),not bool(pair[1].get('summary')),pair[1]['collected_at'],pair[1]['article_id']))
    for table,row in candidates:
        url=canonical_url(row['url'])
        if not url:raise ValueError('Cannot migrate invalid article URL')
        existing=db.execute('SELECT article_id FROM articles WHERE url=?',(url,)).fetchone()
        if existing:aid=existing[0]
        else:
            aid=row['article_id'];record={k:row.get(k) for k in fields}
            request=row.get('request_id') if table=='sample_articles' else sub_evals.get(aid)
            stamp=db.execute('SELECT completed_at FROM llm_requests WHERE request_id=?',(request,)).fetchone() if request else None
            record.update(url=url,request_id=request,scored_at=stamp[0] if stamp else None,score_version=SCORE_VERSION if all(row.get(k) is not None for k in ('technical_score','organization_score','impact_score')) else None)
            record.update(weighted_scores(record))
            db.execute(f"INSERT INTO articles ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",[record[k] for k in fields])
        mapping[(table,row['article_id'])]=aid
    for table in ('sample_articles','subscripted_articles','sample_issues','subscripted_issues'):create(table,True)
    for row in samples:
        # Previous sample request_id was evaluation, not preprocessing: retain it only in articles.
        db.execute('INSERT OR IGNORE INTO sample_articles_shared VALUES (?,?,NULL)',(row['sample_id'],mapping[('sample_articles',row['article_id'])]))
    for row in subs:
        owners=db.execute('SELECT subscription_id FROM subscriptions WHERE sample_id=?',(row['sample_id'],)).fetchall()
        if not owners:raise ValueError('Subscription article has no subscription to map')
        for owner in owners:
            db.execute('INSERT OR IGNORE INTO subscripted_articles_shared VALUES (?,?,?)',(owner[0],mapping[('subscripted_articles',row['article_id'])],row.get('request_id')))
    counts={};seen=set()
    for row in sample_issues:
        aid=mapping[('sample_articles',row['article_id'])];sid=row['sample_id']
        if (sid,aid) in seen:continue
        seen.add((sid,aid));counts[sid]=counts.get(sid,0)+1
        db.execute('INSERT INTO sample_issues_shared VALUES (?,?,?,?,?,?)',(row['issue_id'],sid,aid,row['request_id'],counts[sid],row['created_at']))
    for row in sub_issues:
        row['article_id']=mapping[('subscripted_articles',row['article_id'])]
        fields=['issue_id','subscription_id','article_id','request_id','summary','rank','created_at']
        db.execute(f"INSERT INTO subscripted_issues_shared ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",[row[k] for k in fields])
    for table in ('sample_issues','subscripted_issues','sample_articles','subscripted_articles'):db.execute(f'DROP TABLE {table}')
    for table in ('sample_articles','subscripted_articles','sample_issues','subscripted_issues'):db.execute(f'ALTER TABLE {table}_shared RENAME TO {table}')
    statement=''
    for line in schema.splitlines(True):
        statement+=line
        if sqlite3.complete_statement(statement):db.execute(statement);statement=''
