# Blueprint: Веб-приложение с онлайн-продуктом, авторизацией и CRM блогеров

> Этот документ описывает всё, что было построено для проекта **verevery.ru** — онлайн-колода карточек «Ближе» для пар. Используй его как шаблон для запуска следующего похожего проекта.

---

## Оглавление

1. [Структура проекта](#1-структура-проекта)
2. [Технологический стек](#2-технологический-стек)
3. [База данных (SQLite)](#3-база-данных-sqlite)
4. [Авторизация через Magic Link](#4-авторизация-через-magic-link)
5. [Приём оплаты через ЮKassa](#5-приём-оплаты-через-юkassa)
6. [Отправка email через Resend](#6-отправка-email-через-resend)
7. [Главная админка](#7-главная-админка)
8. [CRM блогеров](#8-crm-блогеров)
9. [Переменные окружения](#9-переменные-окружения)
10. [Деплой на REG.RU (ISPmanager)](#10-деплой-на-regru-ispmanager)
11. [Настройка почты на REG.RU](#11-настройка-почты-на-regru)
12. [Настройка Resend (домен и DNS)](#12-настройка-resend-домен-и-dns)
13. [Настройка ЮKassa](#13-настройка-юkassa)
14. [Частые ошибки и решения](#14-частые-ошибки-и-решения)
15. [Чеклист запуска нового проекта](#15-чеклист-запуска-нового-проекта)

---

## 1. Структура проекта

```
project/
├── app/
│   ├── __init__.py          # Фабрика Flask-приложения
│   ├── db.py                # SQLite: init_db(), get_db()
│   ├── routes.py            # Все маршруты (один Blueprint main)
│   ├── data/
│   │   ├── cards_action.json
│   │   ├── cards_question.json
│   │   ├── cards_care.json
│   │   └── free_cards.json  # Список ID бесплатных карточек
│   └── templates/
│       ├── base.html
│       ├── free.html        # Страница с бесплатными карточками
│       ├── buy.html         # Страница покупки
│       ├── buy_success.html
│       ├── cards.html       # Колода (только для оплативших)
│       ├── auth.html        # Magic Link вход
│       ├── offer.html       # Оферта
│       ├── privacy.html     # Политика конфиденциальности
│       ├── admin.html           # Главная админка
│       ├── admin_login.html
│       ├── admin_bloggers.html          # CRM список
│       ├── admin_bloggers_analytics.html
│       └── admin_bloggers_templates.html
├── run.py                   # Точка входа
├── requirements.txt
├── verevery.db              # SQLite файл (создаётся автоматически)
└── seed_bloggers.py         # Скрипт заполнения тестовых данных
```

---

## 2. Технологический стек

| Компонент | Технология |
|-----------|----------|
| Backend | Python 3.11, Flask 3.0, Blueprint |
| База данных | SQLite (встроенный `sqlite3`, `row_factory = sqlite3.Row`) |
| Веб-сервер | Gunicorn |
| Email | Resend (Python SDK `resend==2.10.0`) |
| Оплата | ЮKassa (`yookassa==3.1.0`) |
| AI для CRM | Anthropic Claude Haiku (`anthropic==0.40.0`) |
| Хостинг | REG.RU, ISPmanager, Python-хостинг |
| CI/CD | GitHub Actions → деплой на сервер |

---

## 3. База данных (SQLite)

Файл: `app/db.py`

### Подключение

```python
import sqlite3
import os

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'verevery.db'))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # строки как dict-like объекты
    return conn
```

### Таблицы

```sql
-- Пользователи (купившие или получившие доступ вручную)
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT DEFAULT '',  -- не используется, нужен для NOT NULL
    has_access INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Токены для Magic Link
CREATE TABLE magic_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TEXT NOT NULL,   -- ISO-формат, 24 часа
    used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Продажи (заполняется webhook'ом от ЮKassa)
CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT UNIQUE,
    date TEXT,
    email TEXT,
    utm TEXT,          -- UTM метка (slug блогера или 'direct')
    blogger TEXT,      -- копия utm, если не пустой
    amount REAL,
    commission REAL,   -- 30% от amount
    created_at TEXT DEFAULT (datetime('now'))
);

-- Блогеры (CRM)
CREATE TABLE bloggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    platform TEXT DEFAULT '',
    profile_url TEXT DEFAULT '',
    email TEXT DEFAULT '',
    utm_slug TEXT DEFAULT '',
    utm_link TEXT DEFAULT '',      -- BASE_URL/free?utm=SLUG
    status TEXT DEFAULT 'new',     -- new/sent/replied/interested/agreed/posted/declined
    first_email_sent_at TEXT,      -- ISO datetime
    last_reply_at TEXT,
    reply_sentiment TEXT,          -- positive/negative/question (от Claude)
    sales_count INTEGER DEFAULT 0,
    paid_out INTEGER DEFAULT 0,    -- выплаченная комиссия в рублях
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Лог отправленных и входящих писем
CREATE TABLE email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blogger_id INTEGER,
    type TEXT NOT NULL,       -- first/second/inbound
    sent_at TEXT NOT NULL,
    status TEXT DEFAULT 'ok', -- ok/error/positive/negative/question
    error TEXT DEFAULT ''
);

-- Шаблоны писем для блогеров
CREATE TABLE email_templates (
    key TEXT PRIMARY KEY,     -- blogger_first / blogger_second
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL   -- поддерживает {name} и {utm_link}
);

-- Обращения в поддержку (с лендинга при проблеме со входом)
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved INTEGER DEFAULT 0
);
```

### ВАЖНО: sqlite3.Row НЕ поддерживает `.get()`

```python
# ПРАВИЛЬНО:
value = row['column_name']
value = row['column_name'] or 'default'

# НЕПРАВИЛЬНО (вызовет AttributeError):
value = row.get('column_name', 'default')

# Если нужно передать в функцию как dict:
blogger_dict = dict(row)
```

---

## 4. Авторизация через Magic Link

### Как работает

1. Пользователь вводит email → нажимает «Войти»
2. Бэкенд создаёт одноразовый токен (32 байта), сохраняет в `magic_tokens` с TTL 24 часа
3. Resend отправляет письмо со ссылкой `BASE_URL/auth/verify?token=TOKEN`
4. Пользователь кликает → Flask проверяет токен → создаёт сессию

### Маршруты

| Маршрут | Метод | Описание |
|---------|-------|----------|
| `/auth` | GET/POST | Форма ввода email |
| `/auth/verify` | GET | Проверка токена, показ кнопки «Открыть» |
| `/auth/open` | GET | Финальный вход, создание сессии |
| `/auth/report` | POST | Отправка обращения в поддержку |
| `/logout` | GET | Выход |

### Ключевой код

```python
def _send_magic_link(email, conn):
    import resend
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    conn.execute('DELETE FROM magic_tokens WHERE email=?', (email,))
    conn.execute(
        'INSERT INTO magic_tokens (token, email, expires_at) VALUES (?, ?, ?)',
        (token, email, expires_at)
    )
    conn.commit()
    link = f'{BASE_URL}/auth/verify?token={token}'
    resend.api_key = os.environ.get('RESEND_API_KEY', '')
    resend.Emails.send({
        'from': 'Ближе <noreply@YOURDOMAIN.ru>',
        'to': [email],
        'subject': 'Ваша ссылка для входа',
        'html': _magic_link_email(link),
    })
```

---

## 5. Приём оплаты через ЮKassa

### Схема платежа

```
Пользователь → /pay (POST) → ЮKassa API → redirect на страницу оплаты
                                                      ↓ оплата прошла
/webhook/payment (POST) ← ЮKassa webhook ←──────────┘
         ↓
  1. Создать/обновить пользователя (has_access=1)
  2. Сохранить продажу в sales
  3. Отправить Magic Link на email
```

### Настройка ЮKassa

1. Зарегистрироваться на yookassa.ru
2. Создать магазин → получить `shop_id` и `secret_key`
3. В настройках магазина добавить webhook URL: `https://YOURDOMAIN.ru/webhook/payment`
4. Событие: `payment.succeeded`

### Переменные

```
SHOP_ID=1234567
YUKASSA_SECRET_KEY=test_abc123...
```

### Код платежа (с чеком и без — fallback)

```python
@main.route('/pay', methods=['POST'])
def pay():
    from yookassa import Payment as YooPayment
    email = request.form.get('email', '').strip().lower()
    utm = request.form.get('utm', 'direct')
    _configure_yookassa()
    base_params = {
        'amount': {'value': '690.00', 'currency': 'RUB'},
        'confirmation': {'type': 'redirect', 'return_url': f'{BASE_URL}/buy/success'},
        'capture': True,
        'description': 'Название продукта',
        'metadata': {'email': email, 'utm': utm},
    }
    # Пробуем с чеком (нужен для ФЗ-54)
    try:
        payment = YooPayment.create({**base_params, 'receipt': {...}}, str(uuid.uuid4()))
        return redirect(payment.confirmation.confirmation_url)
    except Exception:
        pass
    # Fallback без чека
    payment = YooPayment.create(base_params, str(uuid.uuid4()))
    return redirect(payment.confirmation.confirmation_url)
```

---

## 6. Отправка email через Resend

### Установка

```bash
pip install resend==2.10.0
```

### Базовая отправка

```python
import resend
resend.api_key = os.environ.get('RESEND_API_KEY', '')
resend.Emails.send({
    'from': 'Имя Отправителя <noreply@YOURDOMAIN.ru>',
    'reply_to': ['reply@YOURDOMAIN.ru'],
    'to': ['recipient@example.com'],
    'subject': 'Тема письма',
    'html': '<p>HTML содержимое</p>',
})
```

### Адреса для проекта

| Адрес | Назначение |
|-------|----------|
| `noreply@domain.ru` | Автоматические письма (Magic Link) |
| `team@domain.ru` | Письма блогерам (от имени команды) |
| `reply@domain.ru` | Reply-To — куда приходят ответы блогеров |

### Шаблоны писем для блогеров

Шаблоны хранятся в БД (таблица `email_templates`) и поддерживают плейсхолдеры:
- `{name}` — имя блогера (из поля name в CRM)
- `{utm_link}` — персональная ссылка блогера

```python
def _render_email_html(body_text, name, utm_link=''):
    text = body_text.replace('{name}', name).replace('{utm_link}', utm_link)
    # ... рендер в HTML с фирменным стилем
```

---

## 7. Главная админка

URL: `/admin` (пароль из `ADMIN_PASSWORD`)

### Вкладки

| Вкладка | Что показывает |
|---------|---------------|
| Пользователи | Все юзеры, поиск, выдача доступа вручную, отправка Magic Link |
| Продажи | Таблица всех покупок, удаление тестовых |
| Блогеры-партнёры | Статистика по UTM, выручка, комиссия |
| Карточки | Редактор контента карточек (все поля) |
| Бесплатные | Выбор 5 карточек для бесплатной превью-страницы |
| Обращения | Заявки в поддержку с формы /auth при проблемах со входом |

### Маршруты

| Маршрут | Метод | Описание |
|---------|-------|----------|
| `/admin/login` | GET/POST | Вход по паролю |
| `/admin` | GET | Дашборд |
| `/admin/grant` | POST | Выдать доступ + отправить Magic Link |
| `/admin/resolve-report` | POST | Пометить обращение как решённое |
| `/admin/delete-sales` | POST | Удалить продажи (по ID через запятую) |
| `/admin/save` | POST | Сохранить карточку |
| `/admin/free-cards` | POST | Обновить список бесплатных карточек |

---

## 8. CRM блогеров

URL: `/admin/bloggers`

### Статусы

```python
BLOGGER_STATUSES = [
    ('new',        'Новый',        '#8C7E72', '#F5F0EB'),
    ('sent',       'Отправлено',   '#1a6fa6', '#e8f4fd'),
    ('replied',    'Ответил',      '#a67c00', '#fff8e1'),
    ('interested', 'Интересно',    '#2e7d32', '#e8f5e9'),
    ('agreed',     'Сотрудничаем', '#1565c0', '#e3f2fd'),
    ('posted',     'Опубликовал',  '#1b5e20', '#c8e6c9'),
    ('declined',   'Отказал',      '#c0392b', '#fbe9e7'),
]
```

### Воронка работы с блогером

```
new → [Отправить письмо 1] → sent
sent → [блогер ответил] → replied или interested или declined
interested → [Отправить письмо 2] → agreed
agreed → [опубликовал] → posted
```

### Ключевые функции

**UTM-ссылка** генерируется автоматически при добавлении блогера:
```
https://YOURDOMAIN.ru/free?utm=BLOGGER_SLUG
```

**Письмо 1** — первичное предложение сотрудничества  
**Письмо 2** — детали сотрудничества + персональная ссылка

**Комиссия** — 30% от цены продукта. При цене 690 ₽ = 207 ₽ за продажу.

**Предупреждение ⏰** — появляется, если прошло 3+ дня после отправки письма, а ответа нет.

### Автоматика через webhook (если настроен Resend Inbound)

```
reply@domain.ru получает ответ блогера
         ↓
Resend Inbound → POST /webhook/email-reply
         ↓
Claude Haiku классифицирует: positive / negative / question
         ↓
positive → статус "Интересно" → автоматически отправляет письмо 2
negative → статус "Отказал" → уведомление тебе
question → статус "Ответил" → черновик ответа от Claude → уведомление тебе
```

Если Resend Inbound не настроен — ответы читаешь в почте вручную, статус меняешь через карандаш ✏️.

### Маршруты CRM

| Маршрут | Метод | Описание |
|---------|-------|----------|
| `/admin/bloggers` | GET | Список с фильтрами |
| `/admin/bloggers/add` | POST | Добавить блогера |
| `/admin/bloggers/<id>/update` | POST | Редактировать |
| `/admin/bloggers/<id>/delete` | POST | Удалить |
| `/admin/bloggers/<id>/send-email` | POST | Отправить письмо (param: type=first/second) |
| `/admin/bloggers/send-bulk` | POST | Массовая рассылка (param: ids=1,2,3) |
| `/admin/bloggers/analytics` | GET | Аналитика и воронка |
| `/admin/bloggers/templates` | GET | Просмотр шаблонов |
| `/admin/bloggers/templates/save` | POST | Сохранить шаблон |
| `/webhook/email-reply` | POST | Входящий ответ блогера |

---

## 9. Переменные окружения

Создай файл `.env` или укажи в настройках хостинга:

```env
# Flask
SECRET_KEY=случайная-строка-32-символа

# База данных
DB_PATH=/path/to/verevery.db

# URL сайта
BASE_URL=https://yourdomain.ru

# Админка
ADMIN_PASSWORD=твой-пароль-для-входа-в-админку

# ЮKassa
SHOP_ID=1234567
YUKASSA_SECRET_KEY=live_abc123...

# Resend (email)
RESEND_API_KEY=re_abc123...

# Anthropic (для классификации ответов блогеров)
ANTHROPIC_API_KEY=sk-ant-abc123...

# Уведомления о действиях блогеров
ADMIN_NOTIFY_EMAIL=katya@yourdomain.ru

# Безопасность webhook
WEBHOOK_SECRET=случайная-строка
```

---

## 10. Деплой на REG.RU (ISPmanager)

### Структура Python-хостинга REG.RU

- Хостинг: REG.RU, тариф с Python
- Панель управления: ISPmanager на `server199.hosting.reg.ru:1500/`
- Python-приложение работает через systemd/supervisor
- GitHub Actions автоматически деплоит при push в `main`

### Файл `run.py`

```python
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
```

### `requirements.txt`

```
Flask==3.0.3
gunicorn==22.0.0
requests==2.32.3
resend==2.10.0
yookassa==3.1.0
anthropy==0.40.0
```

### GitHub Actions (`.github/workflows/deploy.yml`)

Настроить секреты в GitHub → Settings → Secrets:
- `SSH_HOST` — IP сервера
- `SSH_USER` — логин
- `SSH_KEY` — приватный ключ

---

## 11. Настройка почты на REG.RU

### Создание почтовых ящиков через ISPmanager

1. Войти в ISPmanager: `server199.hosting.reg.ru:1500/`
2. **Почта → Почтовые домены** → Добавить домен (yourdomain.ru)
3. **Почта → Почтовые ящики** → Создать ящики:
   - `noreply@yourdomain.ru` — для автоматических писем
   - `team@yourdomain.ru` — от имени команды
   - `reply@yourdomain.ru` — для получения ответов от блогеров

### Пересылка на Gmail

В настройках ящика `reply@yourdomain.ru` указать «Копия писем на:» → `youremail@gmail.com`

### DNS-записи для почты

В DNS домена должны быть:
```
MX  @   mail.yourdomain.ru   10
A   mail   IP_СЕРВЕРА
```

---

## 12. Настройка Resend (домен и DNS)

### Шаги

1. Зарегистрироваться на resend.com
2. **Domains → Add Domain** → ввести yourdomain.ru
3. Resend выдаст DNS-записи — добавить их в DNS домена (у регистратора или в REG.RU):

```
TXT   resend._domainkey   v=DKIM1; k=rsa; p=MIIBIjAN...
TXT   @                   v=spf1 include:amazonses.com ~all
CNAME resend               (обычно не нужен, см. в панели)
```

4. Дождаться верификации (обычно 5-30 минут)
5. Скопировать API Key: **API Keys → Create API Key**

### Проверка

Нажать «Send test email» в панели Resend — письмо должно дойти без попадания в спам.

---

## 13. Настройка ЮKassa

### Шаги

1. Зарегистрироваться на yookassa.ru (нужна организация или ИП)
2. Создать магазин → получить `shopId` и `secretKey`
3. **Настройки → HTTP-уведомления** → добавить URL:
   ```
   https://yourdomain.ru/webhook/payment
   ```
   Событие: `payment.succeeded`
4. Включить «Автоприём платежей» (capture=true)
5. Для чеков (ФЗ-54): подключить ОФД в настройках

### Тестирование

В личном кабинете есть тестовые карты для проверки платежей без реальных денег.

---

## 14. Частые ошибки и решения

### `AttributeError: 'sqlite3.Row' object has no attribute 'get'`

```python
# ПРИЧИНА: sqlite3.Row не поддерживает .get()
# РЕШЕНИЕ: везде, где нужен .get(), сначала сконвертируй в dict

blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (bid,)).fetchone()
blogger = dict(blogger)  # ← добавить эту строку
# теперь можно: blogger.get('utm_link', '')
```

Или конвертировать сразу при извлечении списка:
```python
rows = [dict(r) for r in conn.execute(query, params).fetchall()]
```

### `{{ b|tojson }}` в шаблоне не работает / экранирует кавычки

```jinja2
{# НЕПРАВИЛЬНО — двойные кавычки внутри onclick ломают HTML: #}
<button onclick="openEditModal({{ b.id }}, {{ b|tojson }})">

{# ПРАВИЛЬНО — одинарные кавычки снаружи: #}
<button onclick='openEditModal({{ b.id }}, {{ b|tojson }})'>
```

При этом `b` должен быть `dict`, а не `sqlite3.Row`:
```python
bloggers_rows = [dict(r) for r in conn.execute(query).fetchall()]
```

### 500 при отправке email блогеру

Проверить:
1. Поле `RESEND_API_KEY` заполнено в переменных окружения
2. Домен верифицирован в Resend
3. Поле `email` у блогера заполнено
4. `blogger` передаётся в `_send_blogger_email()` как `dict`, а не `sqlite3.Row`

### Push в GitHub возвращает 403

Через `git push` в Claude Code — не работает. Использовать MCP tool `mcp__github__push_files`.

После каждого push через MCP синхронизировать локальную ветку:
```bash
git fetch origin main && git reset --hard origin/main
```

### Сессия пользователя слетает через день

В `app/__init__.py`:
```python
app.permanent_session_lifetime = timedelta(days=30)
```

В маршруте при входе:
```python
session.permanent = True
session['user_id'] = user['id']
```

---

## 15. Чеклист запуска нового проекта

### Первоначальная настройка

- [ ] Зарегистрировать домен на REG.RU
- [ ] Подключить Python-хостинг
- [ ] Создать репозиторий GitHub
- [ ] Настроить GitHub Actions для деплоя

### Email

- [ ] Добавить домен в Resend, добавить DNS-записи
- [ ] Дождаться верификации домена в Resend
- [ ] Создать почтовые ящики в ISPmanager (noreply, team, reply)
- [ ] Настроить пересылку reply@ на личную почту
- [ ] Получить Resend API Key и добавить в переменные окружения

### Оплата

- [ ] Зарегистрироваться в ЮKassa, создать магазин
- [ ] Добавить webhook URL в настройках ЮKassa
- [ ] Получить SHOP_ID и YUKASSA_SECRET_KEY
- [ ] Проверить тестовый платёж

### Переменные окружения

- [ ] `SECRET_KEY` — случайная строка
- [ ] `BASE_URL` — финальный URL с https
- [ ] `ADMIN_PASSWORD` — надёжный пароль
- [ ] `RESEND_API_KEY`
- [ ] `SHOP_ID` + `YUKASSA_SECRET_KEY`
- [ ] `ANTHROPIC_API_KEY` (если нужна AI-классификация)
- [ ] `ADMIN_NOTIFY_EMAIL`
- [ ] `WEBHOOK_SECRET`

### Контент

- [ ] Заполнить карточки в JSON-файлах (cards_action.json и др.)
- [ ] Настроить шаблоны писем в `/admin/bloggers/templates`
- [ ] Выбрать 5 бесплатных карточек в `/admin` → Бесплатные
- [ ] Заполнить Оферту и Политику конфиденциальности

### CRM

- [ ] Добавить первых блогеров вручную или через `seed_bloggers.py`
- [ ] Проверить отправку письма: `/admin/bloggers` → найти блогера с email → Отправить
- [ ] Проверить, что письмо пришло без попадания в спам

### Финальная проверка

- [ ] Купить продукт тестовой картой ЮKassa
- [ ] Получить Magic Link на email
- [ ] Открыть колоду по ссылке
- [ ] Зайти в `/admin` и увидеть покупку в разделе Продажи

---

## Примечания по архитектуре

### Почему один файл routes.py

Всё в одном Blueprint (`main`) — проще поддерживать для небольшого проекта. Если функций станет много — разбить на Blueprint-ы: `auth`, `admin`, `crm`.

### Почему SQLite, а не PostgreSQL

Для нагрузки 100-500 покупателей SQLite достаточно и не требует отдельного сервера. При росте до тысяч активных пользователей — мигрировать на PostgreSQL, заменив `sqlite3` на `psycopg2` и адаптировав синтаксис запросов.

### Почему Magic Link, а не пароль

Проще для пользователя: не нужно помнить пароль. Подходит для продуктов, куда заходят 1-2 раза в месяц. Для частого использования рассмотреть добавление пароля или OAuth (Google).

---

*Документ создан по результатам разработки verevery.ru — онлайн-колода «Ближе» для пар.*
