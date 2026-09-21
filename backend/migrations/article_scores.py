"""Move scores to retained articles and keep only selected issue rows."""
import json
from backend.core.paths import BACKEND_DIR

SCORES=('technical_score','organization_score','impact_score','recency_score','total_score')

def migrate_article_scores(db):
    for table in ('sample_articles','subscripted_articles'):
        columns={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
        for name in SCORES:
            if name not in columns:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {name} REAL CHECK({name} BETWEEN 0 AND 100)')
        if table=='sample_articles' and 'request_id' not in columns:
            db.execute('ALTER TABLE sample_articles ADD COLUMN request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL')
    schema=(BACKEND_DIR/'migrations'/'legacy_articles.sql').read_text()
    for table,articles in (('sample_issues','sample_articles'),('subscripted_issues','subscripted_articles')):
        cols={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
        if 'total_score' not in cols:
            continue
        rows=[dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY created_at,issue_id')]
        for row in rows:
            db.execute(f"UPDATE {articles} SET "+','.join(f'{k}=?' for k in SCORES)+' WHERE article_id=?',
                       (*[row[k] for k in SCORES],row['article_id']))
            if table=='sample_issues':
                db.execute('UPDATE sample_articles SET request_id=? WHERE article_id=?',(row['request_id'],row['article_id']))
        if table=='sample_issues':
            # Historical representatives identify the articles that passed preprocessing.
            retained={r['article_id'] for r in rows if not r['duplicate_of_issue_id']}
            rows=[r for r in rows if r['is_selected'] and not r['duplicate_of_issue_id']]
            rows.sort(key=lambda r:(r['sample_id'],r['rank'] or 999999,r['issue_id']))
        else:
            ranks={}
            for edition in db.execute('SELECT issue_ids FROM subscripted_newsletters'):
                for rank,iid in enumerate(json.loads(edition[0]),1):
                    if iid in ranks and ranks[iid]!=rank:
                        raise ValueError('An issue is reused at conflicting newsletter ranks')
                    ranks[iid]=rank
        start=schema.index(f'CREATE TABLE IF NOT EXISTS {table} (')
        ddl=schema[start:schema.index(';',start)+1].replace(f'IF NOT EXISTS {table}',table+'_replacement')
        db.execute(ddl)
        counters={}
        for row in rows:
            group=row.get('sample_id') or row['subscription_id']
            counters[group]=counters.get(group,0)+1
            rank=counters[group] if table=='sample_issues' else ranks.get(row['issue_id'],counters[group])
            fields=['issue_id','sample_id' if table=='sample_issues' else 'subscription_id','article_id','request_id','rank','created_at']
            if table=='subscripted_issues':fields.append('summary')
            row['rank']=rank
            db.execute(f"INSERT INTO {table}_replacement ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",[row[k] for k in fields])
        db.execute(f'DROP TABLE {table}')
        db.execute(f'ALTER TABLE {table}_replacement RENAME TO {table}')
        if table=='sample_issues':
            for row in db.execute('SELECT article_id FROM sample_articles').fetchall():
                if row[0] not in retained:db.execute('DELETE FROM sample_articles WHERE article_id=?',(row[0],))
            db.execute('CREATE INDEX sample_issues_rank ON sample_issues(sample_id,rank)')
        else:
            db.execute('CREATE INDEX subscripted_issues_subscription ON subscripted_issues(subscription_id,created_at)')
            db.execute('CREATE INDEX subscripted_issues_article ON subscripted_issues(article_id)')
            db.execute('CREATE INDEX subscripted_issues_request ON subscripted_issues(request_id)')
