#!/usr/bin/env python3
"""
Пул почт SmakMail: txt-файл с ящиками, проверка через API, выдача свободных.

Файл mailboxes.txt (рядом со скриптом или путь в MAILBOX_POOL_FILE), по ящику на строку:
    адрес@домен.com:пароль
Строки, начинающиеся с #, и пустые строки игнорируются.

Ящик СВОБОДЕН, если по API в нём нет ни одного письма.
Если формат ответа не распознан или API недоступен, ящик НЕ выдаётся.

Использование в боте (стандартная библиотека, потокобезопасно):
    from mailbox_pool import Pool
    pool = Pool()                                  # токен из переменной SMAK_API_TOKEN
    email = pool.take_free(order_id)               # тот же заказ -> тот же адрес; None = свободных нет
    link = pool.fetch_link_for_order(order_id)     # ждёт письмо со ссылкой (нужен magic_link_auto.py)
    pool.release(order_id)                         # вернуть ящик, если выдать покупателю не удалось

Проверка из консоли (PowerShell):
    $env:SMAK_API_TOKEN = 'ТОКЕН'
    python mailbox_pool.py check --limit 5         # только показать статусы, ничего не выдаёт
    python mailbox_pool.py take TEST1              # выдать ящик тестовому заказу
    python mailbox_pool.py release TEST1           # вернуть
    python mailbox_pool.py stats
    python mailbox_pool.py link TEST1 --timeout 120

Пароли хранятся ТОЛЬКО в mailboxes.txt. В pool_state.json лежат адреса и статусы, без паролей.
Не загружайте mailboxes.txt в Git и в резервные копии.
"""

import argparse
import datetime
import getpass
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

API_BASE = "https://api.smakmail.com/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR") or HERE
POOL_FILE = os.environ.get("MAILBOX_POOL_FILE") or os.path.join(DATA_DIR, "mailboxes.txt")
STATE_FILE = os.environ.get("MAILBOX_POOL_STATE") or os.path.join(DATA_DIR, "pool_state.json")

API_PAUSE = 0.2            # пауза между запросами к API (лимит SmakMail 10/с, держим ~5/с)
MAX_CHECKS_PER_TAKE = 30   # сколько ящиков максимум проверить ради одной выдачи
MAX_UNKNOWN_IN_ROW = 3     # столько неопределённых ответов подряд = считаем, что API недоступен

EMPTY, HAS_MAIL, BAD, UNKNOWN = "empty", "has_mail", "bad", "unknown"
BAD_CODES = {"invalid_mailbox_password", "mailbox_password_required", "not_found"}


class PoolError(Exception):
    """Ошибка пула (нет токена, API недоступен и т.п.)."""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def check_mailbox(email_addr: str, password: str, token: str) -> str:
    """Возвращает EMPTY, HAS_MAIL, BAD (пароль неверный/ящика нет) или UNKNOWN."""
    url = f"{API_BASE}/mailbox/messages?" + urllib.parse.urlencode({"email": email_addr, "limit": 1})
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Mailbox-Password": password,
            "Accept": "application/json",
            "User-Agent": "mailbox-pool/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            payload = json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            payload = {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeEncodeError):
        return UNKNOWN

    if not isinstance(payload, dict):
        return UNKNOWN
    items = payload.get("items")
    if status == 200 and payload.get("ok") is True and isinstance(items, list):
        return HAS_MAIL if items else EMPTY
    err = payload.get("error")
    if isinstance(err, dict) and err.get("code") in BAD_CODES:
        return BAD
    return UNKNOWN


class Pool:
    def __init__(self, token: Optional[str] = None, pool_file: str = POOL_FILE, state_file: str = STATE_FILE):
        self._token_override = token
        self.pool_file = pool_file
        self.state_file = state_file
        self._lock = threading.RLock()

    # ---- служебное ----

    def _token(self) -> str:
        token = self._token_override or os.environ.get("SMAK_API_TOKEN", "")
        if not token:
            raise PoolError("Не задан токен SmakMail (переменная SMAK_API_TOKEN).")
        return token

    def read_pool(self) -> list:
        """[(email, password), ...] из txt. Файл читается заново при каждом вызове."""
        try:
            with open(self.pool_file, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError as e:
            raise PoolError(f"Не удалось прочитать {self.pool_file}: {e}") from e
        result, seen = [], set()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            email_addr, password = line.split(":", 1)
            email_addr, password = email_addr.strip().lower(), password.strip()
            if "@" not in email_addr or not password or email_addr in seen:
                continue
            seen.add(email_addr)
            result.append((email_addr, password))
        return result

    def _load_state(self) -> dict:
        try:
            with open(self.state_file, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("mailboxes", {})
        state.setdefault("orders", {})
        return state

    def _save_state(self, state: dict) -> None:
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_file)

    # ---- основной интерфейс ----

    def email_for_order(self, order_id) -> Optional[str]:
        with self._lock:
            return self._load_state()["orders"].get(str(order_id))

    def password_for(self, email_addr: str) -> Optional[str]:
        email_addr = email_addr.strip().lower()
        for addr, password in self.read_pool():
            if addr == email_addr:
                return password
        return None

    def take_free(self, order_id) -> Optional[str]:
        """
        Выдаёт свободный ящик заказу. Повторный вызов для того же заказа вернёт тот же адрес.
        None = подходящих свободных ящиков нет (пополните mailboxes.txt).
        """
        oid = str(order_id)
        with self._lock:
            state = self._load_state()
            if oid in state["orders"]:
                return state["orders"][oid]
            token = self._token()

            checks = unknown_in_row = 0
            for email_addr, password in self.read_pool():
                if state["mailboxes"].get(email_addr, {}).get("status") in ("issued", "used", "bad"):
                    continue
                if checks >= MAX_CHECKS_PER_TAKE:
                    break
                checks += 1
                result = check_mailbox(email_addr, password, token)
                time.sleep(API_PAUSE)

                if result == EMPTY:
                    state["mailboxes"][email_addr] = {"status": "issued", "order": oid, "ts": _now()}
                    state["orders"][oid] = email_addr
                    self._save_state(state)
                    return email_addr
                if result == HAS_MAIL:
                    state["mailboxes"][email_addr] = {"status": "used", "ts": _now()}
                    unknown_in_row = 0
                elif result == BAD:
                    state["mailboxes"][email_addr] = {"status": "bad", "ts": _now()}
                    unknown_in_row = 0
                else:
                    unknown_in_row += 1
                    if unknown_in_row >= MAX_UNKNOWN_IN_ROW:
                        self._save_state(state)
                        raise PoolError("API SmakMail не дал распознаваемого ответа несколько раз подряд.")
            self._save_state(state)
            return None

    def release(self, order_id) -> bool:
        """Снимает выдачу: ящик снова считается кандидатом (будет перепроверен)."""
        oid = str(order_id)
        with self._lock:
            state = self._load_state()
            email_addr = state["orders"].pop(oid, None)
            if email_addr is None:
                return False
            state["mailboxes"].pop(email_addr, None)
            self._save_state(state)
            return True

    def stats(self) -> dict:
        with self._lock:
            state = self._load_state()
            pool = self.read_pool()
        counts = {"в файле": len(pool), "issued": 0, "used": 0, "bad": 0, "не проверялись": 0}
        for addr, _pw in pool:
            status = state["mailboxes"].get(addr, {}).get("status")
            if status in counts:
                counts[status] += 1
            else:
                counts["не проверялись"] += 1
        return counts

    def fetch_link_for_order(self, order_id, timeout: float = 300, interval: float = 20) -> str:
        """Ждёт письмо со ссылкой в ящике этого заказа (использует magic_link_auto.py)."""
        email_addr = self.email_for_order(order_id)
        if not email_addr:
            raise PoolError(f"Заказу {order_id} ящик не выдан.")
        password = self.password_for(email_addr)
        if not password:
            raise PoolError("Пароль выданного ящика не найден в файле пула.")
        from magic_link_auto import wait_for_magic_link  # ленивый импорт: нужен только здесь

        return wait_for_magic_link(email_addr, password, timeout=timeout, interval=interval)


# ---------------------------------------------------------------- CLI

def _cmd_check(pool: Pool, limit: int) -> int:
    token = pool._token()
    items = pool.read_pool()
    if limit:
        items = items[:limit]
    totals = {EMPTY: 0, HAS_MAIL: 0, BAD: 0, UNKNOWN: 0}
    for addr, password in items:
        result = check_mailbox(addr, password, token)
        totals[result] += 1
        print(f"{addr}: {result}")
        time.sleep(API_PAUSE)
    print(f"\nИтого: свободных {totals[EMPTY]}, с письмами {totals[HAS_MAIL]}, "
          f"неверный пароль/нет ящика {totals[BAD]}, неопределённо {totals[UNKNOWN]}")
    if totals[UNKNOWN]:
        print("Неопределённо = ответ API не распознан. Такие ящики бот не выдаёт.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Пул почт SmakMail")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="показать статусы ящиков (ничего не выдаёт)")
    p_check.add_argument("--limit", type=int, default=0, help="проверить только первые N")
    p_take = sub.add_parser("take", help="выдать свободный ящик заказу")
    p_take.add_argument("order_id")
    p_rel = sub.add_parser("release", help="вернуть ящик заказа")
    p_rel.add_argument("order_id")
    sub.add_parser("stats", help="сводка по пулу")
    p_link = sub.add_parser("link", help="дождаться magic-link для заказа")
    p_link.add_argument("order_id")
    p_link.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    pool = Pool()
    try:
        if args.cmd in ("check", "take", "link") and not (os.environ.get("SMAK_API_TOKEN")):
            os.environ["SMAK_API_TOKEN"] = getpass.getpass("API-токен: ").strip()
        if args.cmd == "check":
            return _cmd_check(pool, args.limit)
        if args.cmd == "take":
            email_addr = pool.take_free(args.order_id)
            print(email_addr if email_addr else "Свободных ящиков нет.")
            return 0 if email_addr else 2
        if args.cmd == "release":
            print("Возвращён." if pool.release(args.order_id) else "За этим заказом ящика нет.")
            return 0
        if args.cmd == "stats":
            for key, value in pool.stats().items():
                print(f"{key}: {value}")
            return 0
        if args.cmd == "link":
            print(pool.fetch_link_for_order(args.order_id, timeout=args.timeout))
            return 0
    except PoolError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # ошибки ожидания ссылки из magic_link_auto и т.п.
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
