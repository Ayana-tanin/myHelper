"""Телеграм-бот: раз в час спрашивает «что делаешь?» и записывает ответы в log.csv.

Команды:
  /now   — сразу задать вопрос и дальше спрашивать каждый час
  /stop  — перестать спрашивать
  /today — показать записи за сегодня

Токен берётся из переменной окружения BOT_TOKEN или из файла token.txt рядом со скриптом.
"""

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG_FILE = BASE / "log.csv"
STATE_FILE = BASE / "state.json"
INTERVAL = 60 * 60  # секунд между вопросами
QUESTION = "Что делаешь? Что делала в течение этого часа?"


def load_token():
    token = os.environ.get("BOT_TOKEN")
    if not token and (BASE / "token.txt").exists():
        token = (BASE / "token.txt").read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Нет токена: положите его в token.txt или в переменную BOT_TOKEN")
    return token


API = f"https://api.telegram.org/bot{load_token()}/"


def api(method, **params):
    data = urllib.parse.urlencode(params).encode()
    timeout = int(params.get("timeout", 0)) + 10
    with urllib.request.urlopen(API + method, data=data, timeout=timeout) as resp:
        return json.loads(resp.read())["result"]


def send(chat_id, text):
    api("sendMessage", chat_id=chat_id, text=text)


# chat_id -> unix-время следующего вопроса; хранится в файле, чтобы пережить перезапуск
def load_state():
    if STATE_FILE.exists():
        return {int(k): v for k, v in json.loads(STATE_FILE.read_text()).items()}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def write_answer(chat_id, text):
    new_file = not LOG_FILE.exists()
    # utf-8-sig, чтобы Excel нормально открыл кириллицу
    with LOG_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["дата", "время", "chat_id", "ответ"])
        now = datetime.now()
        w.writerow([now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), chat_id, text])


def today_entries(chat_id):
    if not LOG_FILE.exists():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    with LOG_FILE.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, delimiter=";"))[1:]
    return [f"{r[1]} — {r[3]}" for r in rows if r[0] == today and r[2] == str(chat_id)]


def handle(msg, state):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    if not text:
        return

    command = text.split()[0].split("@")[0].lower()
    if command in ("/start", "/help"):
        send(chat_id, "Привет! /now — начать (буду спрашивать каждый час), "
                      "/stop — остановить, /today — что записано за сегодня.")
    elif command == "/now":
        send(chat_id, QUESTION)
        state[chat_id] = time.time() + INTERVAL
        save_state(state)
    elif command == "/stop":
        state.pop(chat_id, None)
        save_state(state)
        send(chat_id, "Остановила. Чтобы начать снова — /now")
    elif command == "/today":
        entries = today_entries(chat_id)
        send(chat_id, "\n".join(entries) if entries else "Сегодня записей пока нет.")
    elif text.startswith("/"):
        send(chat_id, "Не знаю такой команды. Есть /now, /stop, /today")
    else:
        write_answer(chat_id, text)
        send(chat_id, "Записала ✅")


def main():
    state = load_state()
    offset = 0
    print("Бот запущен. Ctrl+C — остановить.")
    while True:
        try:
            # ждём сообщений, но не дольше, чем до ближайшего вопроса
            wait = min([30] + [max(0, int(t - time.time())) for t in state.values()])
            for upd in api("getUpdates", offset=offset, timeout=wait):
                offset = upd["update_id"] + 1
                if "message" in upd:
                    handle(upd["message"], state)

            now = time.time()
            for chat_id, due in list(state.items()):
                if now >= due:
                    send(chat_id, QUESTION)
                    state[chat_id] = due + INTERVAL if due + INTERVAL > now else now + INTERVAL
                    save_state(state)
        except KeyboardInterrupt:
            break
        except Exception as e:  # сеть отвалилась и т.п. — подождать и продолжить
            print("Ошибка:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
