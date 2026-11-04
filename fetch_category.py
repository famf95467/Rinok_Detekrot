# -*- coding: utf-8 -*-
"""Детектор рынка: загрузчик страницы категории FunPay (версия 1).

Делает не больше одного прохода в день: проверяет robots.txt, затем один раз скачивает
публичную страницу категории как гость и сохраняет её в pages\\kategoriya_ГГГГ-ММ-ДД.htm.
Потом запускает parse_category.py на этой странице.

Что загрузчик НЕ делает: не входит в аккаунт, не шлёт никаких cookie, кроме валюты показа cy=rub
(её можно отключить: --currency none), не решает капчу, не меняет адрес
и заголовки, чтобы обойти защиту, не повторяет запрос после блокировки, не ходит параллельно.
При капче, блокировке, редиректе или запрете в robots.txt он останавливается и пишет, что делать.

Запуск:  python fetch_category.py
Только Python 3 без дополнительных библиотек.
"""
import argparse, datetime, gzip, json, os, random, re, socket, subprocess, sys, time
import urllib.error, urllib.request, urllib.robotparser
from urllib.parse import urlparse

BASE = os.environ.get('MARKET_TEST_BASE', 'https://funpay.com')   # переменные MARKET_TEST_* только для проверки на локальном сервере
USER_AGENT = 'MarketDetector/1.0 (personal price research; one page per day; guest)'
PAUSE = float(os.environ['MARKET_TEST_PAUSE']) if 'MARKET_TEST_PAUSE' in os.environ else None
TIMEOUT = float(os.environ.get('MARKET_TEST_TIMEOUT', '30'))
MAX_BYTES = 40 * 1024 * 1024
# Единственная разрешённая cookie: выбор валюты показа (имя cy найдено в браузере в гостевом режиме).
# Это не вход в аккаунт. Cookie сессии и любые другие загрузчик отправить не может.
CURRENCY_COOKIES = {'rub': 'cy=rub', 'usd': 'cy=usd', 'eur': 'cy=eur', 'none': None}
BLOCK_STATUSES = {401, 403, 407, 429, 451, 503} | set(range(520, 530))
CAPTCHA_MARKERS = r'captcha|hcaptcha|cf-chl|just a moment|attention required|ddos-guard|checking your browser|проверка браузера|вы не робот'


class Stop(Exception):
    def __init__(self, code, title, detail='', body=b''):
        super().__init__(title)
        self.code, self.title, self.detail, self.body = code, title, detail, body


def pause(lo, hi):
    time.sleep(PAUSE if PAUSE is not None else random.uniform(lo, hi))


def today():
    return datetime.date.today().isoformat()      # дата на вашем ПК


def http_get(url, cookie=None):
    """Один GET без входа и без авторизации. Из cookie можно послать только валюту показа (см. CURRENCY_COOKIES).
    Возвращает (статус, итоговый адрес, тело)."""
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,text/plain;q=0.9,*/*;q=0.5',
        'Accept-Language': 'ru-RU,ru;q=0.9',
        'Accept-Encoding': 'gzip',
    }
    if cookie:
        headers['Cookie'] = cookie
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener()          # без обработчика cookies: ничего не запоминается между запросами
    try:
        resp = opener.open(req, timeout=TIMEOUT)
        status, final, headers = resp.status, resp.geturl(), resp.headers
    except urllib.error.HTTPError as e:
        resp, status, final, headers = e, e.code, e.geturl(), e.headers
    body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise Stop(4, 'Ответ слишком большой', f'больше {MAX_BYTES // 1024 // 1024} МБ, не сохраняю')
    if headers.get('Content-Encoding', '').lower() == 'gzip':
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return status, final, body


def get_once_retry_on_network(url, cookie=None):
    """Сетевая ошибка (таймаут, обрыв): один повтор через паузу. Ответы сайта (403, 429 и т.д.) не повторяются."""
    try:
        return http_get(url, cookie)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e1:
        print(f'Сетевая ошибка ({type(e1).__name__}), один повтор через минуту...')
        pause(60, 60)
        try:
            return http_get(url, cookie)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e2:
            raise Stop(5, 'Нет связи с сайтом', f'{type(e2).__name__}: {e2}') from e2


def check_robots(path):
    status, final, body = get_once_retry_on_network(BASE + '/robots.txt')
    if status == 404:
        print('robots.txt нет (404), ограничений от него нет.')
        return
    if status in BLOCK_STATUSES:
        raise Stop(2, f'Сайт отвечает HTTP {status} на robots.txt', 'Похоже на блокировку или защиту.', body)
    if status != 200:
        raise Stop(4, f'Неожиданный ответ HTTP {status} на robots.txt', '', body)
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode('utf-8', 'replace').splitlines())
    if not rp.can_fetch(USER_AGENT, BASE + path):
        raise Stop(2, 'robots.txt запрещает эту страницу', f'Путь {path} закрыт для роботов.')
    print(f'robots.txt прочитан: путь {path} разрешён.')


def check_page(status, final, body, path):
    if status in BLOCK_STATUSES:
        raise Stop(2, f'Сайт отвечает HTTP {status}', 'Похоже на блокировку, лимит запросов или защиту.', body)
    if status != 200:
        raise Stop(4, f'Неожиданный ответ HTTP {status}', 'Страница не отдана, формат неизвестен.', body)
    if urlparse(final).path.rstrip('/') != path.rstrip('/'):
        raise Stop(2, 'Сайт перенаправил на другой адрес', f'Вместо {path} пришёл {final} (вход, капча или защита).', body)
    text = body.decode('utf-8', 'replace')
    items = len(re.findall(r'class="tc-item', text))
    if items == 0:
        if re.search(CAPTCHA_MARKERS, text[:300000], re.I):
            raise Stop(2, 'Сайт показывает капчу или проверку браузера', 'Загрузчик её не обходит.', body)
        raise Stop(4, 'В ответе нет лотов', 'Страница пришла, но разметка лотов не найдена.', body)
    return text, items


def run_parser(page, date, out_dir, marks):
    parser = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parse_category.py')
    if not os.path.exists(parser):
        print('parse_category.py рядом не найден, разбор пропущен.')
        return 0
    print('--- Запускаю parse_category.py ---')
    return subprocess.run([sys.executable, parser, page, '--date', date, '--out', out_dir, '--marks', marks]).returncode


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='Один проход в день по странице категории FunPay (гость).')
    ap.add_argument('--path', default='/lots/1112/', help='путь категории, по умолчанию «Прочее GTA 5 RP, SAMP»')
    ap.add_argument('--pages', default='pages')
    ap.add_argument('--out', default='out')
    ap.add_argument('--state', default='fetch_state.json')
    ap.add_argument('--marks', default='marks.csv')
    ap.add_argument('--currency', choices=sorted(CURRENCY_COOKIES), default='rub',
                    help='валюта показа: rub (по умолчанию), usd, eur или none (не посылать ничего)')
    ap.add_argument('--no-parse', action='store_true')
    a = ap.parse_args()
    if not re.fullmatch(r'/lots/\d+/', a.path):
        sys.exit('Разрешены только страницы категорий вида /lots/ЧИСЛО/.')

    day = today()
    state = {}
    if os.path.exists(a.state):
        try:
            state = json.load(open(a.state, encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
    if state.get('дата') == day:
        print(f'Сегодня ({day}) проход уже был: {state.get("результат", "?")}. Один проход в день, повторяйте завтра.')
        return 3

    def save_state(result):
        with open(a.state, 'w', encoding='utf-8') as f:
            json.dump({'дата': day, 'результат': result}, f, ensure_ascii=False)

    save_state('начат, не завершён')               # попытка считается сразу, даже если окно закрыли
    os.makedirs(a.pages, exist_ok=True)
    try:
        print(f'Дата {day}. Гостевой режим, без входа в аккаунт. Проверяю robots.txt...')
        check_robots(a.path)
        pause(10, 20)
        cookie = CURRENCY_COOKIES[a.currency]
        print('Загружаю страницу категории (один запрос'
              + (f', валюта показа {cookie}: это настройка отображения, не вход в аккаунт' if cookie else ', без cookie')
              + ')...')
        status, final, body = get_once_retry_on_network(BASE + a.path, cookie)
        text, items = check_page(status, final, body, a.path)
    except Stop as s:
        save_state(f'остановлен: {s.title}')
        if s.body:
            stop_file = os.path.join(a.pages, f'_stop_{day}.html')
            with open(stop_file, 'wb') as f:
                f.write(s.body[:500000])
            print(f'Ответ сайта сохранён для просмотра: {stop_file}')
        print(f'\nСТОП: {s.title}. {s.detail}'.rstrip())
        print('Загрузчик ничего не обходит и сегодня больше не повторит запрос.')
        print('Что делать: сообщите «Бизнесс» через пользователя; решение принимает пользователь.')
        print('Пока можно сохранять страницу вручную в браузере (гостем).')
        return s.code

    name = f'kategoriya_{day}.htm'
    if os.path.exists(os.path.join(a.pages, name)):
        name = f'kategoriya_{day}_auto.htm'        # не затираем вашу ручную страницу
    page = os.path.join(a.pages, name)
    with open(page, 'wb') as f:
        f.write(body)
    save_state('ok')
    units = set(re.findall(r'<span class="unit">([^<]*)</span>', text))
    print(f'Сохранено: {page} ({len(body) // 1024} КБ). Лотов в ответе: {items}.')
    if 'lang="ru"' not in text[:2000]:
        print('ВНИМАНИЕ: страница пришла не на русском, типы лотов могут не распознаться.')
    if units and units != {'₽'}:
        print(f'ВНИМАНИЕ: цены не в рублях ({", ".join(sorted(units))}). Парсер отбросит такие лоты, сравнивать их с рублёвыми нельзя.')
    if items < 1000:
        print('ВНИМАНИЕ: лотов мало: возможно, пришла только часть страницы. Подгрузку и пролистывание загрузчик не эмулирует.')
    if a.no_parse:
        return 0
    return run_parser(page, day, os.path.join(a.out, day), a.marks)


if __name__ == '__main__':
    sys.exit(main())
