import hashlib
import hmac
import json
import logging
import os
import re as _re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, redirect, url_for, session, request

main = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BASE_URL = os.environ.get('BASE_URL', 'https://verevery.ru')
SHOP_ID = os.environ.get('SHOP_ID', '1343976')
SHEET_ID = '11mZ-sB0H7OiaF9yv2iCiTlA3vkMJW8u9D9ypuf4QeAs'
REPLY_TO_EMAIL = os.environ.get('REPLY_TO_EMAIL', 'team.verevery@gmail.com')

FREE_CARD_IDS_DEFAULT = ['А-02', 'З-03', 'В-03', 'В-11', 'З-01']
FREE_CARDS_CONFIG = os.path.join(os.path.dirname(__file__), 'data', 'free_cards.json')


def get_free_card_ids():
    try:
        with open(FREE_CARDS_CONFIG, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return FREE_CARD_IDS_DEFAULT


def save_free_card_ids(ids):
    with open(FREE_CARDS_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(ids, f, ensure_ascii=False)

BLOCK_INFO = {
    'action':   {'label': 'ДЕЙСТВИЕ', 'color': 'var(--accent)',       'name': 'Действие'},
    'question': {'label': 'ВОПРОС',   'color': 'var(--muted)',        'name': 'Вопрос'},
    'care':     {'label': 'ЗАБОТА',   'color': 'var(--light-accent)', 'name': 'Забота'},
}


def load_block(block):
    with open(os.path.join(DATA_DIR, f'cards_{block}.json'), encoding='utf-8') as f:
        return json.load(f)['cards']


def _configure_yookassa():
    from yookassa import Configuration
    Configuration.account_id = SHOP_ID
    Configuration.secret_key = os.environ.get('YUKASSA_SECRET_KEY', '')


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
        'from': 'Ближе <noreply@verevery.ru>',
        'to': [email],
        'subject': 'Ваша ссылка для входа в колоду — verevery.ru',
        'html': _magic_link_email(link),
    })


def _upsert_user(conn, email):
    conn.execute(
        'INSERT OR IGNORE INTO users (email, password_hash) VALUES (?, ?)', (email, '')
    )
    conn.execute('UPDATE users SET has_access=1 WHERE LOWER(email)=?', (email,))
    conn.commit()


def _save_sale(conn, payment_id, date, email, utm, amount):
    try:
        blogger = utm if utm not in ('direct', '', None) else ''
        commission = round(float(amount) * 0.30, 2)
        conn.execute(
            '''INSERT OR IGNORE INTO sales (payment_id, date, email, utm, blogger, amount, commission)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (payment_id, date, email, utm, blogger, float(amount), commission)
        )
        conn.commit()
    except Exception:
        pass


# ── Pages ────────────────────────────────────────────────────────────────────

@main.route('/')
def index():
    return redirect(url_for('main.free'))


@main.route('/free')
def free():
    utm = request.args.get('utm', '').strip()
    if utm and utm not in ('direct', ''):
        try:
            from .db import get_db as _gdb
            _c = _gdb()
            _c.execute('INSERT INTO link_clicks (utm_slug) VALUES (?)', (utm,))
            _c.commit()
            _c.close()
        except Exception:
            pass
    all_cards = {b: load_block(b) for b in BLOCK_INFO}
    id_map = {}
    for block, cards in all_cards.items():
        for c in cards:
            id_map[c['id']] = (block, c)
    free_cards = []
    for cid in get_free_card_ids():
        if cid in id_map:
            block, card = id_map[cid]
            free_cards.append({**card, 'block': block, **BLOCK_INFO[block]})
    return render_template('free.html', cards=free_cards)


@main.route('/buy')
def buy():
    error = request.args.get('error', '')
    return render_template('buy.html', error=error)


@main.route('/pay', methods=['POST'])
def pay():
    from yookassa import Payment as YooPayment
    email = request.form.get('email', '').strip().lower()
    utm = request.form.get('utm', 'direct')

    if not email or '@' not in email or '.' not in email.split('@')[-1]:
        return redirect(url_for('main.buy') + '?error=email')

    _configure_yookassa()
    base_params = {
        'amount': {'value': '690.00', 'currency': 'RUB'},
        'confirmation': {
            'type': 'redirect',
            'return_url': f'{BASE_URL}/buy/success',
        },
        'capture': True,
        'description': 'Колода «Ближе» — постоянный доступ',
        'metadata': {'email': email, 'utm': utm},
    }
    receipt_params = {
        'receipt': {
            'customer': {'email': email},
            'items': [{
                'description': 'Колода «Ближе» — постоянный доступ',
                'quantity': '1.00',
                'amount': {'value': '690.00', 'currency': 'RUB'},
                'vat_code': 1,
                'payment_mode': 'full_payment',
                'payment_subject': 'service',
            }],
        }
    }
    try:
        payment = YooPayment.create({**base_params, **receipt_params}, str(uuid.uuid4()))
        return redirect(payment.confirmation.confirmation_url)
    except Exception:
        pass
    try:
        payment = YooPayment.create(base_params, str(uuid.uuid4()))
        return redirect(payment.confirmation.confirmation_url)
    except Exception as e:
        return redirect(url_for('main.buy') + '?error=' + str(e)[:200])


@main.route('/buy/success')
def buy_success():
    return render_template('buy_success.html')


@main.route('/webhook/payment', methods=['POST'])
def webhook_payment():
    try:
        from yookassa import Payment as YooPayment
        from yookassa.domain.notification import WebhookNotification

        event_json = request.get_json(force=True)
        notification = WebhookNotification(event_json)

        if notification.event != 'payment.succeeded':
            return '', 200

        _configure_yookassa()
        payment = YooPayment.find_one(notification.object.id)

        if payment.status != 'succeeded':
            return '', 200

        email = (payment.metadata or {}).get('email', '').strip().lower()
        utm = (payment.metadata or {}).get('utm', 'direct')
        amount = str(payment.amount.value)
        date = datetime.utcnow().strftime('%d.%m.%Y %H:%M')

        if not email:
            return '', 200

        from .db import get_db
        conn = get_db()

        already_processed = conn.execute(
            'SELECT 1 FROM sales WHERE payment_id=?', (payment.id,)
        ).fetchone()

        _upsert_user(conn, email)
        _save_sale(conn, payment.id, date, email, utm, amount)

        if not already_processed:
            _send_magic_link(email, conn)

        conn.close()

    except Exception:
        pass

    return '', 200


@main.route('/cards')
def cards():
    if 'user_id' not in session:
        return redirect(url_for('main.auth'))
    from .db import get_db
    conn = get_db()
    user = conn.execute(
        'SELECT has_access FROM users WHERE id=?', (session['user_id'],)
    ).fetchone()
    conn.close()
    if not user or not user['has_access']:
        return redirect(url_for('main.buy'))
    blocks = {}
    for block, info in BLOCK_INFO.items():
        blocks[block] = {**info, 'cards': load_block(block)}
    return render_template('cards.html', blocks=blocks, user_email=session.get('email', ''))


@main.route('/auth', methods=['GET', 'POST'])
def auth():
    if 'user_id' in session:
        return redirect(url_for('main.cards'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email or '@' not in email or '.' not in email.split('@')[-1]:
            return render_template('auth.html', error='Введите корректный email')
        from .db import get_db
        conn = get_db()
        conn.execute('INSERT OR IGNORE INTO users (email, password_hash) VALUES (?, ?)', (email, ''))
        conn.commit()
        _send_magic_link(email, conn)
        conn.close()
        return render_template('auth.html', sent=True, email=email)

    return render_template('auth.html')


@main.route('/auth/verify', methods=['GET', 'POST'])
def auth_verify():
    if request.method == 'GET':
        token = request.args.get('token', '')
        if not token:            return redirect(url_for('main.auth'))
        try:
            from .db import get_db
            conn = get_db()
            row = conn.execute(
                'SELECT 1 FROM magic_tokens WHERE token=? AND expires_at > ?',
                (token, datetime.utcnow().isoformat())
            ).fetchone()
            conn.close()
            if not row:
                return render_template('auth.html', token_expired=True)
        except Exception:
            return render_template('auth.html', token_expired=True)
        return render_template('auth.html', confirm_token=token)

    return redirect(url_for('main.auth'))


@main.route('/auth/open')
def auth_open():
    token = request.args.get('token', '')
    if not token:
        return redirect(url_for('main.auth'))
    try:
        from .db import get_db
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM magic_tokens WHERE token=? AND expires_at > ?',
            (token, datetime.utcnow().isoformat())
        ).fetchone()
        if not row:
            debug_row = conn.execute(
                'SELECT expires_at FROM magic_tokens WHERE token=?', (token,)
            ).fetchone()
            conn.close()
            if debug_row:
                debug_info = f'Токен истёк {debug_row["expires_at"]}'
            else:
                debug_info = 'Токен не найден — возможно, была выслана новая ссылка'
            return render_template('auth.html', token_expired=True, debug_info=debug_info)

        email = row['email'].strip().lower()
        if not email:
            conn.close()
            return render_template('auth.html', token_expired=True)

        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if not user:
            user = conn.execute(
                'SELECT * FROM users WHERE LOWER(TRIM(email))=?', (email,)
            ).fetchone()

        if user:
            conn.execute('UPDATE users SET email=?, has_access=1 WHERE id=?', (email, user['id']))
            conn.commit()
        else:
            conn.execute(
                'INSERT INTO users (email, password_hash, has_access) VALUES (?, ?, 1)', (email, '')
            )
            conn.commit()

        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if not user:
            conn.close()
            return render_template('auth.html', token_expired=True)

        conn.close()
        session.permanent = True
        session['user_id'] = user['id']
        session['email'] = user['email']
        return redirect(url_for('main.cards'))
    except Exception as e:
        return render_template('auth.html', token_expired=True, debug_info=f'Exception: {e}')


@main.route('/auth/report', methods=['POST'])
def auth_report():
    email = request.form.get('email', '').strip()[:200]
    message = request.form.get('message', '').strip()[:1000]
    if not email or not message:
        return 'Bad request', 400
    try:
        from .db import get_db
        conn = get_db()
        conn.execute('''CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0
        )''')
        conn.execute(
            'INSERT INTO reports (email, message, created_at) VALUES (?, ?, ?)',
            (email, message, datetime.utcnow().strftime('%d.%m.%Y %H:%M'))
        )
        conn.commit()
        conn.close()
        _notify_admin(
            f'Новое обращение от {email}',
            f'Email: {email}\n\nСообщение:\n{message}'
        )
        return '', 200
    except Exception:
        return '', 500


@main.route('/offer')
def offer():
    return render_template('offer.html')


@main.route('/privacy')
def privacy():
    return render_template('privacy.html')


@main.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.free'))


# ── Admin ────────────────────────────────────────────────────────────────────

def _admin_required():
    return session.get('admin_logged_in')


@main.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == os.environ.get('ADMIN_PASSWORD', ''):
            session['admin_logged_in'] = True
            session.permanent = True
            return redirect(url_for('main.admin'))
        return render_template('admin_login.html', error='Неверный пароль')
    return render_template('admin_login.html')


@main.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('main.admin_login'))


@main.route('/admin')
def admin():
    if not _admin_required():
        return redirect(url_for('main.admin_login'))
    blocks_data = {}
    for block in ['action', 'question', 'care']:
        blocks_data[block] = load_block(block)
    from .db import get_db
    conn = get_db()
    users = conn.execute(
        'SELECT id, email, has_access, created_at FROM users ORDER BY id DESC LIMIT 1000'
    ).fetchall()
    all_cards_flat = []
    for block in ['action', 'question', 'care']:
        for card in load_block(block):
            all_cards_flat.append({'id': card['id'], 'text': card.get('text', '')[:50], 'block': block})
    free_ids = get_free_card_ids()
    blogger_stats = conn.execute('''
        SELECT
            CASE WHEN blogger = '' THEN 'Прямые продажи' ELSE blogger END as blogger,
            COUNT(*) as cnt,
            SUM(amount) as total,
            SUM(commission) as commission
        FROM sales
        GROUP BY blogger
        ORDER BY total DESC
    ''').fetchall()
    sales = conn.execute(
        'SELECT id, date, email, utm, blogger, amount, commission FROM sales ORDER BY id DESC'
    ).fetchall()
    try:
        reports = conn.execute(
            'SELECT id, email, message, created_at, resolved FROM reports ORDER BY id DESC LIMIT 500'
        ).fetchall()
    except Exception:
        reports = []
    conn.close()
    return render_template('admin.html', blocks=blocks_data, users=users,
                           blogger_stats=blogger_stats, sales=sales,
                           all_cards=all_cards_flat, free_ids=free_ids,
                           reports=reports)


@main.route('/admin/grant', methods=['POST'])
def admin_grant():
    if not _admin_required():
        return 'Forbidden', 403
    email = request.form.get('email', '').strip().lower()
    if not email or '@' not in email:
        return 'Bad email', 400
    try:
        from .db import get_db
        conn = get_db()
        _upsert_user(conn, email)
        _send_magic_link(email, conn)
        conn.close()
        return 'OK', 200
    except Exception as e:
        return f'Ошибка: {e}', 500


@main.route('/admin/resolve-report', methods=['POST'])
def admin_resolve_report():
    if not _admin_required():
        return 'Forbidden', 403
    report_id = request.form.get('id', '')
    try:
        from .db import get_db
        conn = get_db()
        conn.execute('UPDATE reports SET resolved=1 WHERE id=?', (report_id,))
        conn.commit()
        conn.close()
        return '', 200
    except Exception as e:
        return f'Ошибка: {e}', 500


@main.route('/admin/delete-sales', methods=['POST'])
def admin_delete_sales():
    if not _admin_required():
        return 'Forbidden', 403
    ids_raw = request.form.get('ids', '')
    try:
        ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
    except Exception:
        return 'Bad request', 400
    if not ids:
        return 'Nothing to delete', 400
    try:
        from .db import get_db
        conn = get_db()
        conn.execute(
            'DELETE FROM sales WHERE id IN ({})'.format(','.join('?' * len(ids))), ids
        )
        conn.commit()
        conn.close()
        return '', 200
    except Exception as e:
        return f'Ошибка: {e}', 500


@main.route('/admin/save', methods=['POST'])
def admin_save():
    if not _admin_required():
        return 'Forbidden', 403
    block = request.form.get('block', '')
    if block not in ('action', 'question', 'care'):
        return 'Bad request', 400
    card_id = request.form.get('id', '')
    data_file = os.path.join(DATA_DIR, f'cards_{block}.json')
    with open(data_file, encoding='utf-8') as f:
        data = json.load(f)
    for card in data['cards']:
        if card['id'] == card_id:
            card['level']   = request.form.get('level',   card.get('level', ''))
            card['text']    = request.form.get('text',    card.get('text', ''))
            card['hint']    = request.form.get('hint',    card.get('hint', ''))
            card['why']     = request.form.get('why',     card.get('why', ''))
            card['science'] = request.form.get('science', card.get('science', ''))
            card['result']  = request.form.get('result',  card.get('result', ''))
            brain_raw = request.form.get('brain', '')
            card['brain'] = [l.strip() for l in brain_raw.splitlines() if l.strip()]
            break
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return '', 200


@main.route('/admin/free-cards', methods=['POST'])
def admin_free_cards():
    if not _admin_required():
        return 'Forbidden', 403
    ids = [request.form.get(f'card_{i}', '').strip() for i in range(5)]
    ids = [cid for cid in ids if cid]
    save_free_card_ids(ids)
    return '', 200


# ── Blogger CRM ──────────────────────────────────────────────────────────────

COMMISSION_PER_SALE = 207  # 30% of 690 RUB

BLOGGER_STATUSES = [
    ('new',        'Новый',          '#8C7E72', '#F5F0EB'),
    ('sent',       'Отправлено',     '#1a6fa6', '#e8f4fd'),
    ('replied',    'Ответил',        '#a67c00', '#fff8e1'),
    ('interested', 'Интересно',      '#2e7d32', '#e8f5e9'),
    ('agreed',     'Сотрудничаем',   '#1565c0', '#e3f2fd'),
    ('posted',     'Опубликовал',    '#1b5e20', '#c8e6c9'),
    ('declined',   'Отказал',        '#c0392b', '#fbe9e7'),
]


def _make_utm_slug(name):
    slug = name.lower().strip()
    slug = _re.sub(r'[\s\-]+', '_', slug)
    slug = _re.sub(r'[^a-z0-9_]', '', slug)
    return slug[:50] or 'blogger'


def _blogger_warning(blogger, now):
    if blogger['status'] not in ('sent', 'replied'):
        return False
    if not blogger['first_email_sent_at']:
        return False
    if blogger['last_reply_at']:
        return False
    try:
        sent = datetime.fromisoformat(blogger['first_email_sent_at'])
        return (now - sent).days >= 3
    except Exception:
        return False


def _ensure_email_templates_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS email_templates (
        key TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        body_text TEXT NOT NULL
    )''')
    for key, subject, body_text in [
        ('blogger_first',
         'Сотрудничество — колода карточек «Ближе» для пар',
         'Привет, {name}! \U0001f44b\n\nМеня зовут Катя, я создала Vera — онлайн-колоду карточек «Ближе» для пар на verevery.ru.\n\nКарточки помогают восстановить близость в отношениях — основаны на доказательной психологии (Готтман, EFT, теория привязанности). Цена: 690 ₽.\n\nХочу предложить сотрудничество: вы рассказываете аудитории о проекте, получаете 30% с каждой продажи по вашей ссылке — 207 ₽ за покупку.\n\nЕсли интересно — напишу подробнее об условиях \U0001f64c\n\nКатя\nverevery.ru'),
        ('blogger_second',
         'Re: Сотрудничество — колода карточек «Ближе» для пар',
         'Привет, {name}! Рада, что откликнулись \U0001f49b\n\nВот подробности о сотрудничестве:\n\n\U0001f4e6 Продукт: онлайн-колода «Ближе» — 60 карточек для пар (verevery.ru)\n\U0001f4b8 Комиссия: 30% = 207 ₽ с каждой продажи\n\U0001f517 Ваша ссылка: {utm_link}\n\nКак это работает:\n1. Вы публикуете пост или сторис со своей ссылкой\n2. Подписчики переходят и покупают\n3. Я считаю продажи по вашему UTM и перевожу комиссию раз в месяц\n\nМогу прислать описание продукта и примеры карточек — всё что нужно для публикации.\n\nГотова ответить на любые вопросы!\n\nКатя\nverevery.ru'),
        ('blogger_third',
         '{name}, делюсь рекомендациями по работе с контентом',
         'Привет, {name}!\n\nДелюсь рекомендациями по формату публикации. Это не жёсткие требования — финальный вид всегда за вами. Но эти подходы по нашему опыту дают лучший отклик.\n\n\U0001f4cc ВАЖНО ПРО ФОРМАТ ПРОДУКТА\n\nКарточки — цифровые, открываются в браузере на экране телефона.\nЭто не одна категория, а три блока по 20 карточек:\n\n— Вопрос — глубокие вопросы для разговора с партнёром\n— Действие — конкретные совместные практики (прогулка без телефона, записка в кармане и т.д.)\n— Забота — готовые фразы поддержки и принятия\n\nВнутри каждого блока — три уровня сложности: Лёгкий → Средний → Сложный. Можно начинать с лёгких и идти глубже.\n\nУ каждой карточки есть не только текст вопроса/действия, но и объяснение зачем это работает с точки зрения нейробиологии и ссылкой на исследования (Готтман, EFT, КПТ, ACT). Это важный момент — это не «вопросы для знакомства», это инструмент.\n\n\U0001f4f1 ОСНОВНОЙ ПОСТ\n\nФормат 1 — Карусель «Три карточки которые меня прибили» (5-7 слайдов)\n\nСамый сильный формат для цифровых карточек. Структура:\n\nСлайд 1 — Хук со скриншотом одной карточки\nСкриншот самой сильной карточки крупным планом. Например карточка В-01 «Лучший момент»: «Какой момент, проведённый с тобой, я вспоминаю чаще всего — и почему именно он?»\nПодпись поверх или рядом: «Этот вопрос я бы никогда не задала сама. А зря».\n\nСлайды 2-4 — Личное размышление\nВ вашем обычном стиле. Реакция на карточки, личный опыт, размышление про близость. Не реклама — продолжение вашего обычного контента.\n\nСлайд 5 — Скриншоты карточек из разных блоков\nОдин скриншот вопроса, один действия, один заботы. Подпись сбоку: «Вопрос. Действие. Забота. 60 карточек, три блока, три уровня сложности».\n\nСлайд 6 — Что внутри\nКратко про научную базу: «Каждая карточка построена на исследованиях — Готтман, КПТ, теория привязанности. И к каждой есть объяснение почему это работает в мозге».\n\nСлайд 7 — Призыв\n«5 карточек бесплатно — посмотреть как это устроено. Полная колода — по моей ссылке: {utm_link}»\n\nФормат 2 — Рилс (15-45 секунд)\n\nСценарий А — «Три вопроса которые поменяли разговор»\nЗапись экрана: листаете карточки в браузере, останавливаетесь на трёх самых сильных вопросах. Голос за кадром: «Купила недавно. Задала мужу эти три вопроса. Говорили два часа без перерыва.»\n\nСценарий Б — Screen recording по блокам\nБыстрая смена скриншотов — Вопрос / Действие / Забота. Голос или текст: «В отношениях обычно не хватает не любви. Не хватает поводов поговорить. Вот 60 поводов, разделённые на три категории.»\n\nСценарий В — Реакция на одну карточку\nКамера на вас, в кадре телефон с одной карточкой. Читаете вопрос вслух, реагируете честно.\n\nСценарий Г — «Категория Забота — это что-то отдельное»\nФокус только на блоке Забота. Скриншоты 2-3 карточек заботы + ваша реакция: «Это не вопросы. Это просто фразы. Но попробуй их сказать вслух — поймёшь почему сложно».\n\n\U0001f4f2 STORIES (2-3 ШТУКИ)\n\nStories 1 — Тизер за день до поста\nСкриншот одной мощной карточки + ваш комментарий.\n\nStories 2 — В день публикации\nСкриншот поста + ссылка-стикер.\n\nStories 3 — Через 1-2 дня\nЛичная реакция или цитата без давления — продолжение темы.\n\n\U0001f4e6 ВИЗУАЛЬНЫЕ МАТЕРИАЛЫ ОТ НАС\n\nЯ пришлю:\n— Подборку скриншотов карточек в высоком разрешении из всех трёх блоков\n— Mockup-изображения телефона с открытыми карточками\n— Screen recording прохождения карточек на телефоне\n— Готовые тексты постов и stories\n\n\U0001f7e2 ЧТО ХОРОШО РАБОТАЕТ\n\n— Скриншоты конкретных вопросов или фраз из колоды\n— Подсветка структуры (три блока, три уровня)\n— Упоминание научной базы (Готтман, КПТ, исследования)\n— Личная реакция на конкретную карточку «вот эта меня прибила»\n— Акцент что у каждой карточки есть объяснение зачем\n\n\U0001f534 ЧТО НЕ РАБОТАЕТ\n\n— «Карточки помогут улучшить отношения» — пустая фраза без конкретики\n— Скрывать что продукт цифровой\n— Не упоминать три категории и градацию сложности\n— Слова «уникальный», «революционный», «единственный»\n— Прямая реклама без личной обёртки\n\n\U0001f552 ПО ТАЙМИНГУ\n\nЛучшее время для публикации в нише отношений:\n— Будни: вечер 19:00–21:30\n— Выходные: первая половина дня 11:00–14:00\n\n⚠️ ОБЯЗАТЕЛЬНО\n\n— Маркировка рекламы по закону РФ: пометка «реклама», ИНН рекламодателя и ERID. Пришлю данные после регистрации креатива в ОРД.\n— Чёткое указание что продукт цифровой (онлайн-формат, открывается в браузере на телефоне)\n— Партнёрская ссылка в шапке профиля или ссылке-стикере stories: {utm_link}\n\nЕсли хотите обсудить идеи — пишите. Могу помочь подобрать конкретные карточки под раскадровку рилс или текст поста.\n\nС уважением,\nКатя'),
    ]:
        try:
            conn.execute(
                'INSERT OR IGNORE INTO email_templates (key, subject, body_text) VALUES (?, ?, ?)',
                (key, subject, body_text)
            )
        except Exception:
            pass
    conn.commit()


def _get_template(conn, key):
    try:
        row = conn.execute('SELECT subject, body_text FROM email_templates WHERE key=?', (key,)).fetchone()
    except Exception:
        row = None
    if row:
        return row['subject'], row['body_text']
    if key == 'blogger_first':
        return ('Сотрудничество — колода карточек «Ближе» для пар',
                'Привет, {name}! 👋\n\nМеня зовут Катя, я создала Vera — онлайн-колоду карточек «Ближе» для пар на verevery.ru.\n\nКарточки помогают восстановить близость в отношениях — основаны на доказательной психологии (Готтман, EFT, теория привязанности). Цена: 690 ₽.\n\nХочу предложить сотрудничество: вы рассказываете аудитории о проекте, получаете 30% с каждой продажи по вашей ссылке — 207 ₽ за покупку.\n\nЕсли интересно — напишу подробнее об условиях 🙌\n\nКатя\nverevery.ru')
    if key == 'blogger_third':
        return ('{name}, делюсь рекомендациями по работе с контентом',
                'Привет, {name}!\n\nДелюсь рекомендациями по формату публикации.\n\nКатя\nverevery.ru')
    return ('Re: Сотрудничество — колода карточек «Ближе» для пар',
            'Привет, {name}! Рада, что откликнулись 💛\n\nВаша UTM-ссылка: {utm_link}\n\nКатя\nverevery.ru')


def _render_email_html(body_text, name, utm_link=''):
    import html as _html
    text = body_text.replace('{name}', name).replace('{utm_link}', utm_link)
    paragraphs = ''
    for para in text.split('\n\n'):
        para = para.strip()
        if not para:
            continue
        lines = para.split('\n')
        escaped = '<br>'.join(_html.escape(l) for l in lines)
        paragraphs += f'<p style="font-size:14px;font-weight:300;color:#5C4F44;line-height:1.8;margin:0 0 14px;">{escaped}</p>'
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#FAF7F2;font-family:Helvetica,Arial,sans-serif;">'
        '<div style="max-width:480px;margin:0 auto;padding:40px 24px;">'
        '<div style="font-family:Georgia,serif;font-size:22px;color:#2A2118;margin-bottom:32px;">'
        'vere<span style="color:#A67C52;">very</span></div>'
        '<div style="background:#FFFFFF;border:1px solid #EDE6DA;border-radius:20px;padding:32px 28px;">'
        + paragraphs +
        '</div></div></body></html>'
    )


def _send_blogger_email(blogger, email_type, conn):
    import resend
    resend.api_key = os.environ.get('RESEND_API_KEY', '')
    template_key = {'first': 'blogger_first', 'second': 'blogger_second', 'third': 'blogger_third'}.get(email_type, 'blogger_first')
    subject, body_text = _get_template(conn, template_key)
    html_body = _render_email_html(body_text, blogger['name'], blogger['utm_link'] or '')
    now_fmt = datetime.utcnow().strftime('%d.%m.%Y %H:%M')
    try:
        resend.Emails.send({
            'from': 'Vera <team@verevery.ru>',
            'reply_to': [REPLY_TO_EMAIL],
            'to': [blogger['email']],
            'subject': subject,
            'html': html_body,
        })
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status) VALUES (?,?,?,?)',
            (blogger['id'], email_type, now_fmt, 'ok')
        )
        return True, None
    except Exception as e:
        err = str(e)[:500]
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status, error) VALUES (?,?,?,?,?)',
            (blogger['id'], email_type, now_fmt, 'error', err)
        )
        return False, err


def _classify_reply_with_claude(text):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=10,
            messages=[{'role': 'user', 'content': (
                'Ты помощник, который анализирует ответы блогеров на предложение о сотрудничестве. '
                'Классифицируй ответ как одно из:\n'
                '- positive (заинтересован, хочет узнать больше, готов сотрудничать)\n'
                '- negative (отказ, не интересно, не подходит)\n'
                '- question (задаёт вопросы, нужна дополнительная информация)\n'
                'Ответить только одним словом: positive, negative или question.\n'
                f'Текст ответа: {text[:2000]}'
            )}]
        )
        result = msg.content[0].text.strip().lower()
        if result in ('positive', 'negative', 'question'):
            return result
    except Exception:
        pass
    return 'question'


def _draft_reply_with_claude(blogger_name, text):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': (
                f'Блогер {blogger_name} написал нам по поводу сотрудничества с онлайн-колодой «Ближе» (verevery.ru). '
                'Напиши короткий черновик ответа на его вопрос. Отвечаем от имени Кати. '
                'Тон: тёплый, дружелюбный, профессиональный.\n\n'
                f'Вопрос блогера:\n{text[:1000]}'
            )}]
        )
        return msg.content[0].text.strip()
    except Exception:
        return '(не удалось сгенерировать черновик)'


def _notify_admin(subject, body):
    try:
        import resend
        resend.api_key = os.environ.get('RESEND_API_KEY', '')
        to = os.environ.get('ADMIN_NOTIFY_EMAIL', 'team.verevery@gmail.com')
        resend.Emails.send({
            'from': 'Vera система <noreply@verevery.ru>',
            'to': [to],
            'subject': subject,
            'html': f'<pre style="font-family:sans-serif;white-space:pre-wrap;font-size:14px">{body}</pre>',
        })
    except Exception:
        pass


# ── Direct outbound: Instagram & Telegram ────────────────────────────────────

def send_instagram_dm(psid, text):
    """POST to Instagram Graph API (IG Login, IGAA token). Returns {'ok': bool, ...}."""
    import requests as _req
    import time as _time
    token = os.environ.get('INSTAGRAM_ACCESS_TOKEN')
    user_id = os.environ.get('INSTAGRAM_USER_ID')
    if not token or not user_id:
        return {'ok': False, 'error': 'INSTAGRAM_ACCESS_TOKEN или INSTAGRAM_USER_ID не настроены'}
    url = f'https://graph.instagram.com/v23.0/{user_id}/messages'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    body = {'recipient': {'id': psid}, 'message': {'text': text}}
    for attempt in range(2):
        try:
            resp = _req.post(url, json=body, headers=headers, timeout=7)
            if resp.status_code < 400:
                return {'ok': True, 'message_id': resp.json().get('message_id')}
            if resp.status_code >= 500 and attempt < 1:
                _time.sleep(2)
                continue
            logger.error(f'send_instagram_dm HTTP {resp.status_code}: {resp.text[:300]}')
            return {'ok': False, 'error': f'HTTP {resp.status_code}: {resp.text[:300]}'}
        except Exception as e:
            if attempt < 1:
                _time.sleep(2)
                continue
            logger.error(f'send_instagram_dm exception: {e}')
            return {'ok': False, 'error': str(e)[:300]}
    return {'ok': False, 'error': 'все попытки исчерпаны'}


def send_telegram_message(chat_id, text):
    """POST to Telegram Bot API sendMessage. Returns {'ok': bool, ...}."""
    import requests as _req
    import time as _time
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        return {'ok': False, 'error': 'TELEGRAM_BOT_TOKEN не настроен'}
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    body = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    for attempt in range(3):
        try:
            resp = _req.post(url, json=body, timeout=10)
            if resp.status_code < 400:
                result = resp.json().get('result') or {}
                return {'ok': True, 'message_id': str(result.get('message_id', ''))}
            if resp.status_code >= 500 and attempt < 2:
                _time.sleep(2 ** attempt)
                continue
            logger.error(f'send_telegram_message HTTP {resp.status_code}: {resp.text[:300]}')
            return {'ok': False, 'error': f'HTTP {resp.status_code}: {resp.text[:300]}'}
        except Exception as e:
            if attempt < 2:
                _time.sleep(2 ** attempt)
                continue
            logger.error(f'send_telegram_message exception: {e}')
            return {'ok': False, 'error': str(e)[:300]}
    return {'ok': False, 'error': 'все попытки исчерпаны'}


def _dispatch_outbound(blogger, email_type, conn):
    """Route outbound message: IG/TG → direct API, email → Resend. Returns (ok, error_msg)."""
    channel = (blogger.get('channel') or 'email').strip()
    if channel == 'email':
        return _send_blogger_email(blogger, email_type, conn)
    template_key = {'first': 'blogger_first', 'second': 'blogger_second', 'third': 'blogger_third'}.get(
        email_type, 'blogger_first'
    )
    subject, body_text = _get_template(conn, template_key)
    text = body_text.replace('{name}', blogger.get('name', '')).replace(
        '{utm_link}', blogger.get('utm_link') or ''
    )
    now_fmt = datetime.utcnow().strftime('%d.%m.%Y %H:%M')
    bid = blogger['id']
    if channel == 'instagram':
        result = send_instagram_dm(blogger.get('ig_user_id', ''), text)
    elif channel == 'telegram':
        result = send_telegram_message(blogger.get('tg_user_id', ''), text)
    else:
        result = {'ok': False, 'error': f'неизвестный канал: {channel}'}
    ok = result.get('ok', False)
    err = result.get('error', '')
    if ok:
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status) VALUES (?,?,?,?)',
            (bid, email_type, now_fmt, 'ok')
        )
    else:
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status, error) VALUES (?,?,?,?,?)',
            (bid, email_type, now_fmt, 'error', str(err)[:500])
        )
    return ok, err if not ok else None


# ── Incoming message pipeline ─────────────────────────────────────────────────

def _resolve_ig_psid_to_username(psid, timeout=15):
    """Call Instagram Graph API to get username for a PSID. Returns lowercase username or None."""
    import requests as _req
    token = os.environ.get('INSTAGRAM_ACCESS_TOKEN')
    if not token:
        return None
    try:
        resp = _req.get(
            f'https://graph.instagram.com/v23.0/{psid}',
            params={'fields': 'username,name', 'access_token': token},
            timeout=timeout,
        )
        if resp.status_code == 200:
            username = resp.json().get('username', '').strip().lower()
            if username:
                logger.warning(f'resolved PSID {psid} → @{username}')
                return username
        else:
            logger.warning(f'_resolve_ig_psid_to_username({psid}): API {resp.status_code} {resp.text[:200]}')
    except Exception as e:
        logger.warning(f'_resolve_ig_psid_to_username({psid}): {e}')
    return None


def find_blogger_by_external_id(channel, external_id, extra, conn):
    """Locate blogger by channel-specific ID; auto-saves ig_user_id when found by username."""
    blogger = None
    if channel == 'instagram':
        # 1. Exact match by saved PSID
        blogger = conn.execute(
            'SELECT * FROM bloggers WHERE ig_user_id=?', (external_id,)
        ).fetchone()
        if not blogger:
            # 2. Username from webhook payload (new IG API rarely includes it)
            ig_username = (extra.get('ig_username') or '').strip().lstrip('@').lower()
            # Note: Graph API PSID→username lookup moved to background thread to avoid
            # blocking the webhook response. See process_incoming_message_async.
            if ig_username:
                blogger = conn.execute(
                    'SELECT * FROM bloggers WHERE LOWER(ig_username)=?', (ig_username,)
                ).fetchone()
        if blogger and not blogger['ig_user_id']:
            conn.execute('UPDATE bloggers SET ig_user_id=? WHERE id=?', (external_id, blogger['id']))
            conn.commit()
            logger.warning(
                f'auto-saved ig_user_id={external_id} for blogger {blogger["id"]} (@{blogger["ig_username"]})'
            )
    elif channel == 'telegram':
        tg_username = (extra.get('tg_username') or '').strip().lstrip('@').lower()
        blogger = conn.execute(
            'SELECT * FROM bloggers WHERE tg_user_id=?', (external_id,)
        ).fetchone()
        if not blogger and tg_username:
            blogger = conn.execute(
                'SELECT * FROM bloggers WHERE LOWER(tg_username)=?', (tg_username,)
            ).fetchone()
    return dict(blogger) if blogger else None


def store_incoming_message(channel, external_id, text, raw_payload, received_at,
                           message_id=None, extra=None):
    """Store incoming message with deduplication on (channel, message_id). Returns message_db_id."""
    from .db import get_db
    extra = extra or {}
    raw_json = json.dumps(raw_payload, ensure_ascii=False)[:8192]
    conn = get_db()
    try:
        blogger = find_blogger_by_external_id(channel, external_id, extra, conn)
        blogger_id = blogger['id'] if blogger else None

        if message_id is not None:
            cursor = conn.execute(
                '''INSERT OR IGNORE INTO incoming_messages
                   (channel, message_id, external_id, blogger_id, text, received_at, raw_payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (channel, message_id, external_id, blogger_id, text[:4096], received_at, raw_json)
            )
            conn.commit()
            if cursor.rowcount == 0:
                existing = conn.execute(
                    'SELECT id FROM incoming_messages WHERE channel=? AND message_id=?',
                    (channel, message_id)
                ).fetchone()
                msg_id = existing['id'] if existing else None
                logger.info(f'duplicate {channel} message_id={message_id}, skipping processing')
                conn.close()
                return msg_id
            msg_id = cursor.lastrowid
        else:
            # no message_id (edge case) — insert unconditionally, no dedup
            cursor = conn.execute(
                '''INSERT INTO incoming_messages
                   (channel, message_id, external_id, blogger_id, text, received_at, raw_payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (channel, None, external_id, blogger_id, text[:4096], received_at, raw_json)
            )
            conn.commit()
            msg_id = cursor.lastrowid

        known = f'blogger_id={blogger_id}' if blogger_id else 'НЕИЗВЕСТЕН'
        logger.warning(f'incoming {channel} from {external_id} ({known}): {text[:80]}')
        conn.close()
        threading.Thread(target=process_incoming_message_async, args=(msg_id,), daemon=True).start()
        return msg_id
    except Exception:
        logger.exception('store_incoming_message error')
        try:
            conn.close()
        except Exception:
            pass
        return None


def process_incoming_message_async(message_db_id):
    """Background: classify sentiment, update blogger status, maybe auto-reply."""
    from .db import get_db
    conn = get_db()
    try:
        msg = conn.execute(
            'SELECT * FROM incoming_messages WHERE id=?', (message_db_id,)
        ).fetchone()
        if not msg:
            logger.warning(f'process_incoming_message_async: message {message_db_id} not found')
            return
        msg = dict(msg)
        channel = msg['channel']
        text = msg['text']
        blogger_id = msg['blogger_id']

        if not blogger_id:
            # Try to resolve PSID→username in background (longer timeout OK here)
            if channel == 'instagram':
                external_id = msg['external_id']
                ig_username = _resolve_ig_psid_to_username(external_id, timeout=20)
                if ig_username:
                    row = conn.execute(
                        'SELECT * FROM bloggers WHERE LOWER(ig_username)=?', (ig_username,)
                    ).fetchone()
                    if row:
                        blogger_id = row['id']
                        conn.execute('UPDATE bloggers SET ig_user_id=? WHERE id=?', (external_id, blogger_id))
                        conn.execute(
                            'UPDATE incoming_messages SET blogger_id=? WHERE id=?', (blogger_id, message_db_id)
                        )
                        conn.commit()
                        logger.warning(
                            f'background: resolved PSID {external_id} → @{ig_username} → blogger {blogger_id}'
                        )

            if not blogger_id:
                external_id = msg['external_id']
                logger.warning(f'message {message_db_id}: blogger not identified (external_id={external_id})')
                _notify_admin(
                    f'Неизвестный {channel}: новое сообщение',
                    f'Получено сообщение от неизвестного пользователя.\n\n'
                    f'Канал: {channel}\n'
                    f'PSID / external_id: {external_id}\n\n'
                    f'Сообщение:\n{msg["text"]}\n\n'
                    f'Добавьте этот ID в поле ig_user_id блогера в админке, '
                    f'чтобы следующие сообщения определялись автоматически.'
                )
                conn.execute(
                    'UPDATE incoming_messages SET processed_at=datetime("now") WHERE id=?', (message_db_id,)
                )
                conn.commit()
                return

        blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (blogger_id,)).fetchone()
        if not blogger:
            logger.warning(f'message {message_db_id}: blogger {blogger_id} missing from DB')
            return
        blogger = dict(blogger)
        bid = blogger['id']

        # debounce: skip if last reply was within 60 seconds (handles burst messages)
        last_reply = blogger.get('last_reply_at') or ''
        if last_reply:
            try:
                last_dt = datetime.fromisoformat(last_reply)
                if (datetime.utcnow() - last_dt).total_seconds() < 60:
                    logger.info(f'debounce: skipping {channel} from blogger {bid}')
                    conn.execute(
                        'UPDATE incoming_messages SET processed_at=datetime("now") WHERE id=?',
                        (message_db_id,)
                    )
                    conn.commit()
                    return
            except Exception:
                pass

        now_iso = datetime.utcnow().isoformat()
        now_fmt = datetime.utcnow().strftime('%d.%m.%Y %H:%M')

        logger.info(f'classifying {channel} message {message_db_id} from blogger {bid}')
        sentiment = _classify_reply_with_claude(text)

        conn.execute(
            'UPDATE bloggers SET last_reply_at=?, reply_sentiment=?, last_message=? WHERE id=?',
            (now_iso, sentiment, text[:2000], bid)
        )

        if sentiment == 'positive':
            conn.execute("UPDATE bloggers SET status='interested' WHERE id=?", (bid,))
            conn.commit()
            logger.info(f'blogger {bid} positive → sending second via {channel}')
            _dispatch_outbound(blogger, 'second', conn)
            conn.commit()
        elif sentiment == 'negative':
            conn.execute("UPDATE bloggers SET status='declined' WHERE id=?", (bid,))
            conn.commit()
            logger.warning(f'blogger {bid} declined via {channel}')
            _notify_admin(
                f'Блогер {blogger["name"]} отказал',
                f'Канал: {channel}\nОтвет:\n{text}'
            )
        else:
            conn.execute("UPDATE bloggers SET status='replied' WHERE id=?", (bid,))
            conn.commit()
            draft = _draft_reply_with_claude(blogger['name'], text)
            logger.info(f'blogger {bid} has question, notifying admin')
            _notify_admin(
                f'Блогер {blogger["name"]} задал вопрос',
                f'Канал: {channel}\nОтвет блогера:\n{text}\n\n---\nЧерновик ответа:\n{draft}'
            )

        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status) VALUES (?,?,?,?)',
            (bid, f'inbound_{channel}', now_fmt, sentiment)
        )
        conn.execute(
            'UPDATE incoming_messages SET processed_at=datetime("now") WHERE id=?', (message_db_id,)
        )
        conn.commit()
        logger.warning(f'processed message {message_db_id}: blogger {bid}, sentiment={sentiment}')
    except Exception:
        logger.exception(f'process_incoming_message_async error for message {message_db_id}')
    finally:
        conn.close()


@main.route('/admin/bloggers')
def admin_bloggers():
    if not _admin_required():
        return redirect(url_for('main.admin_login'))
    status_filter = request.args.get('status', '')
    search = request.args.get('q', '').strip()
    from .db import get_db
    conn = get_db()
    query = '''
        SELECT b.*,
            COALESCE(s.cnt, 0) as real_sales,
            COALESCE(s.revenue, 0.0) as total_revenue
        FROM bloggers b
        LEFT JOIN (
            SELECT blogger, COUNT(*) as cnt, SUM(amount) as revenue
            FROM sales GROUP BY blogger
        ) s ON s.blogger = b.utm_slug
    '''
    conditions, params = [], []
    if status_filter:
        conditions.append('b.status = ?')
        params.append(status_filter)
    if search:
        conditions.append('(b.name LIKE ? OR b.email LIKE ?)')
        params += [f'%{search}%', f'%{search}%']
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    query += ' ORDER BY b.created_at DESC'
    bloggers_rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    status_counts = {'': 0}
    for row in conn.execute('SELECT status, COUNT(*) as cnt FROM bloggers GROUP BY status'):
        status_counts[row['status']] = row['cnt']
        status_counts[''] += row['cnt']

    _ensure_email_templates_table(conn)
    t1 = conn.execute("SELECT body_text FROM email_templates WHERE key='blogger_first'").fetchone()
    t2 = conn.execute("SELECT body_text FROM email_templates WHERE key='blogger_second'").fetchone()
    t3 = conn.execute("SELECT body_text FROM email_templates WHERE key='blogger_third'").fetchone()
    email_templates = {
        'first': t1['body_text'] if t1 else '',
        'second': t2['body_text'] if t2 else '',
        'third': t3['body_text'] if t3 else '',
    }
    conn.close()

    now = datetime.utcnow()
    return render_template('admin_bloggers.html',
                           bloggers=bloggers_rows,
                           status_filter=status_filter,
                           search=search,
                           status_counts=status_counts,
                           statuses=BLOGGER_STATUSES,
                           now=now,
                           cps=COMMISSION_PER_SALE,
                           blogger_warning=_blogger_warning,
                           email_templates=email_templates)


@main.route('/admin/bloggers/add', methods=['POST'])
def admin_bloggers_add():
    if not _admin_required():
        return 'Forbidden', 403
    name = request.form.get('name', '').strip()[:200]
    if not name:
        return 'Имя обязательно', 400
    platform = request.form.get('platform', '').strip()[:100]
    profile_url = request.form.get('profile_url', '').strip()[:500]
    email = request.form.get('email', '').strip().lower()[:200]
    utm_slug = request.form.get('utm_slug', '').strip() or _make_utm_slug(name)
    utm_link = f'{BASE_URL}/free?utm={utm_slug}'
    notes = request.form.get('notes', '').strip()[:2000]
    channel = request.form.get('channel', 'email').strip()
    ig_username = request.form.get('ig_username', '').strip()[:200]
    ig_user_id = request.form.get('ig_user_id', '').strip()[:100]
    tg_username = request.form.get('tg_username', '').strip()[:200]
    tg_user_id = request.form.get('tg_user_id', '').strip()[:50]
    try:
        from .db import get_db
        conn = get_db()
        conn.execute(
            'INSERT INTO bloggers (name, platform, profile_url, email, utm_slug, utm_link, notes, channel, ig_username, ig_user_id, tg_username, tg_user_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (name, platform, profile_url, email, utm_slug, utm_link, notes, channel, ig_username, ig_user_id, tg_username, tg_user_id)
        )
        conn.commit()
        conn.close()
        return '', 200
    except Exception as e:
        return f'Ошибка: {e}', 500


@main.route('/admin/bloggers/<int:bid>/update', methods=['POST'])
def admin_bloggers_update(bid):
    if not _admin_required():
        return 'Forbidden', 403
    allowed = {'name', 'platform', 'profile_url', 'email', 'utm_slug',
               'status', 'notes', 'paid_out', 'reply_sentiment',
               'channel', 'ig_username', 'ig_user_id', 'tg_username', 'tg_user_id'}
    updates = {k: request.form[k].strip() for k in allowed if k in request.form}
    if 'utm_slug' in updates:
        updates['utm_link'] = f'{BASE_URL}/free?utm={updates["utm_slug"]}'
    if not updates:
        return 'Nothing to update', 400
    from .db import get_db
    conn = get_db()
    set_clause = ', '.join(f'{k}=?' for k in updates)
    conn.execute(f'UPDATE bloggers SET {set_clause} WHERE id=?', list(updates.values()) + [bid])
    conn.commit()
    row = conn.execute('SELECT utm_link FROM bloggers WHERE id=?', (bid,)).fetchone()
    conn.close()
    if row and 'utm_slug' in updates:
        return row['utm_link'], 200
    return '', 200


@main.route('/admin/bloggers/<int:bid>/delete', methods=['POST'])
def admin_bloggers_delete(bid):
    if not _admin_required():
        return 'Forbidden', 403
    from .db import get_db
    conn = get_db()
    conn.execute('DELETE FROM bloggers WHERE id=?', (bid,))
    conn.execute('DELETE FROM email_log WHERE blogger_id=?', (bid,))
    conn.commit()
    conn.close()
    return '', 200


@main.route('/admin/bloggers/<int:bid>/send-email', methods=['POST'])
def admin_bloggers_send_email(bid):
    if not _admin_required():
        return 'Forbidden', 403
    email_type = request.form.get('type', 'first')
    from .db import get_db
    conn = get_db()
    try:
        blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (bid,)).fetchone()
        if not blogger:
            conn.close()
            return 'Блогер не найден', 404
        b = dict(blogger)
        channel = b.get('channel', 'email') or 'email'
        if channel == 'email':
            if not b.get('email'):
                conn.close()
                return 'Email не указан', 400
            ok, err = _send_blogger_email(b, email_type, conn)
        elif channel == 'instagram':
            ig_id = (b.get('ig_user_id') or '').strip()
            if not ig_id:
                conn.close()
                return 'Instagram User ID не получен — дождитесь первого входящего сообщения от блогера', 400
            ok, err = _dispatch_outbound(b, email_type, conn)
        elif channel == 'telegram':
            tg_id = (b.get('tg_user_id') or '').strip()
            if not tg_id:
                conn.close()
                return 'Telegram ID не получен — блогер должен сначала написать боту', 400
            ok, err = _dispatch_outbound(b, email_type, conn)
        else:
            ok, err = _dispatch_outbound(b, email_type, conn)
        if ok and email_type == 'first':
            conn.execute(
                "UPDATE bloggers SET status='sent', first_email_sent_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), bid)
            )
        conn.commit()
        conn.close()
        return ('', 200) if ok else (f'Ошибка: {err}', 400)
    except Exception as e:
        logger.exception(f'admin_bloggers_send_email bid={bid}')
        try:
            conn.close()
        except Exception:
            pass
        return f'Ошибка: {str(e)[:300]}', 400


@main.route('/admin/bloggers/send-bulk', methods=['POST'])
def admin_bloggers_send_bulk():
    if not _admin_required():
        return 'Forbidden', 403
    try:
        ids = [int(x) for x in request.form.get('ids', '').split(',') if x.strip().isdigit()]
    except Exception:
        return 'Bad ids', 400
    if not ids:
        return 'No ids', 400
    from .db import get_db
    conn = get_db()
    sent, errors = 0, []
    now_iso = datetime.utcnow().isoformat()
    for bid in ids:
        b = conn.execute('SELECT * FROM bloggers WHERE id=?', (bid,)).fetchone()
        if not b or not b['email']:
            continue
        ok, err = _send_blogger_email(dict(b), 'first', conn)
        if ok:
            conn.execute(
                "UPDATE bloggers SET status='sent', first_email_sent_at=? WHERE id=?",
                (now_iso, bid)
            )
            sent += 1
        else:
            errors.append(f'{b["name"]}: {err}')
    conn.commit()
    conn.close()
    msg = f'Отправлено: {sent}'
    if errors:
        return msg + '. Ошибки: ' + '; '.join(errors), 207
    return msg, 200


@main.route('/admin/bloggers/analytics')
def admin_bloggers_analytics():
    if not _admin_required():
        return redirect(url_for('main.admin_login'))
    from .db import get_db
    conn = get_db()
    total = conn.execute('SELECT COUNT(*) FROM bloggers').fetchone()[0]
    by_status = {r['status']: r['cnt'] for r in
                 conn.execute('SELECT status, COUNT(*) as cnt FROM bloggers GROUP BY status')}
    rows = conn.execute('''
        SELECT b.id, b.name, b.platform, b.profile_url, b.utm_slug, b.status, b.paid_out,
            COALESCE(s.cnt, 0) as real_sales
        FROM bloggers b
        LEFT JOIN (
            SELECT blogger, COUNT(*) as cnt
            FROM sales GROUP BY blogger
        ) s ON s.blogger = b.utm_slug
        ORDER BY real_sales DESC, b.name
    ''').fetchall()
    conn.close()
    total_sales = sum(r['real_sales'] for r in rows)
    total_commission = total_sales * COMMISSION_PER_SALE
    total_paid = sum(r['paid_out'] for r in rows)
    return render_template('admin_bloggers_analytics.html',
                           total_bloggers=total,
                           funnel=by_status,
                           bloggers=rows,
                           total_sales=total_sales,
                           total_revenue=total_sales * 690,
                           total_commission=total_commission,
                           total_paid=total_paid,
                           total_debt=total_commission - total_paid,
                           statuses=BLOGGER_STATUSES,
                           cps=COMMISSION_PER_SALE)


@main.route('/webhook/email-reply', methods=['POST'])
def webhook_email_reply():
    secret = os.environ.get('WEBHOOK_SECRET', '')
    if secret and request.headers.get('X-Vera-Token') != secret and request.args.get('secret') != secret:
        return 'Forbidden', 403
    try:
        payload = request.get_json(force=True, silent=True) or {}
        data = payload.get('data', payload)
        sender = (data.get('from') or '').strip().lower()
        text = (data.get('text') or data.get('plain_text') or '').strip()
        if not sender or not text:
            return '', 200
        from .db import get_db
        conn = get_db()
        blogger = conn.execute(
            'SELECT * FROM bloggers WHERE LOWER(email)=?', (sender,)
        ).fetchone()
        if not blogger:
            conn.close()
            return '', 200
        blogger = dict(blogger)
        bid = blogger['id']
        now_iso = datetime.utcnow().isoformat()
        now_fmt = datetime.utcnow().strftime('%d.%m.%Y %H:%M')
        sentiment = _classify_reply_with_claude(text)
        conn.execute(
            'UPDATE bloggers SET last_reply_at=?, reply_sentiment=? WHERE id=?',
            (now_iso, sentiment, bid)
        )
        if sentiment == 'positive':
            conn.execute("UPDATE bloggers SET status='interested' WHERE id=?", (bid,))
            conn.commit()
            _send_blogger_email(blogger, 'second', conn)
            conn.commit()
        elif sentiment == 'negative':
            conn.execute("UPDATE bloggers SET status='declined' WHERE id=?", (bid,))
            conn.commit()
            _notify_admin(
                f'Блогер {blogger["name"]} отказал',
                f'Email: {blogger["email"]}\n\nОтвет:\n{text}'
            )
        else:
            conn.execute("UPDATE bloggers SET status='replied' WHERE id=?", (bid,))
            conn.commit()
            draft = _draft_reply_with_claude(blogger['name'], text)
            _notify_admin(
                f'Блогер {blogger["name"]} задал вопрос',
                f'Email: {blogger["email"]}\n\nОтвет блогера:\n{text}\n\n---\nЧерновик ответа:\n{draft}'
            )
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status) VALUES (?,?,?,?)',
            (bid, 'inbound', now_fmt, sentiment)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return '', 200


@main.route('/api/v1/check-blogger', methods=['GET'])
def api_check_blogger():
    token = os.environ.get('WEBHOOK_SECRET', '')
    if token and request.headers.get('X-Vera-Token') != token:
        return 'Forbidden', 403
    email = (request.args.get('email') or '').strip().lower()
    username = (request.args.get('username') or '').strip().lstrip('@').lower()
    if not email and not username:
        return {'found': False, 'error': 'email or username required'}, 400
    try:
        from .db import get_db
        conn = get_db()
        blogger = None
        if email:
            blogger = conn.execute(
                'SELECT * FROM bloggers WHERE LOWER(email)=?', (email,)
            ).fetchone()
        if not blogger and username:
            blogger = conn.execute(
                'SELECT * FROM bloggers WHERE LOWER(ig_username)=? OR LOWER(tg_username)=?',
                (username, username)
            ).fetchone()
        conn.close()
        if not blogger:
            return {'found': False}, 200
        b = dict(blogger)
        contacted = b.get('status', 'new') != 'new'
        return {
            'found': True,
            'contacted': contacted,
            'blogger_id': b['id'],
            'name': b['name'],
            'status': b['status'],
            'channel': b.get('channel', 'email'),
        }, 200
    except Exception:
        return {'found': False}, 200


def _parse_timestamp(ts):
    """Convert Unix timestamp (seconds or milliseconds) to UTC ISO string.

    Instagram Messaging API sends ms, Telegram sends seconds.
    Heuristic: if value > 1e12, treat as milliseconds.
    """
    try:
        ts_float = float(ts)
        if ts_float > 1e12:
            ts_float /= 1000.0
        return datetime.fromtimestamp(ts_float, tz=timezone.utc).replace(tzinfo=None).isoformat()
    except Exception:
        logger.warning(f'_parse_timestamp: cannot parse {ts!r}, falling back to utcnow')
        return datetime.utcnow().isoformat()


# ── Instagram & Telegram webhooks ────────────────────────────────────────────

@main.route('/webhook/instagram/health')
def webhook_instagram_health():
    return {'status': 'ok', 'channel': 'instagram'}, 200


@main.route('/webhook/telegram/health')
def webhook_telegram_health():
    return {'status': 'ok', 'channel': 'telegram'}, 200


@main.route('/webhook/instagram', methods=['GET', 'POST'])
def webhook_instagram():
    if request.method == 'GET':
        mode = request.args.get('hub.mode', '')
        verify_token = request.args.get('hub.verify_token', '')
        challenge = request.args.get('hub.challenge', '')
        expected = os.environ.get('META_VERIFY_TOKEN', '')
        if mode == 'subscribe' and expected and verify_token == expected:
            return challenge, 200, {'Content-Type': 'text/plain'}
        logger.warning(f'instagram verify failed: mode={mode} token_match={verify_token == expected}')
        return 'Forbidden', 403

    # POST — validate HMAC SHA256
    logger.warning(f'instagram webhook POST received: ua={request.headers.get("User-Agent","")[:60]}')
    app_secret = os.environ.get('META_APP_SECRET', '')
    if app_secret:
        raw_body = request.get_data()
        sig_header = request.headers.get('X-Hub-Signature-256', '')
        if not sig_header.startswith('sha256='):
            logger.warning('instagram webhook: missing X-Hub-Signature-256')
            return 'Forbidden', 403
        expected_sig = 'sha256=' + hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected_sig):
            logger.warning('instagram webhook: HMAC mismatch')
            return 'Forbidden', 403
    else:
        logger.warning('instagram webhook: META_APP_SECRET not set, skipping HMAC check')

    try:
        payload = request.get_json(force=True, silent=True) or {}
        for entry in payload.get('entry', []):
            # DM messages — full processing pipeline
            for msg_event in entry.get('messaging', []):
                try:
                    sender = msg_event.get('sender') or {}
                    recipient = msg_event.get('recipient') or {}
                    message = msg_event.get('message') or {}
                    if message.get('is_echo'):
                        continue
                    sender_id = sender.get('id', '')
                    recipient_id = recipient.get('id', '')
                    text = (message.get('text') or '').strip()
                    message_id = message.get('mid')
                    timestamp = msg_event.get('timestamp')
                    received_at = _parse_timestamp(timestamp) if timestamp is not None else datetime.utcnow().isoformat()
                    logger.info(
                        f'instagram DM: sender={sender_id} recipient={recipient_id} '
                        f'mid={message_id} ts_raw={timestamp} text_len={len(text)}'
                    )
                    if not sender_id or not text:
                        continue
                    store_incoming_message(
                        channel='instagram',
                        external_id=sender_id,
                        text=text,
                        raw_payload=msg_event,
                        received_at=received_at,
                        message_id=message_id,
                        extra={'ig_username': sender.get('username', '')},
                    )
                except Exception:
                    logger.exception('error processing instagram DM event')
            # Comments — log only, not processed in this iteration
            for change in entry.get('changes', []):
                if change.get('field') == 'comments':
                    logger.debug(f'instagram comment event (not processed): {json.dumps(change)[:300]}')
    except Exception:
        logger.exception('instagram webhook error')

    return '', 200


@main.route('/webhook/telegram', methods=['POST'])
def webhook_telegram():
    secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
    if secret and request.headers.get('X-Telegram-Bot-Api-Secret-Token') != secret:
        logger.warning('telegram webhook: secret token mismatch')
        return 'Forbidden', 403

    try:
        payload = request.get_json(force=True, silent=True) or {}
        message = payload.get('message') or payload.get('edited_message') or {}
        chat = message.get('chat') or {}
        from_user = message.get('from') or {}
        chat_id = str(chat.get('id', ''))
        user_id = str(from_user.get('id', ''))
        tg_username = (from_user.get('username') or '').strip().lstrip('@').lower()
        text = (message.get('text') or '').strip()
        raw_msg_id = message.get('message_id')
        message_id = str(raw_msg_id) if raw_msg_id is not None else None
        date = message.get('date')
        received_at = _parse_timestamp(date) if date is not None else datetime.utcnow().isoformat()
        if not chat_id or not text:
            return '', 200
        external_id = user_id or chat_id
        store_incoming_message(
            channel='telegram',
            external_id=external_id,
            text=text,
            raw_payload=payload,
            received_at=received_at,
            message_id=message_id,
            extra={'tg_username': tg_username},
        )
    except Exception:
        logger.exception('telegram webhook error')

    return '', 200


@main.route('/webhook/save-ig-id', methods=['POST'])
def webhook_save_ig_id():
    token = os.environ.get('WEBHOOK_SECRET', '')
    if token and request.headers.get('X-Vera-Token') != token:
        return 'Forbidden', 403
    try:
        payload = request.get_json(force=True, silent=True) or {}
        ig_username = (payload.get('ig_username') or payload.get('username') or '').strip().lstrip('@').lower()
        ig_user_id = (payload.get('ig_user_id') or payload.get('psid') or '').strip()
        if not ig_username or not ig_user_id:
            return '', 200
        from .db import get_db
        conn = get_db()
        blogger = conn.execute(
            "SELECT id, ig_user_id FROM bloggers WHERE LOWER(ig_username)=?", (ig_username,)
        ).fetchone()
        if blogger and not blogger['ig_user_id']:
            conn.execute(
                "UPDATE bloggers SET ig_user_id=? WHERE id=?", (ig_user_id, blogger['id'])
            )
            conn.commit()
        conn.close()
    except Exception:
        pass
    return '', 200


@main.route('/admin/bloggers/templates')
def admin_bloggers_templates():
    if not _admin_required():
        return redirect(url_for('main.admin_login'))
    from .db import get_db
    conn = get_db()
    _ensure_email_templates_table(conn)
    t1 = conn.execute("SELECT key, subject, body_text FROM email_templates WHERE key='blogger_first'").fetchone()
    t2 = conn.execute("SELECT key, subject, body_text FROM email_templates WHERE key='blogger_second'").fetchone()
    t3 = conn.execute("SELECT key, subject, body_text FROM email_templates WHERE key='blogger_third'").fetchone()
    conn.close()
    return render_template('admin_bloggers_templates.html', t1=t1, t2=t2, t3=t3)


@main.route('/admin/bloggers/templates/save', methods=['POST'])
def admin_bloggers_templates_save():
    if not _admin_required():
        return 'Forbidden', 403
    key = request.form.get('key', '')
    if key not in ('blogger_first', 'blogger_second', 'blogger_third'):
        return 'Bad key', 400
    subject = request.form.get('subject', '').strip()[:500]
    body_text = request.form.get('body_text', '').strip()[:10000]
    if not subject or not body_text:
        return 'Пустые поля', 400
    from .db import get_db
    conn = get_db()
    _ensure_email_templates_table(conn)
    conn.execute(
        'INSERT OR REPLACE INTO email_templates (key, subject, body_text) VALUES (?, ?, ?)',
        (key, subject, body_text)
    )
    conn.commit()
    conn.close()
    return '', 200


# ─── Partner Cabinet ────────────────────────────────────────────

PARTNER_TOKEN_HOURS = 72

def _partner_magic_link_email(name, link):
    return f'''<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#FAF7F2;font-family:Helvetica,Arial,sans-serif;">
<div style="max-width:480px;margin:0 auto;padding:40px 24px;">
  <div style="font-family:Georgia,serif;font-size:22px;color:#2A2118;margin-bottom:32px;">vere<span style="color:#A67C52;">very</span></div>
  <div style="background:#fff;border:1px solid #EDE6DA;border-radius:20px;padding:32px 28px;">
    <h2 style="font-family:Georgia,serif;font-size:20px;color:#2A2118;margin:0 0 16px">Привет, {name}! 👋</h2>
    <p style="color:#5C4A36;line-height:1.7;margin:0 0 24px">Катя приглашает тебя в личный кабинет партнёра verevery.ru — там ты найдёшь свою статистику, историю продаж и материалы для постов.</p>
    <a href="{link}" style="display:inline-block;background:#2A2118;color:#FAF7F2;text-decoration:none;padding:14px 28px;border-radius:50px;font-size:14px;font-weight:500;">Войти в кабинет →</a>
    <p style="color:#A0927E;font-size:12px;margin:24px 0 0">Ссылка действует 72 часа. Если ты не ожидала это письмо — просто проигнорируй его.</p>
  </div>
</div>
</body></html>'''

def _send_partner_invite(blogger, base_url):
    import secrets, resend
    from datetime import timedelta
    from .db import get_db
    resend.api_key = os.environ.get('RESEND_API_KEY', '')
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=PARTNER_TOKEN_HOURS)).isoformat()
    conn = get_db()
    conn.execute('DELETE FROM partner_tokens WHERE blogger_id=? AND used=0', (blogger['id'],))
    conn.execute('INSERT INTO partner_tokens (token, blogger_id, expires_at) VALUES (?,?,?)',
                 (token, blogger['id'], expires))
    conn.commit()
    conn.close()
    link = f"{base_url}/partner/auth?token={token}"
    html = _partner_magic_link_email(blogger['name'], link)
    try:
        resend.Emails.send({
            'from': 'Vera <team@verevery.ru>',
            'to': [blogger['email']],
            'subject': 'Твой личный кабинет партнёра verevery.ru',
            'html': html,
            'reply_to': os.environ.get('REPLY_TO_EMAIL', 'team.verevery@gmail.com'),
        })
        return True, None
    except Exception as e:
        return False, str(e)[:300]


@main.route('/admin/bloggers/<int:bid>/send-partner-invite', methods=['POST'])
def admin_send_partner_invite(bid):
    if not _admin_required():
        return 'Forbidden', 403
    from .db import get_db
    conn = get_db()
    blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (bid,)).fetchone()
    conn.close()
    if not blogger:
        return 'Блогер не найден', 404
    blogger = dict(blogger)
    if not blogger.get('email'):
        return 'У блогера нет email', 400
    base_url = os.environ.get('BASE_URL', 'https://verevery.ru')
    ok, err = _send_partner_invite(blogger, base_url)
    return ('', 200) if ok else (f'Ошибка: {err}', 500)


@main.route('/partner')
def partner_index():
    if not session.get('partner_id'):
        return redirect(url_for('main.partner_login'))
    return redirect(url_for('main.partner_dashboard'))


@main.route('/partner/login', methods=['GET', 'POST'])
def partner_login():
    if session.get('partner_id'):
        return redirect(url_for('main.partner_dashboard'))
    error = ''
    sent = False
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email or '@' not in email:
            error = 'Введите корректный email'
        else:
            from .db import get_db
            conn = get_db()
            blogger = conn.execute(
                "SELECT * FROM bloggers WHERE LOWER(email)=? AND status NOT IN ('new')",
                (email,)
            ).fetchone()
            conn.close()
            if blogger:
                base_url = os.environ.get('BASE_URL', 'https://verevery.ru')
                _send_partner_invite(dict(blogger), base_url)
            sent = True  # always show "check email" to avoid enumeration
    return render_template('partner_login.html', error=error, sent=sent)


@main.route('/partner/auth')
def partner_auth():
    token = request.args.get('token', '').strip()
    if not token:
        return redirect(url_for('main.partner_login'))
    from .db import get_db
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM partner_tokens WHERE token=? AND used=0', (token,)
    ).fetchone()
    if not row:
        conn.close()
        return render_template('partner_login.html', error='Ссылка недействительна или уже использована', sent=False)
    if datetime.fromisoformat(row['expires_at']) < datetime.utcnow():
        conn.close()
        return render_template('partner_login.html', error='Ссылка истекла — запросите новую', sent=False)
    conn.execute('UPDATE partner_tokens SET used=1 WHERE token=?', (token,))
    conn.commit()
    conn.close()
    session['partner_id'] = row['blogger_id']
    session.permanent = True
    return redirect(url_for('main.partner_dashboard'))


@main.route('/partner/logout')
def partner_logout():
    session.pop('partner_id', None)
    return redirect(url_for('main.partner_login'))


@main.route('/partner/open-cards')
def partner_open_cards():
    """Give blogger full access to the card deck and redirect them there."""
    pid = session.get('partner_id')
    if not pid:
        return redirect(url_for('main.partner_login'))
    from .db import get_db
    conn = get_db()
    blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (pid,)).fetchone()
    if not blogger or not blogger['email']:
        conn.close()
        return redirect(url_for('main.partner_dashboard'))
    blogger = dict(blogger)
    email = blogger['email'].strip().lower()
    _upsert_user(conn, email)
    conn.close()
    conn2 = get_db()
    try:
        _send_magic_link(email, conn2)
    finally:
        conn2.close()
    return render_template('partner_login.html',
        sent=True,
        cards_hint=True,
        error=None
    )


@main.route('/partner/dashboard')
def partner_dashboard():
    pid = session.get('partner_id')
    if not pid:
        return redirect(url_for('main.partner_login'))
    from .db import get_db
    conn = get_db()
    blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (pid,)).fetchone()
    if not blogger:
        session.pop('partner_id', None)
        conn.close()
        return redirect(url_for('main.partner_login'))
    blogger = dict(blogger)
    utm = blogger['utm_slug'] or ''

    now = datetime.utcnow()
    month_start = now.strftime('%Y-%m-01')
    today = now.strftime('%Y-%m-%d')

    # Sales stats
    def q(sql, *args):
        row = conn.execute(sql, args).fetchone()
        return dict(row) if row else {}

    s_all = q("SELECT COUNT(*) cnt, COALESCE(SUM(commission),0) comm FROM sales WHERE utm=?", utm)
    s_month = q("SELECT COUNT(*) cnt, COALESCE(SUM(commission),0) comm FROM sales WHERE utm=? AND date>=?", utm, month_start)
    s_today = q("SELECT COUNT(*) cnt, COALESCE(SUM(commission),0) comm FROM sales WHERE utm=? AND date LIKE ?", utm, today+'%')

    # Click stats
    c_all = conn.execute("SELECT COUNT(*) cnt FROM link_clicks WHERE utm_slug=?", (utm,)).fetchone()['cnt']
    c_month = conn.execute("SELECT COUNT(*) cnt FROM link_clicks WHERE utm_slug=? AND visited_at>=?", (utm, month_start)).fetchone()['cnt']
    c_today = conn.execute("SELECT COUNT(*) cnt FROM link_clicks WHERE utm_slug=? AND date(visited_at)=?", (utm, today)).fetchone()['cnt']

    # Payments
    total_earned = int(s_all.get('comm', 0))
    paid_out = blogger.get('paid_out') or 0
    balance = max(0, total_earned - paid_out)

    # Recent sales
    recent = conn.execute(
        "SELECT date, amount, commission FROM sales WHERE utm=? ORDER BY id DESC LIMIT 10", (utm,)
    ).fetchall()
    recent = [dict(r) for r in recent]

    # Conversion
    conversion = round(s_all['cnt'] / c_all * 100, 1) if c_all else 0

    conn.close()
    base_url = os.environ.get('BASE_URL', 'https://verevery.ru')
    utm_link = blogger.get('utm_link') or f"{base_url}/free?utm={utm}"

    return render_template('partner_dashboard.html',
        blogger=blogger,
        utm_link=utm_link,
        s_all=s_all, s_month=s_month, s_today=s_today,
        c_all=c_all, c_month=c_month, c_today=c_today,
        total_earned=total_earned,
        paid_out=paid_out,
        balance=balance,
        recent=recent,
        conversion=conversion,
    )


@main.route('/partner/sales')
def partner_sales():
    pid = session.get('partner_id')
    if not pid:
        return redirect(url_for('main.partner_login'))
    from .db import get_db
    conn = get_db()
    blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (pid,)).fetchone()
    if not blogger:
        session.pop('partner_id', None)
        conn.close()
        return redirect(url_for('main.partner_login'))
    blogger = dict(blogger)
    utm = blogger['utm_slug'] or ''

    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')

    query = "SELECT date, amount, commission FROM sales WHERE utm=?"
    params = [utm]
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to + 'T23:59:59')
    query += " ORDER BY id DESC"

    sales = [dict(r) for r in conn.execute(query, params).fetchall()]
    total_comm = sum(s['commission'] for s in sales)
    conn.close()
    return render_template('partner_sales.html',
        blogger=blogger, sales=sales,
        total_comm=int(total_comm),
        date_from=date_from, date_to=date_to,
    )


@main.route('/partner/payments')
def partner_payments():
    pid = session.get('partner_id')
    if not pid:
        return redirect(url_for('main.partner_login'))
    from .db import get_db
    conn = get_db()
    blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (pid,)).fetchone()
    if not blogger:
        session.pop('partner_id', None)
        conn.close()
        return redirect(url_for('main.partner_login'))
    blogger = dict(blogger)
    utm = blogger['utm_slug'] or ''

    payments = [dict(r) for r in conn.execute(
        'SELECT * FROM partner_payments WHERE blogger_id=? ORDER BY paid_date DESC', (pid,)
    ).fetchall()]

    total_earned_row = conn.execute(
        "SELECT COALESCE(SUM(commission),0) s FROM sales WHERE utm=?", (utm,)
    ).fetchone()
    total_earned = int(total_earned_row['s'])
    paid_out = blogger.get('paid_out') or 0
    balance = max(0, total_earned - paid_out)
    conn.close()

    from datetime import date
    today = date.today()
    if today.day <= 15:
        next_payment = today.replace(day=15).isoformat()
    else:
        if today.month == 12:
            next_payment = today.replace(year=today.year+1, month=1, day=15).isoformat()
        else:
            next_payment = today.replace(month=today.month+1, day=15).isoformat()

    return render_template('partner_payments.html',
        blogger=blogger,
        payments=payments,
        total_earned=total_earned,
        paid_out=paid_out,
        balance=balance,
        next_payment=next_payment,
    )


@main.route('/admin/bloggers/<int:bid>/add-payment', methods=['POST'])
def admin_add_payment(bid):
    if not _admin_required():
        return 'Forbidden', 403
    amount = request.form.get('amount', '').strip()
    paid_date = request.form.get('paid_date', '').strip()
    method = request.form.get('method', '').strip()[:100]
    note = request.form.get('note', '').strip()[:500]
    if not amount or not paid_date:
        return 'Сумма и дата обязательны', 400
    try:
        amount = int(float(amount))
    except ValueError:
        return 'Некорректная сумма', 400
    from .db import get_db
    conn = get_db()
    conn.execute(
        'INSERT INTO partner_payments (blogger_id, amount, paid_date, method, note) VALUES (?,?,?,?,?)',
        (bid, amount, paid_date, method, note)
    )
    # update paid_out total on blogger
    conn.execute('UPDATE bloggers SET paid_out = paid_out + ? WHERE id=?', (amount, bid))
    conn.commit()
    conn.close()
    return '', 200


def _magic_link_email(link):
    return f'''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#FAF7F2;font-family:Helvetica,Arial,sans-serif;">
<div style="max-width:480px;margin:0 auto;padding:40px 24px;">
  <div style="font-family:Georgia,serif;font-size:22px;color:#2A2118;margin-bottom:32px;">
    vere<span style="color:#A67C52;">very</span>
  </div>
  <div style="background:#FFFFFF;border:1px solid #EDE6DA;border-radius:20px;padding:32px 28px;">
    <div style="font-family:Georgia,serif;font-size:26px;color:#2A2118;margin-bottom:12px;line-height:1.25;">
      Ваша колода готова
    </div>
    <p style="font-size:14px;font-weight:300;color:#8C7E72;line-height:1.7;margin:0 0 28px;">
      Нажмите кнопку ниже, чтобы войти в колоду «Ближе».<br>Ссылка действует 24 часа.
    </p>
    <a href="{link}"
       style="display:block;text-align:center;background:#2A2118;color:#FFFFFF;
              text-decoration:none;padding:16px 24px;border-radius:50px;
              font-size:14px;font-weight:500;letter-spacing:0.5px;">
      Открыть колоду
    </a>
    <p style="font-size:11px;color:#D4C8B5;text-align:center;margin:20px 0 0;line-height:1.6;">
      Если кнопка не открывается:<br>
      <a href="{link}" style="color:#A67C52;word-break:break-all;">{link}</a>
    </p>
  </div>
  <p style="font-size:11px;color:#D4C8B5;text-align:center;margin-top:24px;line-height:1.6;">
    Если вы не совершали покупку — просто проигнорируйте это письмо.
  </p>
</div>
</body>
</html>'''
