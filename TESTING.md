# Тестирование webhooks verevery.ru

## Переменные (подставить свои значения)

```bash
BASE=https://verevery.ru
META_VERIFY_TOKEN=<ваш токен верификации>
META_APP_SECRET=<App Secret из Meta Developer Console>
TG_SECRET=<TELEGRAM_WEBHOOK_SECRET>
```

---

## Health checks

```bash
curl $BASE/webhook/instagram/health
# {"channel":"instagram","status":"ok"}

curl $BASE/webhook/telegram/health
# {"channel":"telegram","status":"ok"}
```

---

## Instagram webhook

### GET — верификация подписки Meta

```bash
curl "$BASE/webhook/instagram?hub.mode=subscribe&hub.verify_token=$META_VERIFY_TOKEN&hub.challenge=TEST_CHALLENGE_123"
# Ответ: TEST_CHALLENGE_123  (200 OK)
```

Некорректный токен (ожидать 403):
```bash
curl "$BASE/webhook/instagram?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=X"
# Forbidden
```

### POST — входящее DM (с корректной HMAC-подписью)

```python
# Сгенерировать подпись локально:
import hmac, hashlib, json, requests

app_secret = '<META_APP_SECRET>'
payload = {
    "object": "instagram",
    "entry": [{
        "id": "17841480067488095",
        "messaging": [{
            "sender": {"id": "123456789", "username": "test_blogger"},
            "recipient": {"id": "17841480067488095"},
            "timestamp": 1700000000,
            "message": {
                "mid": "m_test_unique_001",
                "text": "Привет! Интересно, расскажите подробнее"
            }
        }]
    }]
}
body = json.dumps(payload).encode()
sig = 'sha256=' + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()

resp = requests.post(
    'https://verevery.ru/webhook/instagram',
    data=body,
    headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': sig}
)
print(resp.status_code)  # 200
```

Некорректная подпись (ожидать 403):
```bash
curl -X POST $BASE/webhook/instagram \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=badhash" \
  -d '{"object":"instagram","entry":[]}'
# Forbidden
```

### POST — echo-сообщение (должно быть проигнорировано)

```python
payload = {
    "object": "instagram",
    "entry": [{
        "id": "17841480067488095",
        "messaging": [{
            "sender": {"id": "17841480067488095"},
            "recipient": {"id": "123456789"},
            "timestamp": 1700000000,
            "message": {
                "mid": "m_echo_001",
                "text": "Исходящее сообщение",
                "is_echo": True
            }
        }]
    }]
}
# Ответ: 200, запись в incoming_messages НЕ создаётся
```

### POST — дедупликация (повторный message_id)

Отправить тот же payload с `mid=m_test_unique_001` второй раз.
Ожидать: 200, в логах — `duplicate instagram message_id=m_test_unique_001, skipping`.
Фоновая обработка НЕ запускается второй раз.

---

## Telegram webhook

### POST — входящее сообщение

```bash
curl -X POST $BASE/webhook/telegram \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $TG_SECRET" \
  -d '{
    "update_id": 100000001,
    "message": {
      "message_id": 42,
      "from": {"id": 987654321, "username": "test_blogger_tg"},
      "chat": {"id": 987654321, "type": "private"},
      "date": 1700000000,
      "text": "Да, интересно, расскажите подробнее!"
    }
  }'
# 200
```

Некорректный секрет (ожидать 403):
```bash
curl -X POST $BASE/webhook/telegram \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: wrong" \
  -d '{"update_id":1,"message":{}}'
# Forbidden
```

### POST — edited_message

```bash
curl -X POST $BASE/webhook/telegram \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $TG_SECRET" \
  -d '{
    "update_id": 100000002,
    "edited_message": {
      "message_id": 42,
      "from": {"id": 987654321, "username": "test_blogger_tg"},
      "chat": {"id": 987654321, "type": "private"},
      "date": 1700000000,
      "text": "Исправленный текст"
    }
  }'
# 200
```

---

## Тестирование исходящих функций (Python-консоль)

```python
# Запустить из корня проекта:
# export FLASK_APP=run.py && python -c "..."

import os
os.environ['INSTAGRAM_ACCESS_TOKEN'] = 'IGAA...'
os.environ['INSTAGRAM_USER_ID'] = '17841480067488095'
os.environ['TELEGRAM_BOT_TOKEN'] = '123456:AAA...'

from app.routes import send_instagram_dm, send_telegram_message

# Instagram DM
result = send_instagram_dm(psid='<PSID блогера>', text='Тест отправки')
print(result)  # {'ok': True, 'message_id': 'm_xxx'}

# Telegram
result = send_telegram_message(chat_id='987654321', text='Тест из Flask')
print(result)  # {'ok': True, 'message_id': '43'}
```

---

## Регистрация webhooks (setup_webhooks.py)

```bash
# Заполнить .env или экспортировать переменные, затем:
python scripts/setup_webhooks.py
```

Скрипт:
1. Показывает текущий Telegram webhook (URL, pending, ошибки)
2. Устанавливает новый webhook на `https://verevery.ru/webhook/telegram`
3. Показывает состояние после установки
4. Проверяет подписку Instagram через `subscribed_apps`

---

## Переменные окружения — полный список

| Переменная | Назначение | Обязательна |
|---|---|---|
| `RESEND_API_KEY` | Email через Resend | Да |
| `YUKASSA_SECRET_KEY` | Платежи ЮКасса | Да |
| `WEBHOOK_SECRET` | Защита `/webhook/reply`, `/webhook/email-reply` | Да |
| `ANTHROPIC_API_KEY` | Claude для классификации | Да |
| `MAKE_OUTBOUND_WEBHOOK` | Исходящие email через Make.com | Для email |
| `META_VERIFY_TOKEN` | Верификация Instagram webhook | Для IG |
| `META_APP_SECRET` | HMAC-подпись входящих от Meta | Для IG |
| `INSTAGRAM_ACCESS_TOKEN` | Отправка DM (IGAA... токен) | Для IG |
| `INSTAGRAM_USER_ID` | IG User ID аккаунта vere.very | Для IG |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API | Для TG |
| `TELEGRAM_WEBHOOK_SECRET` | Защита `/webhook/telegram` | Для TG |
| `ADMIN_NOTIFY_EMAIL` | Уведомления администратору | Нет (default: team.verevery@gmail.com) |
| `REPLY_TO_EMAIL` | Reply-To в исходящих email блогерам | Нет (default: team.verevery@gmail.com) |
| `BASE_URL` | Базовый URL сайта | Нет (default: https://verevery.ru) |
| `ADMIN_PASSWORD` | Пароль в /admin | Да |
