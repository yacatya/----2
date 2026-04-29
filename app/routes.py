import json
import os
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, session, request, jsonify

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

@main.route('/auth')
def auth():
    return render_template('auth.html')

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
                # brain comes as newline-separated string, split into list
                cards[i]['brain'] = [line for line in data['brain'].split('\n') if line.strip()]
            save_block(block, cards)
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'card not found'}), 404
