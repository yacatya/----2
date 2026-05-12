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
        CREATE TABLE IF NOT EXISTS email_templates (
            key TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            body_text TEXT NOT NULL
        );
    ''')
    default_templates = [
        (
            'blogger_first',
            'Сотрудничество — колода карточек «Ближе» для пар',
            'Привет, {name}! \U0001f44b\n\nМеня зовут Катя, я создала Vera — онлайн-колоду карточек «Ближе» для пар на verevery.ru.\n\nКарточки помогают восстановить близость в отношениях — основаны на доказательной психологии (Готтман, EFT, теория привязанности). Цена: 690 ₽.\n\nХочу предложить сотрудничество: вы рассказываете аудитории о проекте, получаете 30% с каждой продажи по вашей ссылке — 207 ₽ за покупку.\n\nЕсли интересно — напишу подробнее об условиях \U0001f64c\n\nКатя\nverevery.ru',
        ),
        (
            'blogger_second',
            'Re: Сотрудничество — колода карточек «Ближе» для пар',
            'Привет, {name}! Рада, что откликнулись \U0001f49b\n\nВот подробности о сотрудничестве:\n\n\U0001f4e6 Продукт: онлайн-колода «Ближе» — 60 карточек для пар (verevery.ru)\n\U0001f4b8 Комиссия: 30% = 207 ₽ с каждой продажи\n\U0001f517 Ваша ссылка: {utm_link}\n\nКак это работает:\n1. Вы публикуете пост или сторис со своей ссылкой\n2. Подписчики переходят и покупают\n3. Я считаю продажи по вашему UTM и перевожу комиссию раз в месяц\n\nМогу прислать описание продукта и примеры карточек — всё что нужно для публикации.\n\nГотова ответить на любые вопросы!\n\nКатя\nverevery.ru',
        ),
    ]
    for key, subject, body_text in default_templates:
        try:
            conn.execute(
                'INSERT OR IGNORE INTO email_templates (key, subject, body_text) VALUES (?, ?, ?)',
                (key, subject, body_text)
            )
        except Exception:
            pass
    for col, definition in [
        ('has_access', 'INTEGER DEFAULT 0'),
        ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ]:
        try:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {definition}')
        except Exception:
            pass
    for col, definition in [
        ('channel',     "TEXT DEFAULT 'email'"),
        ('ig_username', "TEXT DEFAULT ''"),
        ('tg_username', "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f'ALTER TABLE bloggers ADD COLUMN {col} {definition}')
        except Exception:
            pass
    conn.commit()
    conn.close()
