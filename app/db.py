import sqlite3
import os

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'verevery.db'))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS placements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blogger_id INTEGER NOT NULL,
            placement_date TEXT,
            format TEXT DEFAULT 'post',
            creative_variant TEXT DEFAULT '',
            model_at_placement TEXT DEFAULT 'fix',
            cost INTEGER DEFAULT 0,
            payment_status TEXT DEFAULT 'not_required',
            payment_date TEXT,
            views INTEGER,
            clicks INTEGER,
            sales INTEGER,
            revenue_kopecks INTEGER,
            notes TEXT DEFAULT '',
            deleted_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ad_budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT UNIQUE NOT NULL,
            budget_limit_kopecks INTEGER NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            has_access INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS magic_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE,
            date TEXT,
            email TEXT,
            utm TEXT,
            blogger TEXT,
            amount REAL,
            commission REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS bloggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            platform TEXT DEFAULT '',
            profile_url TEXT DEFAULT '',
            email TEXT DEFAULT '',
            utm_slug TEXT DEFAULT '',
            utm_link TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            first_email_sent_at TEXT,
            last_reply_at TEXT,
            reply_sentiment TEXT,
            sales_count INTEGER DEFAULT 0,
            paid_out INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blogger_id INTEGER,
            type TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            status TEXT DEFAULT 'ok',
            error TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS email_templates (
            key TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            body_text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS link_clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utm_slug TEXT NOT NULL,
            visited_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS partner_tokens (
            token TEXT PRIMARY KEY,
            blogger_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS partner_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blogger_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            paid_date TEXT NOT NULL,
            method TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS partner_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT DEFAULT 'link',
            url TEXT DEFAULT '',
            content TEXT DEFAULT '',
            description TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS partner_faq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            order_num INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS incoming_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel      TEXT NOT NULL,
            message_id   TEXT,
            external_id  TEXT NOT NULL,
            blogger_id   INTEGER,
            text         TEXT NOT NULL,
            received_at  TEXT NOT NULL,
            processed_at TEXT,
            raw_payload  TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(channel, message_id)
        );
        CREATE TABLE IF NOT EXISTS utm_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL DEFAULT '',
            ip TEXT NOT NULL DEFAULT '',
            user_agent TEXT DEFAULT '',
            referrer TEXT DEFAULT '',
            landing_page TEXT DEFAULT '',
            utm_source TEXT DEFAULT '',
            utm_medium TEXT DEFAULT '',
            utm_campaign TEXT DEFAULT '',
            utm_content TEXT DEFAULT '',
            is_unique INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_utm_visits_source ON utm_visits(utm_source);
        CREATE INDEX IF NOT EXISTS idx_utm_visits_session ON utm_visits(session_id);
        CREATE INDEX IF NOT EXISTS idx_utm_visits_created ON utm_visits(created_at);
    ''')
    default_templates = [
        (
            'blogger_first',
            'Сотрудничество — колода карточек «Ближе» для пар',
            'Привет, {name}! \U0001f44b\n\nМеня зовут Катя, я создала Vera — онлайн-колоду карточек «Ближе» для пар на verevery.ru.\n\nКарточки помогают восстановить близость в отношениях — основаны на доказательной психологии (Готтман, EFT, теория привязанности). Цена: 690 ₽.\n\nХочу предложить сотрудничество: вы рассказываете аудитории о проекте, получаете 30% с каждой продажи по вашей ссылке — 207 ₽ за покупку.\n\nЕсли интересно — напишу подробнее об условиях \U0001f64c\n\nКатя\nverevery.ru',
        ),
        (
            'blogger_second',
            'Re: Сотрудничество — колода карточек «Ближе» для пар',
            'Привет, {name}! Рада, что откликнулись \U0001f49b\n\nВот подробности о сотрудничестве:\n\n\U0001f4e6 Продукт: онлайн-колода «Ближе» — 60 карточек для пар (verevery.ru)\n\U0001f4b8 Комиссия: 30% = 207 ₽ с каждой продажи\n\U0001f517 Ваша ссылка: {utm_link}\n\nКак это работает:\n1. Вы публикуете пост или сторис со своей ссылкой\n2. Подписчики переходят и покупают\n3. Я считаю продажи по вашему UTM и перевожу комиссию раз в месяц\n\nМогу прислать описание продукта и примеры карточек — всё что нужно для публикации.\n\nГотова ответить на любые вопросы!\n\nКатя\nverevery.ru',
        ),
        (
            'blogger_third',
            '{name}, делюсь рекомендациями по работе с контентом',
            'Привет, {name}!\n\nДелюсь рекомендациями по формату публикации. Это не жёсткие требования — финальный вид всегда за вами. Но эти подходы по нашему опыту дают лучший отклик.\n\n\U0001f4cc ВАЖНО ПРО ФОРМАТ ПРОДУКТА\n\nКарточки — цифровые, открываются в браузере на экране телефона.\nЭто не одна категория, а три блока по 20 карточек:\n\n— Вопрос — глубокие вопросы для разговора с партнёром\n— Действие — конкретные совместные практики (прогулка без телефона, записка в кармане и т.д.)\n— Забота — готовые фразы поддержки и принятия\n\nВнутри каждого блока — три уровня сложности: Лёгкий → Средний → Сложный. Можно начинать с лёгких и идти глубже.\n\nУ каждой карточки есть не только текст вопроса/действия, но и объяснение зачем это работает с точки зрения нейробиологии и ссылкой на исследования (Готтман, EFT, КПТ, ACT). Это важный момент — это не «вопросы для знакомства», это инструмент.\n\n\U0001f4f1 ОСНОВНОЙ ПОСТ\n\nФормат 1 — Карусель «Три карточки которые меня прибили» (5-7 слайдов)\n\nСамый сильный формат для цифровых карточек. Структура:\n\nСлайд 1 — Хук со скриншотом одной карточки\nСкриншот самой сильной карточки крупным планом. Например карточка В-01 «Лучший момент»: «Какой момент, проведённый с тобой, я вспоминаю чаще всего — и почему именно он?»\nПодпись поверх или рядом: «Этот вопрос я бы никогда не задала сама. А зря».\n\nСлайды 2-4 — Личное размышление\nВ вашем обычном стиле. Реакция на карточки, личный опыт, размышление про близость. Не реклама — продолжение вашего обычного контента.\n\nСлайд 5 — Скриншоты карточек из разных блоков\nОдин скриншот вопроса, один действия, один заботы. Подпись сбоку: «Вопрос. Действие. Забота. 60 карточек, три блока, три уровня сложности».\n\nСлайд 6 — Что внутри\nКратко про научную базу: «Каждая карточка построена на исследованиях — Готтман, КПТ, теория привязанности. И к каждой есть объяснение почему это работает в мозге».\n\nСлайд 7 — Призыв\n«5 карточек бесплатно — посмотреть как это устроено. Полная колода — по моей ссылке: {utm_link}»\n\nФормат 2 — Рилс (15-45 секунд)\n\nСценарий А — «Три вопроса которые поменяли разговор»\nЗапись экрана: листаете карточки в браузере, останавливаетесь на трёх самых сильных вопросах. Голос за кадром: «Купила недавно. Задала мужу эти три вопроса. Говорили два часа без перерыва.»\n\nСценарий Б — Screen recording по блокам\nБыстрая смена скриншотов — Вопрос / Действие / Забота. Голос или текст: «В отношениях обычно не хватает не любви. Не хватает поводов поговорить. Вот 60 поводов, разделённые на три категории.»\n\nСценарий В — Реакция на одну карточку\nКамера на вас, в кадре телефон с одной карточкой. Читаете вопрос вслух, реагируете честно.\n\nСценарий Г — «Категория Забота — это что-то отдельное»\nФокус только на блоке Забота. Скриншоты 2-3 карточек заботы + ваша реакция: «Это не вопросы. Это просто фразы. Но попробуй их сказать вслух — поймёшь почему сложно».\n\n\U0001f4f2 STORIES (2-3 ШТУКИ)\n\nStories 1 — Тизер за день до поста\nСкриншот одной мощной карточки + ваш комментарий.\n\nStories 2 — В день публикации\nСкриншот поста + ссылка-стикер.\n\nStories 3 — Через 1-2 дня\nЛичная реакция или цитата без давления — продолжение темы.\n\n\U0001f4e6 ВИЗУАЛЬНЫЕ МАТЕРИАЛЫ ОТ НАС\n\nЯ пришлю:\n— Подборку скриншотов карточек в высоком разрешении из всех трёх блоков\n— Mockup-изображения телефона с открытыми карточками\n— Screen recording прохождения карточек на телефоне\n— Готовые тексты постов и stories\n\n\U0001f7e2 ЧТО ХОРОШО РАБОТАЕТ\n\n— Скриншоты конкретных вопросов или фраз из колоды\n— Подсветка структуры (три блока, три уровня)\n— Упоминание научной базы (Готтман, КПТ, исследования)\n— Личная реакция на конкретную карточку «вот эта меня прибила»\n— Акцент что у каждой карточки есть объяснение зачем\n\n\U0001f534 ЧТО НЕ РАБОТАЕТ\n\n— «Карточки помогут улучшить отношения» — пустая фраза без конкретики\n— Скрывать что продукт цифровой\n— Не упоминать три категории и градацию сложности\n— Слова «уникальный», «революционный», «единственный»\n— Прямая реклама без личной обёртки\n\n\U0001f552 ПО ТАЙМИНГУ\n\nЛучшее время для публикации в нише отношений:\n— Будни: вечер 19:00–21:30\n— Выходные: первая половина дня 11:00–14:00\n\n⚠️ ОБЯЗАТЕЛЬНО\n\n— Маркировка рекламы по закону РФ: пометка «реклама», ИНН рекламодателя и ERID. Пришлю данные после регистрации креатива в ОРД.\n— Чёткое указание что продукт цифровой (онлайн-формат, открывается в браузере на телефоне)\n— Партнёрская ссылка в шапке профиля или ссылке-стикере stories: {utm_link}\n\nЕсли хотите обсудить идеи — пишите. Могу помочь подобрать конкретные карточки под раскадровку рилс или текст поста.\n\nС уважением,\nКатя',
        ),
    ]
    fix_templates = [
        (
            'fix_first',
            'Реклама в вашем канале — колода для пар «Ближе»',
            'Здравствуйте, {name}!\n\nХочу обсудить размещение в вашем канале. Продукт — цифровая колода карточек для пар «Ближе» (verevery.ru), цена 690₽.\n\nПодскажите:\n— Прайс на пост / 1/24 / 1/48\n— Ближайшие свободные даты\n— Нужны ли данные для маркировки (ИНН, ОРД)\n\nКреатив пришлю под формат канала. Готова к переговорам по цене при долгосрочных размещениях.\n\nСпасибо!'
        ),
        (
            'fix_materials',
            'Материалы для размещения',
            'Отлично, благодарю за согласование! Высылаю материалы:\n\n— 3 варианта текста поста (выберите ближайший к стилю канала)\n— Изображения для поста (прикреплены отдельно)\n— Ссылка с UTM-меткой: {utm_link}\n\nПодтвердите дату публикации. Оплату пришлю на СБП / карту — как удобнее?\n\nС уважением'
        ),
        (
            'fix_convert',
            'Отчёт по размещению + предложение на постоянку',
            'Здравствуйте, {name}!\n\nОтчёт по нашему размещению от {placement_date}:\n— Переходов: {clicks}\n— Продаж: {sales}\n— Сумма продаж: {revenue}₽\n\nПо нашей партнёрской программе (30% с продаж) вы бы заработали {partnership_amount}₽ с этого же размещения.\n\nЕсли интересно — переключаемся на постоянное сотрудничество:\n— Без предоплаты с моей стороны\n— 207₽ с каждой продажи по вашей ссылке\n— Выплаты раз в месяц\n— Личный кабинет со статистикой\n\nГотова продолжить работу?'
        ),
    ]
    for key, subject, body_text in fix_templates:
        try:
            conn.execute(
                'INSERT OR IGNORE INTO email_templates (key, subject, body_text) VALUES (?, ?, ?)',
                (key, subject, body_text)
            )
        except Exception:
            pass
    for key, subject, body_text in default_templates:
        try:
            conn.execute(
                'INSERT OR IGNORE INTO email_templates (key, subject, body_text) VALUES (?, ?, ?)',
                (key, subject, body_text)
            )
        except Exception:
            pass
    for col, definition in [
        ('session_id', "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f'ALTER TABLE sales ADD COLUMN {col} {definition}')
        except Exception:
            pass
    for col, definition in [
        ('has_access', 'INTEGER DEFAULT 0'),
        ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ]:
        try:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {definition}')
        except Exception:
            pass
    for col, definition in [
        ('channel',            "TEXT DEFAULT 'email'"),
        ('ig_username',        "TEXT DEFAULT ''"),
        ('ig_user_id',         "TEXT DEFAULT ''"),
        ('tg_username',        "TEXT DEFAULT ''"),
        ('tg_user_id',         "TEXT DEFAULT ''"),
        ('last_message',       "TEXT DEFAULT ''"),
        ('partner_token',      "TEXT DEFAULT ''"),
        ('cooperation_model',  "TEXT DEFAULT 'partnership'"),
        ('audience_size',      'INTEGER'),
        ('topic',              "TEXT DEFAULT ''"),
        ('er_percent',         'REAL'),
    ]:
        try:
            conn.execute(f'ALTER TABLE bloggers ADD COLUMN {col} {definition}')
        except Exception:
            pass
    conn.commit()
    conn.close()
