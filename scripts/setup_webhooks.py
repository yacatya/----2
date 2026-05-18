#!/usr/bin/env python3
"""
Register Telegram webhook and verify Instagram webhook subscription.

Run locally after filling .env (or exporting env vars):
    python scripts/setup_webhooks.py

Idempotent — safe to run multiple times.
"""

import os
import sys
import json

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

try:
    import requests
except ImportError:
    sys.exit('Установите requests: pip install requests')

BASE_URL = os.environ.get('BASE_URL', 'https://verevery.ru')


def setup_telegram():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
    if not token:
        print('[Telegram] TELEGRAM_BOT_TOKEN не задан — пропуск\n')
        return

    api = f'https://api.telegram.org/bot{token}'
    webhook_url = f'{BASE_URL}/webhook/telegram'

    # 1. Текущее состояние
    print('[Telegram] Текущее состояние webhook:')
    resp = requests.get(f'{api}/getWebhookInfo', timeout=10)
    info = resp.json().get('result', {})
    print(f'  URL:             {info.get("url") or "(не задан)"}')
    print(f'  Pending updates: {info.get("pending_update_count", 0)}')
    if info.get('last_error_message'):
        print(f'  Последняя ошибка: {info["last_error_message"]}')
        print(f'  Дата ошибки:      {info.get("last_error_date", "")}')

    # 2. Установка нового webhook
    print(f'\n[Telegram] Устанавливаю webhook → {webhook_url}')
    payload = {
        'url': webhook_url,
        'allowed_updates': ['message', 'edited_message'],
    }
    if secret:
        payload['secret_token'] = secret
    else:
        print('  ПРЕДУПРЕЖДЕНИЕ: TELEGRAM_WEBHOOK_SECRET не задан — webhook будет без проверки секрета')

    resp = requests.post(f'{api}/setWebhook', json=payload, timeout=10)
    result = resp.json()
    if result.get('ok'):
        print(f'  OK: {result.get("description", "webhook установлен")}')
    else:
        print(f'  ОШИБКА: {json.dumps(result, ensure_ascii=False)}')

    # 3. Проверка после установки
    print('\n[Telegram] Состояние после установки:')
    resp = requests.get(f'{api}/getWebhookInfo', timeout=10)
    info = resp.json().get('result', {})
    print(f'  URL:             {info.get("url") or "(не задан)"}')
    print(f'  Pending updates: {info.get("pending_update_count", 0)}')
    if info.get('last_error_message'):
        print(f'  Последняя ошибка: {info["last_error_message"]}')
    else:
        print('  Ошибок нет')
    print()


def check_instagram():
    token = os.environ.get('INSTAGRAM_ACCESS_TOKEN', '')
    user_id = os.environ.get('INSTAGRAM_USER_ID', '')
    if not token or not user_id:
        print('[Instagram] INSTAGRAM_ACCESS_TOKEN или INSTAGRAM_USER_ID не заданы — пропуск')
        return

    print('[Instagram] Проверка подписки на webhook...')
    url = f'https://graph.instagram.com/v23.0/{user_id}/subscribed_apps'
    resp = requests.get(url, params={'access_token': token}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        apps = data.get('data', [])
        if apps:
            print(f'  Подписано приложений: {len(apps)}')
            for app in apps:
                print(f'  - {json.dumps(app, ensure_ascii=False)}')
        else:
            print('  Активных подписок нет.')
            print('  Настройте webhook в Meta Developer Console:')
            print(f'    Callback URL:  {BASE_URL}/webhook/instagram')
            print(f'    Verify Token:  $META_VERIFY_TOKEN')
            print('    Подписки:      messages, messaging_postbacks')
    else:
        print(f'  Ошибка {resp.status_code}: {resp.text[:400]}')
    print()


if __name__ == '__main__':
    print(f'=== Настройка webhooks {BASE_URL} ===\n')
    setup_telegram()
    check_instagram()
    print('Готово.')
