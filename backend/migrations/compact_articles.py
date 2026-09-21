"""Remove unused image metadata and place summary after the total score."""
from backend.core.paths import BACKEND_DIR


def compact_articles(db):
    columns=[r['name'] for r in db.execute('PRAGMA table_info(articles)')]
    if 'favicon_url' not in columns and columns.index('summary')==columns.index('total_score')+1:return
    schema=(BACKEND_DIR/'newsletter_schema.sql').read_text()
    start=schema.index('CREATE TABLE IF NOT EXISTS articles (')
    ddl=schema[start:schema.index(';',start)+1].replace('IF NOT EXISTS articles','articles_compact')
    db.execute(ddl)
    fields=[r['name'] for r in db.execute('PRAGMA table_info(articles_compact)') if r['name'] in columns]
    names=','.join(fields)
    db.execute(f'INSERT INTO articles_compact ({names}) SELECT {names} FROM articles')
    db.execute('DROP TABLE articles')
    db.execute('ALTER TABLE articles_compact RENAME TO articles')
    db.execute('CREATE INDEX articles_published ON articles(published_at)')
    db.execute('CREATE INDEX articles_request ON articles(request_id)')
