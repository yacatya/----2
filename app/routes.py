import json
import os
import re as _re
import secrets
import uuid
from datetime import datetime, timedelta

import requests

from flask import Blueprint, render_template, redirect, url_for, session, request

main = Blueprint('main', __name__)

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
    """Insert user if not exists (compatible with password_hash NOT NULL schema), then grant access."""
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
    """Return True if status is sent/replied, 3+ days passed, no reply yet."""
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
    """Send first or second outreach email. Returns (ok, error_msg)."""
    import resend
    resend.api_key = os.environ.get('RESEND_API_KEY', '')
    template_key = 'blogger_first' if email_type == 'first' else 'blogger_second'
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


def _send_via_make(blogger, email_type, conn):
    """Send outreach via Make webhook (any channel). Returns (ok, error_msg)."""
    webhook = os.environ.get('MAKE_OUTBOUND_WEBHOOK', '').strip()
    now_fmt = datetime.utcnow().strftime('%d.%m.%Y %H:%M')
    channel = (blogger.get('channel') or 'email').lower()
    if not webhook:
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status, error) VALUES (?,?,?,?,?)',
            (blogger['id'], email_type, now_fmt, 'error', 'MAKE_OUTBOUND_WEBHOOK not set')
        )
        return False, 'MAKE_OUTBOUND_WEBHOOK не настроен'
    if channel == 'instagram':
        recipient = blogger.get('ig_username') or ''
    elif channel == 'telegram':
        recipient = blogger.get('tg_username') or ''
    else:
        recipient = blogger.get('email') or ''
    if not recipient:
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status, error) VALUES (?,?,?,?,?)',
            (blogger['id'], email_type, now_fmt, 'error', f'recipient for {channel} not set')
        )
        return False, f'контакт для {channel} не указан'
    template_key = 'blogger_first' if email_type == 'first' else 'blogger_second'
    subject, body_text = _get_template(conn, template_key)
    text = body_text.replace('{name}', blogger['name']).replace('{utm_link}', blogger.get('utm_link') or '')
    html = _render_email_html(body_text, blogger['name'], blogger.get('utm_link') or '')
    payload = {
        'channel': channel,
        'blogger_id': blogger['id'],
        'blogger_name': blogger['name'],
        'recipient': recipient,
        'email': blogger.get('email') or '',
        'ig_username': blogger.get('ig_username') or '',
        'tg_username': blogger.get('tg_username') or '',
        'subject': subject,
        'text': text,
        'html': html,
        'from_email': 'team@verevery.ru',
        'reply_to': REPLY_TO_EMAIL,
        'email_type': email_type,
        'utm_link': blogger.get('utm_link') or '',
    }
    try:
        r = requests.post(webhook, json=payload, timeout=15)
        ok = 200 <= r.status_code < 300
        if ok:
            conn.execute(
                'INSERT INTO email_log (blogger_id, type, sent_at, status) VALUES (?,?,?,?)',
                (blogger['id'], email_type, now_fmt, 'ok')
            )
            return True, None
        err = f'HTTP {r.status_code}: {r.text[:200]}'
        conn.execute(
            'INSERT INTO email_log (blogger_id, type, sent_at, status, error) VALUES (?,?,?,?,?)',
            (blogger['id'], email_type, now_fmt, 'error', err)
        )
        return False, err
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
    email_templates = {
        'first': t1['body_text'] if t1 else '',
        'second': t2['body_text'] if t2 else '',
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
    channel = request.form.get('channel', 'email').strip().lower()
    if channel not in ('email', 'instagram', 'telegram'):
        channel = 'email'
    ig_username = request.form.get('ig_username', '').strip().lstrip('@')[:100]
    tg_username = request.form.get('tg_username', '').strip().lstrip('@')[:100]
    try:
        from .db import get_db
        conn = get_db()
        conn.execute(
            'INSERT INTO bloggers (name, platform, profile_url, email, utm_slug, utm_link, notes, '
            'channel, ig_username, tg_username) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (name, platform, profile_url, email, utm_slug, utm_link, notes,
             channel, ig_username, tg_username)
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
               'channel', 'ig_username', 'tg_username'}
    updates = {k: request.form[k].strip() for k in allowed if k in request.form}
    if 'ig_username' in updates:
        updates['ig_username'] = updates['ig_username'].lstrip('@')[:100]
    if 'tg_username' in updates:
        updates['tg_username'] = updates['tg_username'].lstrip('@')[:100]
    if 'channel' in updates and updates['channel'].lower() not in ('email', 'instagram', 'telegram'):
        updates['channel'] = 'email'
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
    blogger = conn.execute('SELECT * FROM bloggers WHERE id=?', (bid,)).fetchone()
    if not blogger:
        conn.close()
        return 'Блогер не найден', 404
    blogger = dict(blogger)
    ok, err = _send_via_make(blogger, email_type, conn)
    if ok and email_type == 'first':
        conn.execute(
            "UPDATE bloggers SET status='sent', first_email_sent_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), bid)
        )
    conn.commit()
    conn.close()
    return ('', 200) if ok else (f'Ошибка: {err}', 500)


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
        if not b:
            continue
        ok, err = _send_via_make(dict(b), 'first', conn)
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


@main.route('/webhook/reply', methods=['POST'])
@main.route('/webhook/email-reply', methods=['POST'])
def webhook_reply():
    secret = os.environ.get('WEBHOOK_SECRET', '')
    if secret and request.args.get('secret') != secret:
        return 'Forbidden', 403
    try:
        payload = request.get_json(force=True, silent=True) or {}
        data = payload.get('data', payload)
        channel = (data.get('channel') or '').strip().lower()
        sender = (data.get('from') or data.get('sender') or '').strip()
        text = (data.get('text') or data.get('plain_text') or data.get('message') or '').strip()
        if not sender or not text:
            return '', 200
        if not channel:
            channel = 'email' if '@' in sender else 'unknown'
        from .db import get_db
        conn = get_db()
        if channel == 'email':
            blogger = conn.execute(
                'SELECT * FROM bloggers WHERE LOWER(email)=?', (sender.lower(),)
            ).fetchone()
        elif channel == 'instagram':
            handle = sender.lstrip('@').lower()
            blogger = conn.execute(
                'SELECT * FROM bloggers WHERE LOWER(ig_username)=?', (handle,)
            ).fetchone()
        elif channel == 'telegram':
            handle = sender.lstrip('@').lower()
            blogger = conn.execute(
                'SELECT * FROM bloggers WHERE LOWER(tg_username)=?', (handle,)
            ).fetchone()
        else:
            blogger = None
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
        contact_info = f'Канал: {channel}\nКонтакт: {sender}'
        if sentiment == 'positive':
            conn.execute("UPDATE bloggers SET status='interested' WHERE id=?", (bid,))
            conn.commit()
            _send_via_make(blogger, 'second', conn)
            conn.commit()
        elif sentiment == 'negative':
            conn.execute("UPDATE bloggers SET status='declined' WHERE id=?", (bid,))
            conn.commit()
            _notify_admin(
                f'Блогер {blogger["name"]} отказал',
                f'{contact_info}\n\nОтвет:\n{text}'
            )
        else:
            conn.execute("UPDATE bloggers SET status='replied' WHERE id=?", (bid,))
            conn.commit()
            draft = _draft_reply_with_claude(blogger['name'], text)
            _notify_admin(
                f'Блогер {blogger["name"]} задал вопрос',
                f'{contact_info}\n\nОтвет блогера:\n{text}\n\n---\nЧерновик ответа:\n{draft}'
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


@main.route('/admin/bloggers/templates')
def admin_bloggers_templates():
    if not _admin_required():
        return redirect(url_for('main.admin_login'))
    from .db import get_db
    conn = get_db()
    _ensure_email_templates_table(conn)
    t1 = conn.execute("SELECT key, subject, body_text FROM email_templates WHERE key='blogger_first'").fetchone()
    t2 = conn.execute("SELECT key, subject, body_text FROM email_templates WHERE key='blogger_second'").fetchone()
    conn.close()
    return render_template('admin_bloggers_templates.html', t1=t1, t2=t2)


@main.route('/admin/bloggers/templates/save', methods=['POST'])
def admin_bloggers_templates_save():
    if not _admin_required():
        return 'Forbidden', 403
    key = request.form.get('key', '')
    if key not in ('blogger_first', 'blogger_second'):
        return 'Bad key', 400
    subject = request.form.get('subject', '').strip()[:500]
    body_text = request.form.get('body_text', '').strip()[:5000]
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