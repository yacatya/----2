import json
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for,
                   session, request, jsonify, make_response)

main = Blueprint('main', __name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

FREE_CARD_IDS = ['А-02', 'З-03', 'В-03', 'В-11', 'З-01']

BLOCK_INFO = {
    'action':   {'label': 'ДЕЙСТВИЕ', 'color': 'var(--accent)',       'name': 'Действие'},
    'question': {'label': 'ВОПРОС',   'color': 'var(--muted)',        'name': 'Вопрос'},
    'care':     {'label': 'ЗАБОТА',   'color': 'var(--light-accent)', 'name': 'Забота'},
}

# ── Helpers ────────────────────────────────────────────────

def load_block(block):
    with open(os.path.join(DATA_DIR, f'cards_{block}.json'), encoding='utf-8') as f:
        return json.load(f)['cards']

def save_block(block, cards):
    path = os.path.join(DATA_DIR, f'cards_{block}.json')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data['cards'] = cards
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_content():
    with open(os.path.join(DATA_DIR, 'content.json'), encoding='utf-8') as f:
        return json.load(f)

def save_content(content):
    with open(os.path.join(DATA_DIR, 'content.json'), 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=2)

def send_magic_link(email, token):
    import resend
    resend.api_key = os.environ.get('RESEND_API_KEY', '')
    base_url = os.environ.get('BASE_URL', 'https://verevery.ru')
    link = f"{base_url}/auth/verify?token={token}"
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8">
<style>
  body {{ font-family: 'Georgia', serif; background: #FAF7F2; margin: 0; padding: 40px 20px; }}
  .wrap {{ max-width: 480px; margin: 0 auto; background: #fff;
           border-radius: 20px; padding: 40px 36px; border: 1px solid #EDE6DA; }}
  .logo {{ font-size: 22px; color: #2A2118; margin-bottom: 8px; }}
  .logo span {{ color: #A67C52; }}
  .label {{ font-family: sans-serif; font-size: 10px; letter-spacing: 2px;
             text-transform: uppercase; color: #D4C8B5; margin-bottom: 28px; display: block; }}
  h1 {{ font-size: 26px; font-weight: 500; color: #2A2118; margin-bottom: 12px; line-height: 1.3; }}
  p {{ font-family: sans-serif; font-size: 14px; font-weight: 300;
       line-height: 1.7; color: #8C7E72; margin-bottom: 28px; }}
  .btn {{ display: inline-block; padding: 16px 36px; background: #A67C52;
          color: #fff; text-decoration: none; border-radius: 50px;
          font-family: sans-serif; font-size: 14px; font-weight: 500; }}
  .link {{ font-family: sans-serif; font-size: 11px; color: #D4C8B5;
            margin-top: 24px; word-break: break-all; }}
  .footer {{ font-family: sans-serif; font-size: 11px; color: #D4C8B5;
              margin-top: 32px; padding-top: 20px; border-top: 1px solid #EDE6DA; }}
</style></head>
<body><div class="wrap">
  <div class="logo">vere<span>very</span></div>
  <span class="label">Вход в колоду</span>
  <h1>Ваша ссылка для входа</h1>
  <p>Нажмите кнопку ниже, чтобы войти в свою колоду.<br>
     Ссылка действует 24 часа.</p>
  <a href="{link}" class="btn">Открыть колоду →</a>
  <div class="link">Или скопируйте ссылку: {link}</div>
  <div class="footer">Если вы не запрашивали вход — просто проигнорируйте это письмо.</div>
</div></body></html>"""

    resend.Emails.send({
        "from": os.environ.get('RESEND_FROM', 'noreply@verevery.ru'),
        "to": [email],
        "subject": "Ваша ссылка для входа — verevery",
        "html": html,
    })

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('main.admin_login'))
        return f(*args, **kwargs)
    return decorated

# ── Public routes ──────────────────────────────────────────

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
    for cid in FREE_CARD_IDS:
        if cid in id_map:
            block, card = id_map[cid]
            free_cards.append({**card, 'block': block, **BLOCK_INFO[block]})
    content = load_content()
    return render_template('free.html', cards=free_cards, c=content['free'])

@main.route('/buy')
def buy():
    content = load_content()
    return render_template('buy.html', c=content['buy'])

@main.route('/cards')
def cards():
    if 'user_id' not in session:
        return redirect(url_for('main.auth'))
    blocks = {}
    for block, info in BLOCK_INFO.items():
        blocks[block] = {**info, 'cards': load_block(block)}
    return render_template('cards.html', blocks=blocks)

# ── Auth routes ─────────────────────────────────────────────

@main.route('/auth')
def auth():
    if 'user_id' in session:
        return redirect(url_for('main.cards'))
    return render_template('auth.html', step='email', error=None)

@main.route('/auth/send', methods=['POST'])
def auth_send():
    from .db import get_db
    email = request.form.get('email', '').strip().lower()
    if not email or '@' not in email:
        return render_template('auth.html', step='email', error='Введите корректный email')

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=24)

    db = get_db()
    # clean up old unused tokens for this email
    db.execute("DELETE FROM magic_tokens WHERE email = ? AND used = 0", (email,))
    db.execute(
        "INSERT INTO magic_tokens (email, token, expires_at) VALUES (?, ?, ?)",
        (email, token, expires_at.isoformat())
    )
    db.commit()
    db.close()

    try:
        send_magic_link(email, token)
    except Exception as e:
        return render_template('auth.html', step='email',
                               error=f'Ошибка отправки письма. Попробуйте ещё раз.')

    return render_template('auth.html', step='sent', email=email)

@main.route('/auth/verify')
def auth_verify():
    from .db import get_db
    token = request.args.get('token', '')
    if not token:
        return render_template('auth.html', step='email', error='Ссылка недействительна')

    db = get_db()
    row = db.execute(
        "SELECT * FROM magic_tokens WHERE token = ? AND used = 0",
        (token,)
    ).fetchone()

    if not row:
        db.close()
        return render_template('auth.html', step='email',
                               error='Ссылка уже использована или недействительна')

    if datetime.utcnow() > datetime.fromisoformat(row['expires_at']):
        db.execute("DELETE FROM magic_tokens WHERE token = ?", (token,))
        db.commit()
        db.close()
        return render_template('auth.html', step='email',
                               error='Ссылка истекла. Запросите новую.')

    email = row['email']
    # mark token as used
    db.execute("UPDATE magic_tokens SET used = 1 WHERE token = ?", (token,))
    # upsert user
    db.execute("INSERT OR IGNORE INTO users (email) VALUES (?)", (email,))
    db.commit()
    user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    db.close()

    session.permanent = True
    session['user_id'] = user['id']
    session['user_email'] = email
    return redirect(url_for('main.cards'))

@main.route('/auth/logout')
def auth_logout():
    session.pop('user_id', None)
    session.pop('user_email', None)
    return redirect(url_for('main.free'))

# ── Webhook ЮКассы ───────────────────────────────────────────

def _yukassa_fetch_payment(payment_id):
    """Получить платёж из ЮКассы по ID для верификации."""
    import base64
    import urllib.request
    shop_id = os.environ.get('YUKASSA_SHOP_ID', '')
    secret_key = os.environ.get('YUKASSA_SECRET_KEY', '')
    if not shop_id or not secret_key:
        return None
    token = base64.b64encode(f"{shop_id}:{secret_key}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.yookassa.ru/v3/payments/{payment_id}",
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"YuKassa API error: {e}")
        return None

@main.route('/webhook/payment', methods=['POST'])
def webhook_payment():
    from .db import get_db
    from .sheets import append_sale

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'ok': False}), 400

    event = data.get('event', '')
    obj = data.get('object', {})
    payment_id = obj.get('id', '')

    if event != 'payment.succeeded' or not payment_id:
        return jsonify({'ok': True})  # не наше событие — отвечаем 200

    # Верифицируем через API ЮКассы
    payment = _yukassa_fetch_payment(payment_id)
    if not payment or payment.get('status') != 'succeeded':
        return jsonify({'ok': False, 'error': 'payment not verified'}), 400

    metadata = payment.get('metadata', {})
    email = metadata.get('email', '').strip().lower()
    utm = metadata.get('utm_source', 'direct') or 'direct'
    amount = payment.get('amount', {}).get('value', '690.00')

    if not email:
        print(f"Webhook: no email in metadata for payment {payment_id}")
        return jsonify({'ok': False, 'error': 'no email'}), 400

    # Создаём или обновляем пользователя в БД
    db = get_db()
    db.execute("INSERT OR IGNORE INTO users (email) VALUES (?)", (email,))
    db.execute(
        "UPDATE users SET paid_at = CURRENT_TIMESTAMP WHERE email = ? AND paid_at IS NULL",
        (email,)
    )
    db.commit()
    db.close()

    # Записываем в Google Sheets
    append_sale(email, utm, amount)

    print(f"Webhook OK: {email}, utm={utm}, amount={amount}")
    return jsonify({'ok': True})

# ── Admin routes ────────────────────────────────────────────

@main.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
        if password == admin_password:
            session['admin'] = True
            return redirect(url_for('main.admin'))
        error = 'Неверный пароль'
    return render_template('admin_login.html', error=error)

@main.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('main.admin_login'))

@main.route('/admin')
@admin_required
def admin():
    content = load_content()
    blocks = {b: load_block(b) for b in ['action', 'question', 'care']}
    return render_template('admin.html', content=content, blocks=blocks)

@main.route('/admin/save-content', methods=['POST'])
@admin_required
def admin_save_content():
    data = request.get_json()
    if not data or 'page' not in data or 'field' not in data or 'value' not in data:
        return jsonify({'ok': False, 'error': 'bad request'}), 400
    content = load_content()
    page = data['page']
    if page not in content:
        return jsonify({'ok': False, 'error': 'page not found'}), 404
    parts = data['field'].split('.')
    obj = content[page]
    try:
        for part in parts[:-1]:
            obj = obj[int(part)] if part.isdigit() else obj[part]
        last = parts[-1]
        if last.isdigit():
            obj[int(last)] = data['value']
        else:
            obj[last] = data['value']
    except (KeyError, IndexError, TypeError):
        return jsonify({'ok': False, 'error': 'field not found'}), 404
    save_content(content)
    return jsonify({'ok': True})

@main.route('/admin/save-card', methods=['POST'])
@admin_required
def admin_save_card():
    data = request.get_json()
    if not data or 'block' not in data or 'id' not in data:
        return jsonify({'ok': False, 'error': 'bad request'}), 400
    block = data['block']
    card_id = data['id']
    if block not in ['action', 'question', 'care']:
        return jsonify({'ok': False, 'error': 'unknown block'}), 400
    cards = load_block(block)
    for i, card in enumerate(cards):
        if card['id'] == card_id:
            for key in ['title', 'level', 'text', 'hint', 'why', 'science', 'result']:
                if key in data:
                    cards[i][key] = data[key]
            if 'brain' in data:
                cards[i]['brain'] = [line for line in data['brain'].split('\n') if line.strip()]
            save_block(block, cards)
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'card not found'}), 404
