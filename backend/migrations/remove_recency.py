"""Drop date-based scores and recalculate totals without reevaluating articles."""
from backend.news.scoring_rules import weighted_scores


def remove_recency(db):
    columns={r['name'] for r in db.execute('PRAGMA table_info(articles)')}
    if 'recency_score' not in columns and 'score_date' not in columns:return
    for column in ('recency_score','score_date'):
        if column in columns:db.execute(f'ALTER TABLE articles DROP COLUMN {column}')
    for row in db.execute('SELECT * FROM articles').fetchall():
        db.execute('UPDATE articles SET total_score=? WHERE article_id=?',(weighted_scores(dict(row))['total_score'],row['article_id']))
