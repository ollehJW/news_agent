"""Migrate legacy editions into shared sample-period editions."""
from backend.core.paths import BACKEND_DIR
import json
import uuid


LEGACY_EDITION_SCHEMA = "-- Actual subscription editions are shared outputs, independent of sample ownership.\nCREATE TABLE IF NOT EXISTS newsletters (\n newsletter_id TEXT PRIMARY KEY,\n title TEXT NOT NULL, html_content TEXT NOT NULL, template_version TEXT NOT NULL,\n content_hash TEXT NOT NULL, issue_count INTEGER NOT NULL CHECK(issue_count>=0),\n snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS newsletter_publications (\n publication_id TEXT PRIMARY KEY,\n sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE RESTRICT,\n coverage_start TEXT NOT NULL, coverage_end TEXT NOT NULL CHECK(coverage_end>=coverage_start),\n newsletter_id TEXT UNIQUE REFERENCES newsletters(newsletter_id) ON DELETE SET NULL,\n selected_article_ids TEXT NOT NULL DEFAULT '[]'\n   CHECK(json_valid(selected_article_ids) AND json_type(selected_article_ids)='array'),\n status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','completed','failed')),\n published_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,\n UNIQUE(sample_id,coverage_start,coverage_end)\n);\nCREATE INDEX IF NOT EXISTS publications_status ON newsletter_publications(status,created_at);\n\n\n"


def create_legacy_edition_tables(db):
    # Used only while upgrading the former combined sample/publication schema.
    import sqlite3
    statement = ''
    for line in LEGACY_EDITION_SCHEMA.splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ''


def migrate_subscription_newsletters(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    migrated = set()
    if 'newsletter_publications' in tables:
        for publication in db.execute('SELECT * FROM newsletter_publications').fetchall():
            edition = db.execute('SELECT * FROM newsletters WHERE newsletter_id=?', (publication['newsletter_id'],)).fetchone()
            subscriptions = db.execute('SELECT subscription_id FROM subscriptions WHERE sample_id=? ORDER BY subscription_id', (publication['sample_id'],)).fetchall()
            if not edition or not subscriptions:
                raise RuntimeError('Cannot migrate a legacy publication without an edition and subscription')
            issue_ids = []
            for article_id in json.loads(publication['selected_article_ids']):
                article = db.execute('SELECT sample_id FROM subscripted_articles WHERE article_id=?', (article_id,)).fetchone()
                if not article or article['sample_id'] != publication['sample_id']:
                    raise RuntimeError('Legacy publication contains an invalid source article')
                iid = str(uuid.uuid4())
                db.execute('INSERT INTO subscripted_issues (issue_id,subscription_id,article_id,created_at,rank) VALUES (?,?,?,?,?)',
                           (iid,subscriptions[0]['subscription_id'],article_id,publication['created_at'],len(issue_ids)+1))
                issue_ids.append(iid)
            db.execute("""INSERT INTO subscripted_newsletters
                (newsletter_id,sample_id,coverage_start_date,coverage_end_date,issue_ids,html_content,created_at,published_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (edition['newsletter_id'],publication['sample_id'],publication['coverage_start'],publication['coverage_end'],json.dumps(issue_ids),
                 edition['html_content'],edition['created_at'],publication['published_at']))
            for subscription in subscriptions:
                db.execute('INSERT INTO subscription_history (subscription_id,newsletter_id,created_at) VALUES (?,?,?)',
                           (subscription['subscription_id'],edition['newsletter_id'],publication['created_at']))
            migrated.add(edition['newsletter_id'])
    if 'newsletters' in tables:
        existing = {r[0] for r in db.execute('SELECT newsletter_id FROM newsletters')}
        if existing != migrated:
            raise RuntimeError('Cannot discard legacy editions without a subscription publication link')
    references = [r for r in db.execute('PRAGMA foreign_key_list(sample_newsletters)') if r['from']=='last_issued_newsletter_id']
    if references and references[0]['table'] != 'subscripted_newsletters':
        db.execute('ALTER TABLE sample_newsletters DROP COLUMN last_issued_newsletter_id')
        db.execute('ALTER TABLE sample_newsletters ADD COLUMN last_issued_newsletter_id TEXT REFERENCES subscripted_newsletters(newsletter_id) ON DELETE SET NULL')
    if 'newsletters' in tables or 'newsletter_publications' in tables:
        db.execute("""UPDATE sample_newsletters SET last_issued_newsletter_id=(
            SELECT n.newsletter_id FROM subscripted_newsletters n
            WHERE n.sample_id=sample_newsletters.sample_id AND n.published_at IS NOT NULL
            ORDER BY n.published_at DESC,n.created_at DESC,n.newsletter_id DESC LIMIT 1)""")
    db.execute('DROP TABLE IF EXISTS newsletter_publications')
    db.execute('DROP TABLE IF EXISTS newsletters')


def migrate_shared_newsletters(db):
    """Preserve subscription associations when removing edition.subscription_id."""
    if 'subscription_id' not in {r['name'] for r in db.execute('PRAGMA table_info(subscripted_newsletters)')}:
        return
        schema = (BACKEND_DIR / 'newsletter_schema.sql').read_text()
    start = schema.index('CREATE TABLE IF NOT EXISTS subscripted_newsletters (')
    ddl = schema[start:schema.index(';',start)+1]
    db.execute(ddl.replace('IF NOT EXISTS subscripted_newsletters','subscripted_newsletters_replacement'))
    start = schema.index('CREATE TABLE IF NOT EXISTS subscription_history (')
    db.execute(schema[start:schema.index(';',start)+1])
    rows = db.execute("""SELECT n.*,s.sample_id FROM subscripted_newsletters n
        JOIN subscriptions s USING(subscription_id) ORDER BY n.created_at,n.newsletter_id""").fetchall()
    if len(rows) != db.execute('SELECT count(*) FROM subscripted_newsletters').fetchone()[0]:
        raise RuntimeError('Edition has no subscription to resolve its sample')
    groups = {}
    for row in rows:
        key = (row['sample_id'],row['coverage_start_date'],row['coverage_end_date'])
        previous = groups.get(key)
        if previous:
            # Different historical content cannot be silently discarded.
            if any(row[k] != previous[k] for k in ('html_content','summary','issue_ids','request_id','published_at')):
                raise RuntimeError('Conflicting editions share the same sample and period; resolve before migration')
            nid = previous['newsletter_id']
        else:
            groups[key] = row
            nid = row['newsletter_id']
            db.execute("""INSERT INTO subscripted_newsletters_replacement
                (newsletter_id,sample_id,coverage_start_date,coverage_end_date,issue_ids,summary,request_id,html_content,created_at,published_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", tuple(row[k] for k in
                ('newsletter_id','sample_id','coverage_start_date','coverage_end_date','issue_ids','summary','request_id','html_content','created_at','published_at')))
        db.execute('INSERT INTO subscription_history (subscription_id,newsletter_id,created_at) VALUES (?,?,?)',
                   (row['subscription_id'],nid,row['created_at']))
        db.execute('UPDATE sample_newsletters SET last_issued_newsletter_id=? WHERE last_issued_newsletter_id=?',
                   (nid,row['newsletter_id']))
    db.execute('DROP TABLE subscripted_newsletters')
    db.execute('ALTER TABLE subscripted_newsletters_replacement RENAME TO subscripted_newsletters')
