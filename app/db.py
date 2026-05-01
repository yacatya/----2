import sqlite3
import os

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'verevery.db'))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            has_access INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS magic_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    ''')
    # Migrations: add columns that may be missing in older DBs
    for col, definition in [
        ('has_access', 'INTEGER DEFAULT 0'),
        ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ]:
        try:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {definition}')
        except Exception:
            pass
    conn.commit()
    conn.close()
