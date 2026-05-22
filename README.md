# FocusFlow — очень простая инструкция (шаг за шагом)

Ниже инструкция **максимально просто**, чтобы запустить и не думать.

---

## Что ты получишь
- Задачи на день.
- Помодоро таймер.
- Статистика за 7 дней.
- Напоминания в Telegram через бота.
- Backend можно поднять в Google Colab.

---

## Вариант 1 (рекомендую): запуск через Google Colab

### Шаг 0. Что нужно заранее
1. Telegram-бот (через @BotFather).
2. Токен бота (вида `123456:ABC...`).
3. Этот проект в GitHub (или загруженный в Colab).

### Шаг 1. Открой Google Colab
Создай новый notebook.

### Шаг 2. Выполни в Colab
```python
!git clone <ТВОЙ_URL_РЕПО>
%cd Chto-to
!pip install -r backend/requirements.txt pyngrok
```

### Шаг 3. Вставь токен бота
```python
import os
os.environ['TG_BOT_TOKEN'] = '123456:ABC...'
```

### Шаг 4. Запусти backend
```python
%run backend/colab_run.py
```

После этого увидишь строку типа:
`Backend URL: https://xxxx.ngrok-free.app`

**Скопируй этот URL.**

### Шаг 5. В Mini App вставь URL
1. Открой Mini App.
2. В блоке **API / Colab** вставь URL из Colab.
3. Нажми **Сохранить API**.
4. Готово.

---

## Как проверить, что всё работает
1. Добавь задачу → обнови Mini App → задача должна остаться.
2. Поставь напоминание на 1–2 минуты вперёд.
3. Дождись сообщения от бота.

---

## ВАЖНО (частые проблемы)
1. **Бот не пишет** → сначала открой чат с ботом и нажми **Start**.
2. **Colab отключился** → backend умер, запусти ячейку снова.
3. **URL поменялся** после перезапуска Colab/ngrok → снова вставь новый URL в Mini App.

---

## Локальный запуск (если Colab не нужен)
```bash
cd backend
pip install -r requirements.txt
export TG_BOT_TOKEN=<your_bot_token>
uvicorn app:app --host 0.0.0.0 --port 8000
```

Потом в Mini App в поле **API / Colab** укажи:
`http://127.0.0.1:8000`

---

## Что делает backend
- `POST /state` — сохраняет твои задачи/таймер.
- `GET /state/{user_id}` — загружает твои данные.
- `POST /reminder` — ставит напоминание.
