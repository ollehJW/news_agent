"""Migrate legacy email lists into typed subscription recipients."""
import json
import uuid


def migrate_subscription_members(db):
    db.execute("""CREATE TABLE IF NOT EXISTS subscription_members (
        member_id TEXT PRIMARY KEY,
        subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id) ON DELETE CASCADE,
        member_type TEXT NOT NULL CHECK(member_type IN ('internal','external')),
        user_id TEXT REFERENCES users(user_id) ON DELETE RESTRICT,
        email_address TEXT COLLATE NOCASE,
        created_at TEXT NOT NULL,
        CHECK((member_type='internal' AND user_id IS NOT NULL AND length(trim(user_id))>0 AND email_address IS NULL)
           OR (member_type='external' AND user_id IS NULL AND email_address IS NOT NULL AND length(trim(email_address))>0))
    )""")
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS subscription_member_user ON subscription_members(subscription_id,user_id) WHERE user_id IS NOT NULL')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS subscription_member_email ON subscription_members(subscription_id,email_address) WHERE email_address IS NOT NULL')
    db.execute('CREATE INDEX IF NOT EXISTS subscription_member_lookup ON subscription_members(user_id,subscription_id)')
    if 'email_addresses' in {r['name'] for r in db.execute('PRAGMA table_info(subscriptions)')}:
        for row in db.execute('SELECT subscription_id,email_addresses,created_at FROM subscriptions').fetchall():
            for email in set(e.strip().lower() for e in json.loads(row['email_addresses']) if e.strip()):
                users=db.execute("SELECT user_id FROM users WHERE lower(trim(email))=? AND is_admin=0",(email,)).fetchall()
                # Ambiguous or unregistered addresses remain email-only; never grant an arbitrary account access.
                uid=users[0]['user_id'] if len(users)==1 else None
                db.execute('INSERT OR IGNORE INTO subscription_members(member_id,subscription_id,member_type,user_id,email_address,created_at) VALUES(?,?,?,?,?,?)',
                    (str(uuid.uuid4()),row['subscription_id'],'internal' if uid else 'external',uid,None if uid else email,row['created_at']))
        db.execute('ALTER TABLE subscriptions DROP COLUMN email_addresses')

    if 'status' not in {r['name'] for r in db.execute('PRAGMA table_info(subscription_members)')}:
        db.execute("ALTER TABLE subscription_members ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused'))")
        db.execute("UPDATE subscription_members SET status='paused' WHERE subscription_id IN (SELECT subscription_id FROM subscriptions WHERE status='paused')")
        db.execute("UPDATE subscriptions SET status='active' WHERE status='paused'")
