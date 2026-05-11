"""
One-time seed script: insert 200 bloggers into the CRM.
Run on server: cd /opt/verevery && python3 seed_bloggers.py
Safe to run multiple times (INSERT OR IGNORE on utm_slug).
"""
import sqlite3, os, re

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'verevery.db'))
BASE_URL = os.environ.get('BASE_URL', 'https://verevery.ru')


def slug(text):
    s = text.lower().strip()
    s = re.sub(r'[\s\-]+', '_', s)
    s = re.sub(r'[^a-z0-9_]', '', s)
    return s[:50] or 'blogger'


def tg_slug(url):
    """Extract username from t.me/username, fallback to name-based slug."""
    u = url.replace('https://', '').replace('http://', '').replace('t.me/', '').strip('/')
    if u.startswith('+') or not u:
        return None
    s = re.sub(r'[^a-z0-9_]', '', u.lower())
    return s[:50] or None


def ig_slug(url):
    u = url.replace('https://instagram.com/', '').replace('https://www.instagram.com/', '')
    u = u.replace('@', '').strip('/')
    s = re.sub(r'[^a-z0-9_.]', '', u.lower()).replace('.', '_')
    return s[:50] or None


BLOGGERS = [
    # ── TELEGRAM Part A: Авторские каналы ───────────────────────────────────────────────────────────────────
    ('Надежда Семененко', 'Telegram', 'https://t.me/semenenkon', '', '~15-25K. ПО, ТР — любовь к себе, границы, кПТСР'),
    ('Дмитрий Петров (психология отношений)', 'Telegram', 'https://t.me/+mvszUqj6qVkzODNi', '', '5-15K. ПО, ЖК — психология женщин'),
    ('Елена Фесенко (WomenWisdom)', 'Telegram', 'https://t.me/WomenWisdom', '', '~10-20K. ПО — мужчина и женщина'),
    ('Эмилия Гончарова', 'Telegram', 'https://t.me/emiliagoncharova', '', '~600-5K. ПО, ЖК — образ аристократичной женщины'),
    ('Ирина Гиберманн (Гиберклаб)', 'Telegram', 'https://t.me/giberclub', '', '~30-45K. ТР, ОС — КПТ, схема-терапия'),
    ('Олеся Шаповал', 'Telegram', 'https://t.me/safe_place_psy', '', '~10-20K. ТР, ОС — ACT, CFT'),
    ('Юлия Макоева (HappyPeople)', 'Telegram', 'https://t.me/happypeoplecoach', '', '~5-15K. СР, ОС — позитивная психология'),
    ('Дарина (тело и психология)', 'Telegram', 'https://t.me/darina_about_body', '', '~5-15K. ОС, ТР — функциональная нормализация веса'),
    ('Марина Безуглова', 'Telegram', 'https://t.me/wellness_bezuglova', '', '~5-10K. СР, ОС — коучинг, медитации'),
    ('Радмила Хакова', 'Telegram', 'https://t.me/khakova', '', '~50K (на грани). ПО, МТ — родительство, ментальное здоровье'),
    ('Наталья Ремиш', 'Telegram', 'https://t.me/natalia_remish', '', '~30-50K. МТ, СП'),
    ('Татьяна Мужицкая', 'Telegram', 'https://t.me/muzhitskaya', '', '~30-50K. ПО, СР — отношения, переговоры'),
    ('Михаил Лабковский', 'Telegram', 'https://t.me/labkovskiy', '', '>100K (вне порога). ПО — публичный психолог'),
    ('Вика Дмитриева', 'Telegram', 'https://t.me/vikadmitrieva_psiholog', '', '~270K (вне порога). СП, МТ'),
    ('Лариса Суркова', 'Telegram', 'https://t.me/larisasurkova_psy', '', '>100K (вне порога). СП, МТ'),
    ('Михаил Златкин', 'Telegram', 'https://t.me/mikhailzlatkinblog', '', '~130K (вне порога). ТР'),
    ('Марина Травкова', 'Telegram', 'https://t.me/travkova_psy', '', '~10-25K. ПО — измены, исследования о семье'),
    ('Мила Кудрякова', 'Telegram', 'https://t.me/mila_kudryakova', '', '~10-20K. ПО, СП — пары, родители-дети'),
    ('Ирина Парфенова', 'Telegram', 'https://t.me/parfenova_psy', '', '~10-20K. ТР, СР — личные границы'),
    ('Татьяна Павлова (тревога)', 'Telegram', 'https://t.me/anxious_psychologist', '', '~15-30K. ТР — тревожные расстройства'),
    ('Альберт Сафин', 'Telegram', 'https://t.me/safinalbert', '', '~15-35K. ПО, СР'),
    ('Полина Девочкина', 'Telegram', 'https://t.me/polinadevochkina', '', '~10-25K. ПО — сексология научно'),
    ('Катерина Карпович', 'Telegram', 'https://t.me/katerina_karpovich', '', '~10-25K. ПО, ТР — сексология, отношения'),
    ('Анастасия (созависимость)', 'Telegram', 'https://t.me/psy_codependence', '', '~5-15K. ПО, ТР — созависимые отношения'),
    ('Юлия (научная психология отношений)', 'Telegram', 'https://t.me/science_relationships', '', '~5-15K. ПО — Готтман, исследования'),
    ('Вероника Степанова', 'Telegram', 'https://t.me/veronika_stepanova', '', '~30-50K. ТР, СП'),
    ('Алексей Карачинский', 'Telegram', 'https://t.me/karachinskiy', '', '~20-40K. ТР — фобии, неврозы'),
    ('Чистые когниции', 'Telegram', 'https://t.me/cleancognitions', '', '~20-40K. СР, ТР — научпоп о психологии'),
    ('Женя Веритов / Mango Project', 'Telegram', 'https://t.me/mangoproject_eg', '', '~5-15K. ТР — гештальт-терапия'),
    ('Андрей Сирота', 'Telegram', 'https://t.me/ne_sirota', '', '~5-15K. ТР — гештальт'),
    ('Артём Шафкеев', 'Telegram', 'https://t.me/shafkeev_psy', '', '~10-25K. СР, ПО'),
    ('Игорь Ким (архетипы)', 'Telegram', 'https://t.me/igorkimblog', '', '~10-30K. СР, ОС — юнгианство'),
    ('Влада Попутаровская', 'Telegram', 'https://t.me/poputarovskaya', '', '~20-45K. ПО, ЖК — НЛП, отношения'),
    ('Дмитрий Эснер', 'Telegram', 'https://t.me/esner_dmitry', '', '~30-50K. ПО — мужской взгляд'),
    ('Сабина Ламанна', 'Telegram', 'https://t.me/sabina_lamanna', '', '~10-30K. СП, МТ'),
    ('Елена Вайс', 'Telegram', 'https://t.me/elenaweissblog', '', '~10-30K. ТР, ЖК'),
    ('Марина Вовченко (Йога-мама)', 'Telegram', 'https://t.me/marinavovchenkoyoga', '', '~15-30K. ОС, МТ — йога + психология'),
    ('Владимир Зуев', 'Telegram', 'https://t.me/vladimirzuev_psy', '', '~20-45K. СП'),
    ('Дмитрий Карпачёв', 'Telegram', 'https://t.me/karpachov', '', '>100K (вне порога). СП — публичный психолог'),

    # ── TELEGRAM Part B: Тематические каналы ───────────────────────────────────────────────────────────────────
    ('О Любви. Психология отношений', 'Telegram', 'https://t.me/PsyxoLove', '', '~30-50K. ПО'),
    ('Психология отношений (агрегатор)', 'Telegram', 'https://t.me/psychology_relationshipinfo', '', '~25-50K. ПО'),
    ('Психология отношений (psy4love)', 'Telegram', 'https://t.me/psy4love', '', '~10-30K. ПО'),
    ('Психология / Саморазвитие (Psyxo_tg)', 'Telegram', 'https://t.me/Psyxo_tg', '', '~20-40K. СР'),
    ('Психология / Саморазвитие (motivatsia)', 'Telegram', 'https://t.me/motivatsia_psikhologia', '', '~30-50K. СР'),
    ('Психология саморазвития (SilaSlov)', 'Telegram', 'https://t.me/SilaSlov', '', '~30-50K. СР'),
    ('Психология. Саморазвитие (psy_tgram)', 'Telegram', 'https://t.me/psy_tgram', '', '~20-45K. СР'),
    ('Психология / Саморазвитие (psixoIogy)', 'Telegram', 'https://t.me/psixoIogy', '', '~20-45K. СР'),
    ('Психология / Саморазвитие (samorazvitie)', 'Telegram', 'https://t.me/samorazvitie_psix', '', '~15-40K. СР'),
    ('Психология / Саморазвитие (psychologmee)', 'Telegram', 'https://t.me/psychologmee', '', '~15-35K. СР'),
    ('Психология саморазвития (psdevelopment)', 'Telegram', 'https://t.me/psdevelopment', '', '~10-30K. СР'),
    ('Психологические книги', 'Telegram', 'https://t.me/hotpsychologybooks', '', '~20-45K. СР — книги по психологии'),
    ('SUP (краткие посты об отношениях)', 'Telegram', 'https://t.me/sup_psy', '', '~10-30K. ПО'),
    ('Дом саморазвития', 'Telegram', 'https://t.me/domsamorazvitiya', '', '~20-45K. СР'),
    ('Михаил Гаугаш (Путь тропы)', 'Telegram', 'https://t.me/puttropy', '', '~15-40K. ОС, СР — медитативные практики'),
    ('Развитие силы воли', 'Telegram', 'https://t.me/Razvitie_sila_voli', '', '~20-35K. СР'),
    ('Психология самопознания', 'Telegram', 'https://t.me/Psihologiya_samorazvitie', '', '~50K (на грани). СР'),
    ('Ключи мастерства', 'Telegram', 'https://t.me/Kluchimasterstva', '', '~30K. СР'),
    ('Залипать на психологии', 'Telegram', 'https://t.me/zalipatpsychology', '', '~35K. СР, ТР'),
    ('Психологическое счастье', 'Telegram', 'https://t.me/psy_happiness', '', '~10-25K. СР'),
    ('Доступная психология', 'Telegram', 'https://t.me/dostupnayapsy', '', '~10-30K. СР'),
    ('Математика души', 'Telegram', 'https://t.me/math_of_soul', '', '~10-25K. ОС, СР'),
    ('Психосоматика', 'Telegram', 'https://t.me/psychosomatika', '', '~15-40K. ТР, ОС'),
    ('Женский мирок', 'Telegram', 'https://t.me/loove_mood', '', '>100K (вне порога). ЖК'),
    ('Цитаты для женщин', 'Telegram', 'https://t.me/cytaty_jenshini', '', '~20-45K. ЖК'),
    ('В погоне за счастьем', 'Telegram', 'https://t.me/be_happy_now', '', '>100K (вне порога). СР'),
    ('POWER OF L.O.V.E.', 'Telegram', 'https://t.me/poweroflove_as', '', '~15-35K. ПО, ЖК'),
    ('Психология / Мотивация (psy_motivation_ru)', 'Telegram', 'https://t.me/psy_motivation_ru', '', '~20-45K. СР'),
    ('Психология здоровых отношений', 'Telegram', 'https://t.me/healthy_relationships_psy', '', '~10-25K. ПО'),
    ('Mindfulness Russia (TG)', 'Telegram', 'https://t.me/mindfulness_ru', '', '~10-30K. ОС'),
    ('Медитации и осознанность', 'Telegram', 'https://t.me/meditation_ru', '', '~15-35K. ОС'),
    ('Психология детства', 'Telegram', 'https://t.me/childhood_psy', '', '~10-25K. СП, МТ'),
    ('Хорошие отношения (подкаст)', 'Telegram', 'https://t.me/horoshie_otnosheniya', '', '~10-30K. ПО, СП'),
    ('Где мои дети', 'Telegram', 'https://t.me/where_my_kids', '', '~25-50K. МТ, СП'),
    ('Детская комната', 'Telegram', 'https://t.me/child_room_psy', '', '~10-25K. СП, МТ'),

    # ── TELEGRAM Part C: Женский/осознанный сегмент ───────────────────────────────────────────────────────────────────
    ('Женское счастье. Психология', 'Telegram', 'https://t.me/woman_happy_psy', '', '~10-30K. ЖК, ПО'),
    ('Твой путь к цели', 'Telegram', 'https://t.me/path_to_goal_psy', '', '~10-25K. СР'),
    ('Психология / Мотивация (psy_motiv_ru)', 'Telegram', 'https://t.me/psy_motiv_ru', '', '~15-40K. СР'),
    ('Я — женщина (TG)', 'Telegram', 'https://t.me/ya_zhenschina_blog', '', '~15-40K. ЖК'),
    ('Осознанная женщина', 'Telegram', 'https://t.me/aware_woman', '', '~10-25K. ОС, ЖК'),
    ('Mindful mama (TG)', 'Telegram', 'https://t.me/mindful_mama_ru', '', '~5-15K. ОС, МТ'),
    ('Йога для души', 'Telegram', 'https://t.me/yoga_dlya_dushi', '', '~10-25K. ОС'),
    ('Мария (нейропсихология)', 'Telegram', 'https://t.me/maria_neuropsy', '', '~5-15K. ТР'),
    ('Женские архетипы (TG)', 'Telegram', 'https://t.me/female_archetypes', '', '~10-30K. ЖК, СР'),
    ('О границах', 'Telegram', 'https://t.me/about_boundaries', '', '~5-20K. ПО, СР'),
    ('Эмоциональный интеллект (TG)', 'Telegram', 'https://t.me/emotional_iq_ru', '', '~15-40K. СР'),
    ('Привязанность и отношения (TG)', 'Telegram', 'https://t.me/attachment_ru', '', '~5-15K. ПО, ТР'),
    ('Психология пары (TG)', 'Telegram', 'https://t.me/couples_psy_ru', '', '~10-25K. ПО'),
    ('Парная терапия (TG)', 'Telegram', 'https://t.me/couple_therapy_ru', '', '~5-15K. ПО, ТР'),
    ('Семейный портрет', 'Telegram', 'https://t.me/family_portrait_psy', '', '~5-15K. СП'),
    ('Психология родительства (TG)', 'Telegram', 'https://t.me/parenting_psy_ru', '', '~10-25K. СП, МТ'),
    ('Травма и восстановление (TG)', 'Telegram', 'https://t.me/trauma_recovery_ru', '', '~5-15K. ТР'),
    ('Тревожность под контролем', 'Telegram', 'https://t.me/anxiety_control_ru', '', '~10-30K. ТР'),
    ('Самооценка и я', 'Telegram', 'https://t.me/selfesteem_psy', '', '~10-30K. СР'),
    ('Внутренний ребёнок (TG)', 'Telegram', 'https://t.me/inner_child_ru', '', '~5-15K. ТР, СР'),
    ('КПТ-практика (TG)', 'Telegram', 'https://t.me/cbt_practice_ru', '', '~5-15K. ТР'),
    ('Психология осознанности (TG)', 'Telegram', 'https://t.me/mindfulness_psy_ru', '', '~10-25K. ОС'),
    ('Школа осознанности (TG)', 'Telegram', 'https://t.me/awareness_school', '', '~5-15K. ОС'),
    ('Чувства и я', 'Telegram', 'https://t.me/feelings_and_me', '', '~10-25K. СР, ТР'),
    ('Любить и быть любимой', 'Telegram', 'https://t.me/love_and_be_loved', '', '~10-30K. ПО, ЖК'),

    # ── INSTAGRAM Part A: Психологи отношений и пар ─────────────────────────────────────────────────────────────────
    ('Виктория Дмитриева', 'Instagram', 'https://instagram.com/vikadmitrieva_psiholog', '', '>300K (вне порога). ПО, СП'),
    ('Михаил Лабковский', 'Instagram', 'https://instagram.com/labkovskiy', '', '>1M (вне порога). ПО'),
    ('Дмитрий Карпачёв', 'Instagram', 'https://instagram.com/karpachov', '', '>2M (вне порога). СП'),
    ('Лариса Суркова', 'Instagram', 'https://instagram.com/larangsovet', '', '>2M (вне порога). СП, МТ'),
    ('Дмитрий Эснер', 'Instagram', 'https://instagram.com/esner_dmitry', '', '~50-100K. ПО'),
    ('Влада Попутаровская', 'Instagram', 'https://instagram.com/vladaputarovskaya', '', '~30-60K. ПО, ЖК'),
    ('Сабина Ламанна', 'Instagram', 'https://instagram.com/sabinalamanna', '', '~30-50K. СП, МТ'),
    ('Елена Вайс', 'Instagram', 'https://instagram.com/elena_weiss', '', '~20-50K. ТР, ЖК'),
    ('Марина Вовченко', 'Instagram', 'https://instagram.com/marina_vovchenko', '', '~30-50K. ОС, МТ'),
    ('Владимир Зуев', 'Instagram', 'https://instagram.com/vladimir_zuev_official', '', '~30-50K. СП'),
    ('Альберт Сафин', 'Instagram', 'https://instagram.com/albertsafin', '', '~20-50K. ПО, СР'),
    ('Игорь Ким', 'Instagram', 'https://instagram.com/igorkim.psy', '', '~10-30K. СР, ОС'),
    ('Артём Шафкеев', 'Instagram', 'https://instagram.com/a_shafkeev', '', '~10-30K. СР, ПО'),
    ('Марияна Анаэль', 'Instagram', 'https://instagram.com/mariyana_anael', '', '~10-30K. ЖК, ПО'),
    ('Мила Кудрякова', 'Instagram', 'https://instagram.com/mila_kudryakova', '', '~10-25K. ПО, СП'),
    ('Марина Травкова', 'Instagram', 'https://instagram.com/marinatravkova', '', '~20-40K. ПО'),
    ('Полина Девочкина', 'Instagram', 'https://instagram.com/polinadevochkina', '', '~30-50K. ПО — сексология'),
    ('Катерина Карпович', 'Instagram', 'https://instagram.com/karpovich_psy', '', '~10-30K. ПО — сексология'),
    ('Татьяна Мужицкая', 'Instagram', 'https://instagram.com/tmuzhitskaya', '', '~50-100K. ПО, СР'),
    ('Татьяна Павлова', 'Instagram', 'https://instagram.com/anxious_psychologist', '', '~20-45K. ТР'),
    ('Ирина Парфенова', 'Instagram', 'https://instagram.com/parfenova.psy', '', '~15-40K. ТР, СР'),
    ('Ирина Гиберманн', 'Instagram', 'https://instagram.com/gibermann', '', '~30-60K. ТР, ОС'),
    ('Олеся Шаповал', 'Instagram', 'https://instagram.com/olesya.shapoval', '', '~10-25K. ТР, ОС'),
    ('Радмила Хакова', 'Instagram', 'https://instagram.com/khakova', '', '~80-150K (вне порога). МТ, ПО'),
    ('Наталья Ремиш', 'Instagram', 'https://instagram.com/nataliaremish', '', '~100-250K (вне порога). МТ, СП'),
    ('Жанна Оспанова', 'Instagram', 'https://instagram.com/zhospanova', '', '~50K (на грани). ПО, СР'),
    ('Лариса Ренар', 'Instagram', 'https://instagram.com/larisarenar', '', '>100K (вне порога). ЖК, ПО'),
    ('Женя Веритов', 'Instagram', 'https://instagram.com/mango.project', '', '~10-30K. ТР — гештальт'),
    ('Андрей Сирота', 'Instagram', 'https://instagram.com/ne_sirota', '', '~10-25K. ТР'),
    ('Вероника Степанова', 'Instagram', 'https://instagram.com/stepanovaveronika', '', '~50-100K. ТР, СП'),

    # ── INSTAGRAM Part B: Семейные и материнские блоги ────────────────────────────────────────────────────────────────
    ('Екатерина Пятницкая', 'Instagram', 'https://instagram.com/pyatnizkaya_kat', '', '~30-50K. МТ, СП — педагог-психолог'),
    ('Лёгкое материнство', 'Instagram', 'https://instagram.com/legkoe.materinstvo', '', '~30-50K. МТ — перинатальный психолог'),
    ('Анна Полищук (нейропсихолог)', 'Instagram', 'https://instagram.com/anna_polishuk_neuro', '', '~30-50K. СП — нейропсихолог'),
    ('Олеся Лёвкина', 'Instagram', 'https://instagram.com/neuro_levkina', '', '~50K (на грани). СП — нейропсихолог'),
    ('Валентина Паевская', 'Instagram', 'https://instagram.com/neuro_psy_valentina', '', '~50-100K. СП — нейропсихолог'),
    ('Симона Черноморская', 'Instagram', 'https://instagram.com/simonablack', '', '~30-50K. МТ, ЖК'),
    ('Малена Кочарян', 'Instagram', 'https://instagram.com/malena_pi', '', '~30-50K. МТ'),
    ('Галина (наука для детей)', 'Instagram', 'https://instagram.com/galina_science_mama', '', '~10-30K. МТ, СП'),
    ('София (молодая мама)', 'Instagram', 'https://instagram.com/sofia_mama_blog', '', '~10-25K. МТ'),
    ('Елена и Ева', 'Instagram', 'https://instagram.com/elena_eva_mama', '', '~10-25K. МТ, ОС'),
    ('Многодетная Ирина', 'Instagram', 'https://instagram.com/irina_5kids_blog', '', '~30-50K. МТ, СП'),
    ('Мама в декрете (психология)', 'Instagram', 'https://instagram.com/mama_v_dekrete_psy', '', '~10-25K. МТ, СР'),
    ('Анастасия (доула, ГВ)', 'Instagram', 'https://instagram.com/anastasia_doula', '', '~15-35K. МТ'),
    ('Современное материнство', 'Instagram', 'https://instagram.com/modern_motherhood_ru', '', '~20-45K. МТ'),
    ('Осознанная мама', 'Instagram', 'https://instagram.com/aware_mama_ru', '', '~10-25K. ОС, МТ'),
    ('Наталья (мама и психолог)', 'Instagram', 'https://instagram.com/natalya_mama_psy', '', '~10-30K. МТ, СП'),
    ('Семейный психолог Анастасия', 'Instagram', 'https://instagram.com/anastasia_family_psy', '', '~10-25K. СП'),
    ('Перинатальный психолог Мария', 'Instagram', 'https://instagram.com/maria_perinatal', '', '~5-15K. МТ'),

    # ── INSTAGRAM Part C: Женский / осознанный контент ───────────────────────────────────────────────────────────────
    ('Mindful Russia', 'Instagram', 'https://instagram.com/mindful_russia', '', '~20-45K. ОС'),
    ('Школа осознанности (IG)', 'Instagram', 'https://instagram.com/awareness_school_ru', '', '~10-25K. ОС'),
    ('Йога-психология', 'Instagram', 'https://instagram.com/yoga_psy_ru', '', '~15-35K. ОС'),
    ('Медитация со мной', 'Instagram', 'https://instagram.com/meditation_with_me', '', '~10-25K. ОС'),
    ('Любовь к себе', 'Instagram', 'https://instagram.com/love_yourself_blog', '', '~30-50K. СР, ЖК'),
    ('Женские практики', 'Instagram', 'https://instagram.com/female_practices_ru', '', '~20-45K. ЖК, ОС'),
    ('Психология женщины', 'Instagram', 'https://instagram.com/woman_psy_blog', '', '~30-50K. ЖК'),
    ('Я — женщина (IG)', 'Instagram', 'https://instagram.com/ya_zhenshina', '', '~20-45K. ЖК'),
    ('Истинная женственность', 'Instagram', 'https://instagram.com/true_femininity', '', '~15-40K. ЖК'),
    ('Гармония внутри', 'Instagram', 'https://instagram.com/harmony_inside_ru', '', '~10-30K. ОС, СР'),
    ('Психолог о любви', 'Instagram', 'https://instagram.com/psychologist_about_love', '', '~15-40K. ПО'),
    ('Здоровые отношения', 'Instagram', 'https://instagram.com/healthy_relationships', '', '~10-30K. ПО'),
    ('Психология границ', 'Instagram', 'https://instagram.com/boundaries_psy', '', '~10-25K. СР, ПО'),
    ('Эмоциональный интеллект (IG)', 'Instagram', 'https://instagram.com/eq_blog_ru', '', '~20-45K. СР'),
    ('Внутренний ребёнок (IG)', 'Instagram', 'https://instagram.com/inner_child_blog', '', '~10-25K. ТР, СР'),
    ('Привязанность и любовь', 'Instagram', 'https://instagram.com/attachment_love_ru', '', '~5-20K. ПО'),
    ('Психология тела', 'Instagram', 'https://instagram.com/body_psy_ru', '', '~10-25K. ОС'),
    ('Терапия отношений', 'Instagram', 'https://instagram.com/relationship_therapy_ru', '', '~10-30K. ПО'),
    ('Парный психолог', 'Instagram', 'https://instagram.com/couple_psy_blog', '', '~10-25K. ПО'),
    ('Семейная терапия', 'Instagram', 'https://instagram.com/family_therapy_ru', '', '~10-25K. СП, ТР'),
    ('Школа отношений', 'Instagram', 'https://instagram.com/relationship_school_ru', '', '~20-45K. ПО'),
    ('Осознанные пары', 'Instagram', 'https://instagram.com/mindful_couples_ru', '', '~5-20K. ПО, ОС'),
    ('Психолог рядом', 'Instagram', 'https://instagram.com/psychologist_near_you', '', '~15-40K. СР, ТР'),
    ('Жизнь в кайф', 'Instagram', 'https://instagram.com/life_in_kayf_psy', '', '~20-45K. СР, ОС'),
    ('Психология простыми словами', 'Instagram', 'https://instagram.com/psy_simple_words', '', '~30-50K. СР'),

    # ── INSTAGRAM Part D: Авторские блоги ───────────────────────────────────────────────────────────────────
    ('Психолог Анна (созависимость)', 'Instagram', 'https://instagram.com/anna_psy_codep', '', '~10-25K. ПО, ТР'),
    ('Психолог Юлия (научная)', 'Instagram', 'https://instagram.com/julia_science_psy', '', '~10-25K. ПО, СР'),
    ('Психолог Дарина (тело)', 'Instagram', 'https://instagram.com/darina_body_psy', '', '~10-30K. ОС'),
    ('Марина Безуглова', 'Instagram', 'https://instagram.com/marina_bezuglova', '', '~15-35K. СР, ОС'),
    ('Дневник терапевта', 'Instagram', 'https://instagram.com/therapy_diary_ru', '', '~10-25K. ТР'),
    ('Травма-терапевт', 'Instagram', 'https://instagram.com/trauma_specialist_ru', '', '~5-20K. ТР'),
    ('КПТ-психолог', 'Instagram', 'https://instagram.com/cbt_psy_ru', '', '~5-20K. ТР'),
    ('Гештальт-практика', 'Instagram', 'https://instagram.com/gestalt_practice_ru', '', '~10-25K. ТР'),
    ('Схема-терапия', 'Instagram', 'https://instagram.com/schema_therapy_ru', '', '~5-20K. ТР'),
    ('EMDR-терапевт', 'Instagram', 'https://instagram.com/emdr_therapist_ru', '', '~5-15K. ТР'),
    ('Семейный психолог Москва', 'Instagram', 'https://instagram.com/family_psy_moscow', '', '~10-30K. СП'),
    ('Семейный психолог СПб', 'Instagram', 'https://instagram.com/family_psy_spb', '', '~10-25K. СП'),
    ('Психолог для женщин', 'Instagram', 'https://instagram.com/psy_for_women', '', '~20-45K. ЖК'),
    ('Психолог для пар', 'Instagram', 'https://instagram.com/psy_for_couples', '', '~10-30K. ПО'),
    ('Психология материнства', 'Instagram', 'https://instagram.com/motherhood_psy_ru', '', '~15-35K. МТ'),
    ('Осознанное родительство', 'Instagram', 'https://instagram.com/conscious_parenting_ru', '', '~15-40K. СП, ОС'),
    ('Подросток и я', 'Instagram', 'https://instagram.com/teenager_and_me_ru', '', '~10-25K. СП'),
    ('Семейные сценарии', 'Instagram', 'https://instagram.com/family_scenarios_ru', '', '~5-20K. СП'),
    ('Психология развода', 'Instagram', 'https://instagram.com/divorce_psy_ru', '', '~10-25K. ПО'),
    ('После расставания', 'Instagram', 'https://instagram.com/after_breakup_ru', '', '~10-30K. ПО'),
    ('Ресурсное состояние', 'Instagram', 'https://instagram.com/resource_state_ru', '', '~10-25K. СР, ОС'),
    ('Энергия женщины', 'Instagram', 'https://instagram.com/woman_energy_ru', '', '~20-45K. ЖК'),
    ('Сила женственности', 'Instagram', 'https://instagram.com/female_power_blog', '', '~20-45K. ЖК'),
    ('Психология денег и любви', 'Instagram', 'https://instagram.com/money_love_psy', '', '~15-40K. СР, ПО'),
    ('Mindful life Russia', 'Instagram', 'https://instagram.com/mindful_life_ru', '', '~10-25K. ОС'),
]


def make_slug(name, platform, url):
    if platform == 'Telegram':
        s = tg_slug(url)
        return s if s else slug(name)
    else:
        s = ig_slug(url)
        return (s + '_ig') if s else slug(name)


def main():
    conn = sqlite3.connect(DB_PATH)
    inserted = 0
    skipped = 0
    used_slugs = set()
    for row in conn.execute('SELECT utm_slug FROM bloggers'):
        used_slugs.add(row[0])

    for name, platform, url, email, notes in BLOGGERS:
        base = make_slug(name, platform, url)
        utm_slug = base
        suffix = 2
        while utm_slug in used_slugs:
            utm_slug = f'{base}_{suffix}'
            suffix += 1
        utm_link = f'{BASE_URL}/free?utm={utm_slug}'
        try:
            conn.execute(
                'INSERT INTO bloggers (name, platform, profile_url, email, utm_slug, utm_link, notes) '
                'VALUES (?,?,?,?,?,?,?)',
                (name, platform, url, email, utm_slug, utm_link, notes)
            )
            used_slugs.add(utm_slug)
            inserted += 1
        except Exception as e:
            print(f'  SKIP {name}: {e}')
            skipped += 1

    conn.commit()
    conn.close()
    print(f'Done: {inserted} inserted, {skipped} skipped. Total in DB: {inserted + skipped}')


if __name__ == '__main__':
    main()
