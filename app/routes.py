import json
import os
import secrets

import uuid
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, session, request

main = Blueprint('main', __name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BASE_URL = os.environ.get('BASE_URL', 'https://verevery.ru')
SHOP_ID = os.environ.get('SHOP_ID', '1343976')
SHEET_ID = '11mZ-sB0H7OiaF9yv2iCiTlA3vkMJW8u9D9ypuf4QeAs'

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
    conn.execute('DELETE FROM magic_tokens WHERE email=? AND used=0', (email,))
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
        'amount': {'value': '1.00', 'currency': 'RUB'},
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
                'amount': {'value': '1.00', 'currency': 'RUB'},
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

        email = (payment.metadata or {}).get('email', '')
        utm = (payment.metadata or {}).get('utm', 'direct')
        amount = str(payment.amount.value)
        date = datetime.utcnow().strftime('%d.%m.%Y %H:%M')

        if not email:
            return '', 200

        from .db import get_db
        conn = get_db()
        conn.execute('INSERT OR IGNORE INTO users (email) VALUES (?)', (email,))
        conn.execute('UPDATE users SET has_access=1 WHERE email=?', (email,))
        conn.commit()
        _send_magic_link(email, conn)
        _save_sale(conn, payment.id, date, email, utm, amount)
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
    return render_template('cards.html', blocks=blocks)


@main.route('/debug/health')
def debug_health():
    import traceback
    results = {}
    try:
        from .db import get_db
        conn = get_db()
        conn.execute('SELECT 1 FROM sales LIMIT 1')
        results['sales_table'] = 'ok'
        conn.execute('SELECT 1 FROM users LIMIT 1')
        results['users_table'] = 'ok'
        conn.close()
    except Exception:
        results['db_error'] = traceback.format_exc()
    try:
        load_block('action')
        results['json_files'] = 'ok'
    except Exception:
        results['json_error'] = traceback.format_exc()
    try:
        get_free_card_ids()
        results['free_cards'] = 'ok'
    except Exception:
        results['free_cards_error'] = traceback.format_exc()
    import json as _json
    return '<pre>' + _json.dumps(results, ensure_ascii=False, indent=2) + '</pre>'


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
        conn.execute('INSERT OR IGNORE INTO users (email) VALUES (?)', (email,))
        conn.commit()
        _send_magic_link(email, conn)
        conn.close()
        return render_template('auth.html', sent=True, email=email)

    return render_template('auth.html')


@main.route('/auth/verify')
def auth_verify():
    token = request.args.get('token', '')
    if not token:
        return redirect(url_for('main.auth'))

    try:
        from .db import get_db
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM magic_tokens WHERE token=? AND used=0 AND expires_at > ?',
            (token, datetime.utcnow().isoformat())
        ).fetchone()

        if not row:
            conn.close()
            return render_template('auth.html', token_expired=True)

        conn.execute('INSERT OR IGNORE INTO users (email) VALUES (?)', (row['email'],))
        user = conn.execute('SELECT * FROM users WHERE email=?', (row['email'],)).fetchone()
        conn.execute('UPDATE magic_tokens SET used=1 WHERE token=?', (token,))
        conn.commit()
        conn.close()

        session.permanent = True
        session['user_id'] = user['id']
        session['email'] = user['email']
        return redirect(url_for('main.cards'))
    except Exception:
        return render_template('auth.html', token_expired=True)


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
        'SELECT id, email, has_access, created_at FROM users ORDER BY id DESC LIMIT 50'
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
        'SELECT date, email, utm, blogger, amount, commission FROM sales ORDER BY id DESC LIMIT 200'
    ).fetchall()
    conn.close()
    return render_template('admin.html', blocks=blocks_data, users=users,
                           blogger_stats=blogger_stats, sales=sales,
                           all_cards=all_cards_flat, free_ids=free_ids)


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
        conn.execute('INSERT OR IGNORE INTO users (email) VALUES (?)', (email,))
        conn.execute('UPDATE users SET has_access=1 WHERE email=?', (email,))
        conn.commit()
        _send_magic_link(email, conn)
        conn.close()
        return 'OK', 200
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