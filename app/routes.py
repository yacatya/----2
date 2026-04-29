import json
import os
from flask import Blueprint, render_template, redirect, url_for, session

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
    blocks = {}
    for block, info in BLOCK_INFO.items():
        blocks[block] = {**info, 'cards': load_block(block)}
    return render_template('cards.html', blocks=blocks)

@main.route('/auth')
def auth():
    return render_template('auth.html')
