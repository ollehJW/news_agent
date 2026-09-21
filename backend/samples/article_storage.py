"""Copy sample links and selections while preserving shared article identities."""
import uuid


def copy_sample_articles(db,source_id,target_id):
    article_ids={r[0]:r[0] for r in db.execute('SELECT article_id FROM sample_articles WHERE sample_id=?',(source_id,))}
    db.execute('INSERT INTO sample_articles (sample_id,article_id,request_id) SELECT ?,article_id,request_id FROM sample_articles WHERE sample_id=?',(target_id,source_id))
    issue_ids={}
    for row in db.execute('SELECT * FROM sample_issues WHERE sample_id=? ORDER BY rank',(source_id,)).fetchall():
        iid=str(uuid.uuid4());issue_ids[row['issue_id']]=iid
        db.execute('INSERT INTO sample_issues (issue_id,sample_id,article_id,request_id,rank,created_at) VALUES (?,?,?,?,?,?)',
                   (iid,target_id,row['article_id'],row['request_id'],row['rank'],row['created_at']))
    return article_ids,issue_ids
