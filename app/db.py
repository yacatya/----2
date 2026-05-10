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
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE,
            date TEXT,
            email TEXT,
            utm TEXT,
            blogger TEXT,
            amount REAL,
            commission REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS bloggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            platform TEXT DEFAULT '',
            profile_url TEXT DEFAULT '',
            email TEXT DEFAULT '',
            utm_slug TEXT DEFAULT '',
            utm_link TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            first_email_sent_at TEXT,
            last_reply_at TEXT,
            reply_sentiment TEXT,
            sales_count INTEGER DEFAULT 0,
            paid_out INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blogger_id INTEGER,
            type TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            status TEXT DEFAULT 'ok',
            error TEXT DEFAULT ''
        );
    ''')
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
