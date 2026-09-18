"""Migrate accumulated raw subscription articles to the compact schema."""
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def migrate_subscription_articles(db):
    columns={r['name'] for r in db.execute('PRAGMA table_info(subscripted_articles)')}
    if 'canonical_url' not in columns:
        return
    schema=Path(__file__).with_name('newsletter_schema.sql').read_text()
    start=schema.index('CREATE TABLE IF NOT EXISTS subscripted_articles (')
    ddl=schema[start:schema.index(';',start)+1].replace('IF NOT EXISTS subscripted_articles','subscripted_articles_replacement')
    db.execute(ddl)
    for row in db.execute('SELECT * FROM subscripted_articles').fetchall():
        url=row['canonical_url'].strip()
        parsed=urlsplit(url)
        host=(parsed.hostname or '').lower().removeprefix('www.')
        if parsed.scheme not in ('http','https') or not host:
            raise ValueError('Cannot migrate subscription article with invalid canonical URL')
        domain=db.execute('SELECT domain_id FROM domains WHERE host=?',(host,)).fetchone()
        did=domain[0] if domain else str(uuid.uuid4())
        if not domain:
            db.execute('INSERT INTO domains (domain_id,host,created_at) VALUES (?,?,?)',(did,host,row['collected_at']))
        db.execute('INSERT INTO subscripted_articles_replacement VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (row['article_id'],row['sample_id'],did,None,url,row['title'],row['published_at'],
                    row['content'],row['image_url'],row['favicon_url'],row['image_storage_path'],row['collected_at']))
    db.execute('DROP TABLE subscripted_articles')
    db.execute('ALTER TABLE subscripted_articles_replacement RENAME TO subscripted_articles')
    db.execute('CREATE INDEX subscripted_articles_period ON subscripted_articles(sample_id,published_at)')
    db.execute('CREATE INDEX subscripted_articles_collected ON subscripted_articles(sample_id,collected_at)')
