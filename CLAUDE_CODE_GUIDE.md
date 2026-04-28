# ТЕХНИЧЕСКОЕ ЗАДАНИЕ — verevery.ru / Колода «Ближе»
> Этот файл прикладывать к каждому промпту в Claude Code.
> Содержит: стек, архитектуру, стайлгайд, логику доступа и структуру данных.

---

## СТЕК И СЕРВЕР

- **Сервер:** Linux Ubuntu, домен verevery.ru
- **Шаблонизатор:** Jinja2 (Flask / Python)
- **Шаблоны:** `/opt/verevery/app/templates/`
- **Статика:** `/opt/verevery/app/static/`
- **Деплой:** `scp` + `systemctl restart verevery`
- **База данных:** JSON файлы для карточек, SQLite для пользователей и платежей

---

## АРХИТЕКТУРА СТРАНИЦ

```
verevery.ru/              → главная (редирект на /free)
verevery.ru/free          → лендинг с 5 бесплатными карточками
verevery.ru/buy           → лендинг с оплатой (690 ₽)
verevery.ru/cards         → полные 60 карточек (только после оплаты)
verevery.ru/admin         → админка редактирования карточек (пароль)
verevery.ru/auth          → вход по телефону (magic link / SMS код)
```

---

## ЛОГИКА ДОСТУПА

### Бесплатная зона (/free)
- Доступна всем без регистрации
- 5 карточек — по 2 из блоков Действие и Забота, 1 из Вопрос
- Кнопка «Получить полный доступ» → /buy

### Платная зона (/cards)
- Доступна только после оплаты
- Вход без пароля — только телефон + SMS код (magic link)
- Алгоритм:
  1. Человек платит на /buy через ЮКассу
  2. После успешной оплаты → редирект на /auth
  3. Вводит номер телефона → получает SMS с кодом
  4. Вводит код → создаётся сессия → редирект на /cards
  5. При следующем визите — снова телефон + код (без пароля)
- Сессия хранится в cookie (30 дней)

### Защита от шаринга ссылки
- Страница /cards проверяет валидность сессии
- Без валидной сессии → редирект на /auth
- Один аккаунт (телефон) = один активный пользователь

---

## UTM ОТСЛЕЖИВАНИЕ

### Как работает
- Блогер получает ссылку: `verevery.ru/free?utm=имя_блогера`
- При заходе UTM сохраняется в cookie на 60 дней
- При оплате UTM передаётся вместе с данными платежа
- Записывается в Google Sheets автоматически через webhook

### Cookie
```javascript
// Сохранение UTM при заходе
const params = new URLSearchParams(window.location.search);
const utm = params.get('utm');
if (utm) {
  const expires = new Date();
  expires.setDate(expires.getDate() + 60);
  document.cookie = `utm_source=${utm}; expires=${expires.toUTCString()}; path=/`;
}

// Чтение UTM при оплате
function getUtm() {
  const match = document.cookie.match(/utm_source=([^;]+)/);
  return match ? match[1] : 'direct';
}
```

### Google Sheets (через webhook ЮКассы)
При каждой оплате автоматически записывается строка:
| Дата | Телефон | UTM | Блогер | Сумма | Комиссия 30% |

---

## ОПЛАТА

- **Платёжная система:** ЮКасса (поддерживает самозанятых, выдаёт чеки)
- **Цена:** 690 ₽
- **Методы:** карта, СБП, QR
- **Webhook:** после успешной оплаты ЮКасса делает POST запрос на наш сервер
- **Что происходит после оплаты:**
  1. Webhook записывает продажу в БД и Google Sheets
  2. Пользователь получает редирект на /auth
  3. После входа — доступ к /cards открывается навсегда

---

## СТРУКТУРА ДАННЫХ КАРТОЧЕК

### Файл: /opt/verevery/app/data/cards.json
```json
{
  "action": [
    {
      "id": "A-01",
      "level": "Средний",
      "text": "Полный текст карточки лицевой стороны...",
      "hint": "Подсказка курсивом внизу карточки (может быть пустой)",
      "why": "Текст для кнопки Зачем это...",
      "brain": "Текст для кнопки Мозг (HTML с тегами strong и div.modal-item)...",
      "science": "Текст для кнопки Наука (HTML)..."
    }
  ],
  "question": [ ... ],
  "care": [ ... ]
}
```

### Бесплатные карточки: /opt/verevery/app/data/free_cards.json
Отдельный файл с 5 карточками для страницы /free.
Структура идентична cards.json.

### ВАЖНО
- Никогда не сокращать тексты карточек
- Никогда не менять смысл при редактировании
- Все тексты редактируются только через /admin или напрямую в JSON

---

## АДМИНКА (/admin)

### Защита
- Простой пароль в переменной окружения `ADMIN_PASSWORD`
- При входе создаётся сессия на 24 часа

### Интерфейс
- Список всех карточек с возможностью редактирования
- Три вкладки: Действие / Вопрос / Забота
- Каждая карточка — аккордеон с полями:
  - Уровень (выпадающий список: Лёгкий / Средний / Глубокий)
  - Текст карточки (textarea, большое)
  - Подсказка (textarea)
  - Зачем это (textarea)
  - Мозг (textarea)
  - Наука (textarea)
- Кнопка «Сохранить» — записывает в cards.json
- Изменения сразу видны пользователям

---

## СТАЙЛГАЙД

### Шрифты (подключены через Google Fonts в base.html)
- **Заголовки** (H1, H2, H3, логотип, названия блоков, цены): `Cormorant Garamond`, serif, weight 400/500, курсив
- **Всё остальное** (кнопки, подписи, текст, навигация): `Exo 2`, sans-serif, weight 300/400/500

### CSS переменные (объявлены в base.html)
```css
:root {
  --cream: #FAF7F2;      /* основной фон страницы */
  --white: #FFFFFF;      /* фон карточек */
  --beige: #EDE6DA;      /* фон секций, рамки карточек */
  --sand: #D4C8B5;       /* вторичные рамки, мелкий текст */
  --dark: #2A2118;       /* основной текст, тёмные кнопки, footer */
  --muted: #8C7E72;      /* вспомогательный текст, подписи */
  --accent: #A67C52;     /* акцент (логотип, теги, hover) */
  --light-accent: #C9A97A; /* светлый акцент (italic CTA, кнопка accent) */
}
```

### Кнопки
```css
/* Всегда border-radius: 50px — никаких квадратных кнопок */
/* padding: 16px 24px, font-size: 14px, font-weight: 500, letter-spacing: 0.5px */
/* На мобильных: display: block, width: 100% */

.btn-primary  { background: var(--dark);   color: white; }
.btn-primary:hover { background: var(--accent); }

.btn-outline  { background: transparent; border: 1px solid var(--sand); color: var(--dark); }
.btn-outline:hover { background: var(--dark); color: white; }

.btn-accent   { background: var(--accent); color: white; }
.btn-accent:hover { background: var(--dark); }
```

### Карточки
```css
.card {
  background: var(--white);
  border: 1px solid var(--beige);
  border-radius: 20px;           /* или 24px для крупных */
  box-shadow: 0 2px 20px rgba(42,33,24,0.06);
  padding: 24-28px;
}
```

### Маркеры блоков (вместо эмодзи — плоские полоски)
```css
/* Вертикальная полоска слева от названия блока */
.marker-action   { background: var(--accent); }       /* тёплый коричневый */
.marker-question { background: var(--muted); }        /* серо-бежевый */
.marker-care     { background: var(--light-accent); } /* светлый золотой */

/* На карточке — горизонтальная полоска */
width: 20px; height: 4px; border-radius: 2px;
```

### Уровни сложности
```css
.level-easy   { background: var(--light-accent); } /* Лёгкий */
.level-medium { background: var(--accent); }       /* Средний */
.level-deep   { background: var(--dark); }         /* Глубокий */
/* Отображается как pip (6-7px круг) рядом с текстом уровня */
```

### Типографика
```css
.label {
  font-family: 'Exo 2'; font-size: 10px;
  letter-spacing: 2.5px; text-transform: uppercase; color: var(--sand);
}
.h2 {
  font-family: 'Cormorant Garamond'; font-size: 34px;
  font-weight: 500; line-height: 1.15;
}
.h3 { font-family: 'Cormorant Garamond'; font-size: 24px; font-weight: 500; }
.body-text { font-family: 'Exo 2'; font-size: 14px; font-weight: 300; line-height: 1.75; color: var(--muted); }
```

### Секции
```css
/* Чередование фонов — разделители через смену фона, не линии */
.section-cream { background: var(--cream); }
.section-beige { background: var(--beige); }
.section-dark  { background: var(--dark); }

padding: 48px 20px;
max-width контента: 480px, margin: 0 auto;
```

### Навигация
```css
position: fixed; top: 0;
background: rgba(250,247,242,0.94); backdrop-filter: blur(16px);
/* Логотип: "vere" тёмный + "very" var(--accent) */
/* Кнопки в nav: border-radius 50px, padding: 7px 16px */
```

### Модалка (bottom sheet)
```css
border-radius: 24px 24px 0 0;
background: var(--cream);
/* Ручка сверху: 36px × 3px, color var(--sand), margin: 14px auto */
animation: slideUp 0.3s cubic-bezier(0.4,0,0.2,1);
max-height: 78vh; overflow-y: auto;
```

### Свайпер карточек
```css
/* Точки навигации */
.dot         { width: 6px; height: 6px; border-radius: 3px; background: var(--sand); }
.dot.active  { width: 20px; background: var(--dark); }
/* Transition: all 0.3s */
```

### CSS — важные правила
- **НИКОГДА** не использовать Tailwind классы
- Все стили писать в `<style>` блоке или отдельном CSS файле
- **НИКОГДА** не писать inline стили кроме единичных значений (margin, padding, color для динамических данных)
- Стили в Jinja2 шаблонах — в блоке `{% block head %}` внутри `<style>`

---

## СТРУКТУРА JINJA2 ШАБЛОНОВ

```
base.html — содержит блоки:
  {% block title %}   — заголовок вкладки
  {% block head %}    — доп. CSS (сюда пишем <style>)
  {% block nav %}     — навигация (снаружи main)
  {% block content %} — основной контент
  {% block scripts %} — JS перед </body>

Каждая новая страница:
  {% extends "base.html" %}
  {% block content %} ... {% endblock %}
```

---

## ИНТЕРФЕЙС КАРТОЧЕК

### Логика навигации
1. Главный экран → 3 кнопки выбора блока (Действие / Вопрос / Забота)
2. Клик на блок → переход к карточкам этого блока
3. Листание карточек — **свайп** влево/вправо (touchstart / touchend)
4. Нумерация в правом нижнем углу карточки: «1 / 20»
5. Точки-навигация под карточкой (активная — широкая)
6. Кнопка «← Блоки» в навигации — возврат к выбору блока

### Три кнопки под карточкой
- **Зачем это** — открывает модалку снизу с текстом «why»
- **Мозг** — открывает модалку с текстом «brain»
- **Наука** — открывает модалку с текстом «science»
- При свайпе — модалка закрывается автоматически
- Активная кнопка — тёмный фон

### Свайп (JS)
```javascript
let startX = 0;
container.addEventListener('touchstart', e => {
  startX = e.touches[0].clientX;
}, { passive: true });

container.addEventListener('touchend', e => {
  const diff = startX - e.changedTouches[0].clientX;
  if (Math.abs(diff) > 48) {
    if (diff > 0) goToCard(currentIndex + 1); // свайп влево → следующая
    else goToCard(currentIndex - 1);           // свайп вправо → предыдущая
  }
}, { passive: true });
```

---

## БЕСПЛАТНЫЕ КАРТОЧКИ (5 штук)

Показываются на странице /free без регистрации:

| № | Блок | ID | Карточка |
|---|------|----|----------|
| 1 | Действие | А-02 | Записка в кармане |
| 2 | Забота | З-03 | Я рада(д), что ты есть |
| 3 | Вопрос | В-03 | Твой язык любви |
| 4 | Вопрос | В-11 | Когда ты чувствуешь себя собой |
| 5 | Забота | З-01 | Я смотрю на тебя — и мне хорошо |

---

## ЦЕНА И КОМИССИИ

- **Цена полного доступа:** 690 ₽
- **Комиссия блогеру:** 30% = 207 ₽ с каждой продажи
- **Расчёт комиссии:** автоматически в Google Sheets по UTM метке
- **Платёжная система:** ЮКасса (самозанятый, автоматический чек)

---

## ЧТО НЕЛЬЗЯ ДЕЛАТЬ (критично)

- ❌ Сокращать тексты карточек — любое сокращение меняет смысл
- ❌ Использовать Tailwind классы
- ❌ Писать inline стили для блоков (только для единичных динамических значений)
- ❌ Хранить тексты карточек внутри HTML — только через cards.json
- ❌ Упоминать «оборотную сторону карточки» — у нас нет переворота, только кнопки
- ❌ Использовать эмодзи для обозначения блоков — только плоские маркеры-полоски
- ❌ Квадратные кнопки — все кнопки border-radius: 50px

---

*Версия: 1.0 · Проект: verevery.ru / Колода «Ближе»*
