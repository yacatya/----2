import json
import os
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, session, request
import resend

main = Blueprint('main', __name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

FREE_CARD_IDS = ['А-02', 'З-03', 'В-03', 'В-11', 'З-01']

BLOCK_INFO = {
    'action':   {'label': 'ДЕЙСТВИЕ', 'color': 'var(--accent)',       'name': 'Действие'},
    'question': {'label': 'ВОПРОС',   'color': 'var(--muted)',        'name': 'Вопрос'},
    'care':     {'label': 'ЗАБОТА',   'color': 'var(--light-accent)', 'name': 'Забота'},
}


def load_block(block):
    with open(os.path.join(DATA_DIR, f'cards_{block}.json'), encoding='utf-8') as f:
        return json.load(f)['cards']


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
    return render_template('free.html', cards=free_cards)


@main.route('/buy')
def buy():
    return render_template('buy.html')


@main.route('/cards')
def cards():
    if 'user_id' not in session:
        return redirect(url_for('main.auth'))
    from .db import get_db
    conn = get_db()
    user = conn.execute('SELECT has_access FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    if not user or not user['has_access']:
        return redirect(url_for('main.buy'))
    blocks = {}
    for block, info in BLOCK_INFO.items():
        blocks[block] = {**info, 'cards': load_block(block)}
    return render_template('cards.html', blocks=blocks)


@main.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email or '@' not in email or '.' not in email.split('@')[-1]:
            return render_template('auth.html', error='Введите корректный email')

        token = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(minutes=30)).isoformat()

        from .db import get_db
        conn = get_db()
        conn.execute('INSERT OR IGNORE INTO users (email) VALUES (?)', (email,))
        conn.execute('DELETE FROM magic_tokens WHERE email=? AND used=0', (email,))
        conn.execute(
            'INSERT INTO magic_tokens (token, email, expires_at) VALUES (?, ?, ?)',
            (token, email, expires_at)
        )
        conn.commit()
        conn.close()

        base_url = os.environ.get('BASE_URL', 'https://verevery.ru')
        link = f'{base_url}/auth/verify?token={token}'

        resend.api_key = os.environ.get('RESEND_API_KEY', '')
        try:
            resend.Emails.send({
                'from': 'Ближе <noreply@verevery.ru>',
                'to': [email],
                'subject': 'Ваша ссылка для входа — verevery.ru',
                'html': _magic_link_email(link),
            })
        except Exception:
            pass

        return render_template('auth.html', sent=True, email=email)

    return render_template('auth.html')


@main.route('/auth/verify')
def auth_verify():
    token = request.args.get('token', '')
    if not token:
        return redirect(url_for('main.auth'))

    from .db import get_db
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM magic_tokens WHERE token=? AND used=0 AND expires_at > ?',
        (token, datetime.utcnow().isoformat())
    ).fetchone()

    if not row:
        conn.close()
        return render_template('auth.html',
            error='Ссылка устарела или уже использована. Запросите новую.')

    conn.execute('INSERT OR IGNORE INTO users (email) VALUES (?)', (row['email'],))
    user = conn.execute('SELECT * FROM users WHERE email=?', (row['email'],)).fetchone()
    conn.execute('UPDATE magic_tokens SET used=1 WHERE token=?', (token,))
    conn.commit()
    conn.close()

    session.permanent = True
    session['user_id'] = user['id']
    session['email'] = user['email']
    return redirect(url_for('main.cards'))


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
      Ваша ссылка для входа
    </div>
    <p style="font-size:14px;font-weight:300;color:#8C7E72;line-height:1.7;margin:0 0 28px;">
      Нажмите кнопку ниже, чтобы войти в колоду «Ближе».<br>Ссылка действует 30 минут.
    </p>
    <a href="{link}"
       style="display:block;text-align:center;background:#2A2118;color:#FFFFFF;
              text-decoration:none;padding:16px 24px;border-radius:50px;
              font-size:14px;font-weight:500;letter-spacing:0.5px;">
      Войти в колоду
    </a>
    <p style="font-size:11px;color:#D4C8B5;text-align:center;margin:20px 0 0;line-height:1.6;">
      Если кнопка не открывается, скопируйте ссылку:<br>
      <a href="{link}" style="color:#A67C52;word-break:break-all;">{link}</a>
    </p>
  </div>
  <p style="font-size:11px;color:#D4C8B5;text-align:center;margin-top:24px;line-height:1.6;">
    Если вы не запрашивали эту ссылку — просто проигнорируйте письмо.
  </p>
</div>
</body>
</html>'''
