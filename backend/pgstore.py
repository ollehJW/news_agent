"""PostgreSQL-only storage with YAML configuration and bound qmark parameters."""
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
import os
import re
import psycopg
import yaml

ROOT = Path(__file__).resolve().parents[1]


def settings():
    config = yaml.safe_load(Path(os.environ.get('AX_SERVICE_CONFIG', ROOT / 'config.yaml')).read_text())
    db = config['database']
    if db['schema'] != SERVICE or db.get('account_schema', 'platform') != 'platform':
        raise ValueError('Service and account schemas must remain unchanged')
    return config


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, (v.isoformat() if isinstance(v, (datetime, date)) else v for v in values)))


def parameters(query):
    # Convert only binding markers. Values are always sent separately to psycopg.
    pieces = re.split(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")", query)
    return ''.join(part.replace('%', '%%').replace('?', '%s') if i % 2 == 0 else part.replace('%', '%%') for i, part in enumerate(pieces))


class Connection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, query, args=None):
        return self.raw.execute(parameters(query) if args else query, args or None)

    def executemany(self, query, args):
        return self.raw.cursor().executemany(parameters(query), args)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


@contextmanager
def database():
    db = settings()['database']
    password = os.environ[db['password_env']] if db.get('password_env') else db.get('password', '')
    with psycopg.connect(host=db['host'], port=db.get('port', 5432), dbname=db['name'],
                        user=db['user'], password=password, sslmode=db.get('sslmode', 'prefer'),
                        connect_timeout=5, application_name=SERVICE,
                        options=f'-c search_path={SERVICE},platform,pg_catalog -c timezone=UTC -c statement_timeout=30000',
                        row_factory=row_factory) as conn:
        yield Connection(conn)


def initialize():
    # PostgreSQL schema is installed by the explicit migration, never legacy SQLite migrations.
    with database() as db:
        db.execute('SELECT 1 FROM platform.users LIMIT 1')
        db.execute('SELECT 1 FROM ' + SERVICE + '.' + HEALTH_TABLE + ' LIMIT 1')

SERVICE = 'wianews'
HEALTH_TABLE = 'sample_newsletters'
