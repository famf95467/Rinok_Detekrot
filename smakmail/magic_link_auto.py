#!/usr/bin/env python3
"""
Автоматическое получение magic-link из почтового ящика SmakMail по IMAP.

Как модуль (внутри бота):
    from magic_link_auto import wait_for_magic_link
    link = wait_for_magic_link("box@domain.com", "mailbox_password", timeout=300)

Как программа (любой язык может вызвать и прочитать stdout):
    python magic_link_auto.py --login box@domain.com --password PASS --timeout 300
    # ссылка печатается в stdout, ошибки в stderr
    # коды выхода: 0 - найдено, 2 - ошибка авторизации, 3 - таймаут, 1 - прочее

Пароль можно передать через переменную окружения SMAK_PASSWORD
(чтобы он не светился в списке процессов).
"""

import argparse
import email
import email.message
import imaplib
import os
import re
import sys
import time
from getpass import getpass
from html import unescape
from typing import Optional

IMAP_HOST = "imap.smakmail.com"
IMAP_PORT = 993

# Поправьте под реальный вид ссылок платформы, если он отличается
DEFAULT_PATTERN = r'https?://[^\s"\'<>]*magic-link[^\s"\'<>]*'


class MagicLinkError(Exception):
    """Базовая ошибка."""


class AuthError(MagicLinkError):
    """Неверный логин/пароль (повторять бессмысленно)."""


class LinkTimeout(MagicLinkError):
    """Письмо со ссылкой не пришло за отведённое время."""


def _connect(login: str, password: str) -> imaplib.IMAP4_SSL:
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=20)
    except (OSError, imaplib.IMAP4.error) as e:
        raise MagicLinkError(f"Нет соединения с {IMAP_HOST}:{IMAP_PORT}: {e}") from e
    try:
        conn.login(login, password)
    except imaplib.IMAP4.error as e:
        try:
            conn.logout()
        except Exception:
            pass
        raise AuthError(f"Ошибка авторизации: {e}") from e
    return conn


def _extract_text(msg: email.message.Message) -> str:
    """Собирает text/plain и text/html части письма в одну строку."""
    chunks = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        if "attachment" in str(part.get("Content-Disposition") or ""):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                chunks.append(payload.decode(charset, errors="replace"))
        except (LookupError, UnicodeError):
            continue
    return "\n".join(chunks)


def _find_link(body: str, pattern: re.Pattern) -> Optional[str]:
    match = pattern.search(body)
    # unescape: в HTML-письмах символ & в ссылках записан как &amp;
    return unescape(match.group(0)) if match else None


def _check_mailbox_once(login: str, password: str, pattern: re.Pattern) -> Optional[str]:
    """Один проход: ищет ссылку в непрочитанных письмах (от новых к старым)."""
    conn = _connect(login, password)
    try:
        status, _ = conn.select("INBOX")
        if status != "OK":
            raise MagicLinkError("Не удалось открыть INBOX")

        status, data = conn.uid("search", None, "UNSEEN")
        if status != "OK":
            raise MagicLinkError("Ошибка поиска писем")

        for uid in reversed(data[0].split()):
            # BODY.PEEK[] не ставит флаг \Seen сам по себе
            status, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            link = _find_link(_extract_text(msg), pattern)
            if link:
                conn.uid("store", uid, "+FLAGS", "\\Seen")
                return link
        return None
    except (imaplib.IMAP4.error, OSError) as e:
        raise MagicLinkError(f"Ошибка IMAP: {e}") from e
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def wait_for_magic_link(
    login: str,
    password: str,
    timeout: float = 300,
    interval: float = 20,
    pattern: str = DEFAULT_PATTERN,
) -> str:
    """
    Ждёт письмо со ссылкой в ящике и возвращает её.
    Бросает AuthError (неверный пароль), LinkTimeout (не пришло за timeout секунд)
    или MagicLinkError (сеть/сервер недоступны до конца таймаута).
    """
    compiled = re.compile(pattern, re.IGNORECASE)
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None

    while True:
        try:
            link = _check_mailbox_once(login, password, compiled)
            if link:
                return link
            last_error = None
        except AuthError:
            raise  # неверные данные - нет смысла повторять
        except MagicLinkError as e:
            last_error = e  # временная проблема сети - пробуем ещё раз

        if time.monotonic() + interval > deadline:
            if last_error:
                raise last_error
            raise LinkTimeout(f"Письмо со ссылкой не пришло за {timeout:.0f} сек.")
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Получить magic-link из ящика SmakMail")
    parser.add_argument("--login", help="Полный адрес почты")
    parser.add_argument("--password", help="Пароль почты (или переменная SMAK_PASSWORD)")
    parser.add_argument("--timeout", type=float, default=300, help="Сколько секунд ждать письмо")
    parser.add_argument("--interval", type=float, default=20, help="Пауза между проверками, сек (не меньше 15: лимит переподключений SmakMail)")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="Regex ссылки")
    args = parser.parse_args()

    login = args.login or input("Логин (email): ").strip()
    password = args.password or os.environ.get("SMAK_PASSWORD") or getpass("Пароль: ")

    try:
        link = wait_for_magic_link(login, password, args.timeout, args.interval, args.pattern)
    except AuthError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except LinkTimeout as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 3
    except MagicLinkError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Прервано.", file=sys.stderr)
        return 1

    print(link)
    return 0


if __name__ == "__main__":
    sys.exit(main())
