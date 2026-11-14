# -*- coding: utf-8 -*-
"""FunPay Detector 1.0: ЕДИНАЯ программа. Файлы проекта: app.py (весь бэкенд), ui.html (весь интерфейс),
README.md (карта проекта для людей и агентов: читать первым).

Что это: локальная программа на 127.0.0.1 для продавца FunPay (категория «Прочее GTA 5 RP», lots/1112):
детектор рынка (цены скриптов), управление своими лотами, сообщения, напоминания, статистика.

Оглавление app.py (ищите по строке «# ===== N.»):
   1. Пути, константы, утилиты
   2. Правила разбора страницы категории и CLI «parse»      (бывш. parse_category.py)
   3. Гостевой загрузчик категории и CLI «fetch»            (бывш. fetch_category.py)
   4. Клиент аккаунта FunPay по golden_key                  (бывш. funpay_manage.py)
   5. Детектор: отметки, снимки, цены, история, автоснимок  (бывш. detector_app.py)
   6. Вкладка «Аккаунт»: лоты, форма лота, количество, поднятие (бывш. account_tab.py)
   7. Сообщения                                             (бывш. chat_tab.py)
   8. Напоминания о подтверждении                           (бывш. remind_tab.py)
   8б. Подтверждение заказов: состояния, таймер 24 ч, тикет (этап 1)
   8в. Просьба об отзыве: шаблоны на лот, одна просьба на заказ (этап 2)
   9. Статистика                                            (бывш. stats_tab.py)
  9б. Статистика v1: награды, расходы, метрики по ID лота, подсказки, отчёт
  10. HTTP-сервер и таблица маршрутов
  11. Точка входа: serve (по умолчанию) | fetch | parse

Запуск: «Запустить.bat» или `python app.py`. Нужны только Python 3 и beautifulsoup4.
"""
import argparse, base64, collections, csv, datetime, gzip, hashlib, hmac, json, os, random, re, secrets, shutil, socket
import statistics, subprocess, sys, threading, time, traceback, webbrowser
import urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
try:
    from bs4 import BeautifulSoup
except ImportError:
    print('Не установлена библиотека BeautifulSoup. В PowerShell выполните: pip install beautifulsoup4')
    sys.exit(1)


# ===== 1. Пути, константы, утилиты =====================================================================
VERSION = '1.11'
HERE = os.path.dirname(os.path.abspath(__file__))


# Облачный режим (Railway): включается, если задан APP_PASSWORD. Данные лежат на томе (DATA_DIR), ключ берётся из переменной.
CLOUD = bool(os.environ.get('APP_PASSWORD'))
DATA_DIR = os.environ.get('DATA_DIR') or HERE
ENV_KEY = os.environ.get('FUNPAY_GOLDEN_KEY', '').strip()      # СЕКРЕТ: на диск не пишется
if DATA_DIR != HERE:
    os.makedirs(DATA_DIR, exist_ok=True)


def P(*parts):
    return os.path.join(DATA_DIR, *parts)


# Данные лежат рядом с программой (имена файлов не менялись при объединении: старые данные подхватываются).
UI_FILE = os.path.join(HERE, 'ui.html')
PAGES = P('pages')                      # сохранённые страницы категории kategoriya_ГГГГ-ММ-ДД[_ЧЧММСС].htm
PAGES_OWN = P('pages_own')              # диагностика: страницы своего аккаунта без токенов
OUT_DIR = P('out')                      # отчёт CLI «parse» (CSV по дням)
HISTORY = P('history')                  # CSV на снимок + index.csv
INDEX = P('history', 'index.csv')
MARKS = P('marks.csv')                  # ручные отметки лотов (скрипт / ниша / нет)
MARKS_BACKUP = P('marks_before_shell.csv')
STATE = P('fetch_state.json')           # состояние защиты гостевого загрузчика
AUTO_CFG = P('auto_settings.json')
AUTO_LOG = P('auto_log.csv')
KEYFILE = P('golden_key.txt')           # СЕКРЕТ: полный доступ к аккаунту
MANAGE_LOG = P('manage_log.csv')        # журнал запросов аккаунта (путь и статус, без значений)
AMOUNTS_CACHE = P('amounts_cache.json')
ORDERS_CACHE = P('orders_cache.json')   # заказы: номер, статус, цена, название, время (без покупателей)
LOT_COSTS = P('lot_costs.json')         # себестоимость лотов и комиссия: вводит пользователь
REMIND_LOG = P('reminders_log.json')    # кому и когда отправлено напоминание (без текста)

HOST = '0.0.0.0' if CLOUD else '127.0.0.1'
PORTS = ([int(os.environ['PORT'])] if os.environ.get('PORT') else []) + list(range(8765, 8786))         # сначала эти порты; если все заняты: любой свободный
SITE_BASE = os.environ.get('MARKET_TEST_BASE', 'https://funpay.com')   # MARKET_TEST_*: только для проверки на локальном сервере
UA_GUEST = 'MarketDetector/1.0 (personal price research; rare guest requests)'
UA_ACCOUNT = os.environ.get('FUNPAY_USER_AGENT', 'MarketDetector/1.0 (own account, read-only)')
BLOCK_STATUSES = {401, 403, 407, 429, 451, 503} | set(range(520, 530))
CAPTCHA_MARKERS = r'captcha|hcaptcha|cf-chl|just a moment|attention required|ddos-guard|checking your browser|проверка браузера|вы не робот'


class UserError(Exception):
    """Ошибка ввода пользователя (HTTP 400): неверное поле, число и т.п."""


class SiteStop(Exception):
    """Остановка клиента аккаунта: блокировка, капча, редирект, неожиданный ответ. Ничего не повторяется и не обходится."""


def write_csv(path, cols, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, cols, delimiter=';', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def write_csv_atomic(path, cols, rows):
    tmp = path + '.tmp'
    write_csv(tmp, cols, rows)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else default
    except (OSError, ValueError):
        return default


def write_json_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def strip_tags(s):
    return re.sub(r'<[^>]+>', ' ', str(s))


def is_id(v, maxlen):
    return bool(re.fullmatch(r'\d{1,%d}' % maxlen, str(v)))


# ===== 2. Правила разбора страницы категории ===========================================================
# Читает ЛОКАЛЬНУЮ сохранённую страницу, в интернет не ходит. Берёт только публичные данные лотов.
# Продажи и выручку не считает. Менять правила можно только здесь; смена правил меняет rules_hash()
# и пересобирает историю автоматически.
GAME_OK = 'gta 5'            # метка игры на FunPay; 'samp' отбрасываем
TYPE_OK = 'прочее'           # скрипты лежат в «Прочее»
CURRENCY_OK = '₽'
# Чужие проекты: наш проект GTA 5 RP (GTA5RP). Лоты с этими словами в названии отбрасываются.
SAMP_WORDS = (r'samp|crmp|самп|крмп|majestic|маджестик|мажестик|\bnova\b|rmrp|рмрп|'
              r'росси[яи]\s*онлайн|russia\s*online|region\s*-?\s*rp|регион\s*-?\s*рп')
CHEAT_WORDS = r'dlc|rage|leet|1337|просвет|wallhack|скелет|прицел|наведен|стрельба|\besp\b|\baim'
SCRIPT_WORDS = (r'скрипт|script|ahk|афк|afk|макрос|автомат|авто-?(порт|бег|перекуп|скупк|рыбалк|строй)|'
                r'включил и забыл|работает сам|свёрнут|свернут|помощник')
# Срок в названии: число + «дн/day/д/d», недели, месяцы, «навсегда», «на сутки»
NUM_DAYS = r'(?<!\d)(\d{1,3})\s*(?:дн|день|day|д\b|d\b)'
NUM_WEEKS = r'(?<!\d)(\d{1,2})\s*недел'
NUM_MONTHS = r'(?<!\d)(\d{1,2})\s*месяц'
FOREVER = r'навсегда|forever|пожизнен'
BUCKETS = [('до 50', 0, 49), ('50–500', 50, 500), ('больше 500', 501, 10 ** 9)]
STEPS = ['игра не GTA 5', 'тип не «Прочее»', 'в названии чужой проект', 'срок не указан', 'другой срок',
         'несколько сроков', 'не скрипт-автоматизация', 'ручная отметка', 'не подтверждён', 'цена не в рублях', 'нет цены']
MARK_VALUES = ('скрипт', 'ниша', 'нет')
# Автоопределение скрипта. Кроме SCRIPT_WORDS лот считается скриптом, если:
#  1) в названии «авто-»/«auto-» через дефис (АВТО-КАЧАЛКА, AUTO-COOKING), но не «авто-выдача»/«автовыдача»;
#  2) или названо не меньше двух игровых занятий (шахта, стройка, качалка, кулинария, коровы, такси...).
AUTO_ISSUE = r'(?:авто|auto)-?\s?(?:выдач|deliver)\w*'
AUTO_WORDS = r'(?<![a-zа-яё])(?:авто|auto)-\s?[a-zа-яё]'
ACTIVITY_WORDS = [r'шахт', r'стройк', r'качалк', r'кулинар|готовк', r'коров|(?<![а-яё])ферм', r'такси',
                  r'деморган|demorgan', r'рыбалк|рыбак|рыбы', r'(?<![а-яё])порт\b']
# Ниша (автоматически): торговая площадка 5VITO и скупщики/спекулянты. Остальные ниши отмечаются вручную.
NICHE_WORDS = r'5vito|bvito|скупщик|спекулянт'


def has(p, t):
    return re.search(p, t, re.I) is not None


def is_script_text(t):
    t = re.sub(AUTO_ISSUE, ' ', t, flags=re.I)         # «автовыдача» не признак скрипта
    if has(SCRIPT_WORDS, t) or has(AUTO_WORDS, t):
        return True
    return sum(1 for w in ACTIVITY_WORDS if has(w, t)) >= 2


def is_niche(t):
    return has(NICHE_WORDS, t)


def find_terms(t):
    """Набор сроков из названия: числа дней и/или слово «навсегда»."""
    terms = set()
    for m in re.finditer(NUM_DAYS, t, re.I):
        terms.add(int(m.group(1)))
    for m in re.finditer(NUM_WEEKS, t, re.I):
        terms.add(int(m.group(1)) * 7)
    if has(r'(?<!\d)(?<!\d\s)недел', t) and not re.search(NUM_WEEKS, t, re.I):
        terms.add(7)
    for m in re.finditer(NUM_MONTHS, t, re.I):
        terms.add(int(m.group(1)) * 30)
    if has(r'(?<!\d)(?<!\d\s)месяц', t) and not re.search(NUM_MONTHS, t, re.I):
        terms.add(30)
    if has(r'\b(на|1|одни)\s+сутки|24\s*час', t):
        terms.add(1)
    if has(FOREVER, t):
        terms.add('навсегда')
    return terms


def term_label(x):
    if isinstance(x, str):
        return x
    word = 'день' if x % 10 == 1 and x % 100 != 11 else 'дня' if x % 10 in (2, 3, 4) and x % 100 not in (12, 13, 14) else 'дней'
    return f'{x} {word}'


def read_lots(path):
    """Лоты со страницы категории (только блоки a.tc-item)."""
    with open(path, encoding='utf-8', errors='replace') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    lots = []
    for a in soup.select('a.tc-item'):
        title = a.select_one('.tc-desc-text')
        seller = a.select_one('.media-user-name')
        price = a.select_one('.tc-price')
        unit = a.select_one('.tc-price .unit')
        rc = a.select_one('.rating-mini-count')
        info = a.select_one('.media-user-info')
        digits = re.sub(r'\D', '', rc.get_text()) if rc else ''
        lots.append({
            'id': a['href'].split('id=')[-1],
            'название': title.get_text(' ', strip=True) if title else '',
            'игра': a.get('data-f-game') or '',
            'тип': a.get('data-f-type') or '(нет типа)',
            'продавец': seller.get_text(strip=True) if seller else '',
            'цена_руб': round(float(price['data-s']), 2) if price is not None and price.get('data-s') else None,
            'валюта': unit.get_text(strip=True) if unit else '',
            'автовыдача': 'да' if a.get('data-auto') else 'нет',
            'онлайн': 'да' if a.get('data-online') else 'нет',
            'отзывов_продавца': int(digits) if digits else 0,
            'отзывов_нет_счётчика': '' if digits else 'да',
            'на_сайте': info.get_text(strip=True) if info else '',
            'промо': 'да' if 'offer-promo' in a.get('class', []) else 'нет',
        })
    return lots


def classify(l):
    """Возвращает (срок, причина_отброса или None). Порядок проверок = порядок воронки STEPS."""
    t = l['название']
    if l['игра'] != GAME_OK:
        return '', 'игра не GTA 5 (SAMP)'
    if l['тип'] != TYPE_OK:
        return '', 'тип не «Прочее»: ' + l['тип']
    if has(SAMP_WORDS, t):
        return '', 'в названии чужой проект (SAMP, Majestic, NOVA, RMRP, Россия онлайн, Region RP)'
    terms = find_terms(t)
    if not terms:
        return '', 'срок не указан в названии'
    if 7 not in terms:
        return '', 'другой срок: ' + ', '.join(sorted((term_label(x) for x in terms), key=lambda s: (len(s), s)))
    if len(terms) > 1:
        return '', 'несколько сроков в названии'
    if has(CHEAT_WORDS, t):
        return '7 дней', 'не скрипт-автоматизация (DLC/ESP/наведение)'
    if not is_script_text(t):
        return '7 дней', 'не подтверждён как скрипт (нет слов-признаков)'
    return '7 дней', None


def dup_key(l):
    t = re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', l['название'])
    return (re.sub(r'\s+', ' ', t).casefold(), l['цена_руб'])


def add_dup_flags(lots):
    """Флаг «дубль»: такая же пара «название + цена» есть у другого продавца."""
    groups = collections.defaultdict(list)
    for l in lots:
        groups[dup_key(l)].append(l)
    n = 0
    for key, g in groups.items():
        sellers = {x['продавец'] for x in g}
        gid = ''
        if len(sellers) > 1:
            n += 1
            gid = f'D{n:02d}'
        for x in g:
            x['дубль'] = 'да' if len(sellers) > 1 else 'нет'
            x['группа_дубля'] = gid
            x['лотов_в_группе'] = len(g)
            x['продавцов_в_группе'] = len(sellers)


def bucket_of(n):
    for name, lo, hi in BUCKETS:
        if lo <= n <= hi:
            return name


def stat_row(variant, label, kind, vals, sellers):
    r = {'вариант': variant, 'срез': label, 'показатель': kind, 'продавцов': sellers, 'лотов_или_цен': len(vals),
         'мин': '', 'Q1': '', 'медиана': '', 'Q3': '', 'макс': '', 'примечание': ''}
    if not vals:
        r['примечание'] = 'нет лотов'
        return r
    r['мин'], r['медиана'], r['макс'] = min(vals), round(statistics.median(vals), 2), max(vals)
    if len(vals) >= 5:
        q = statistics.quantiles(vals, n=4, method='inclusive')
        r['Q1'], r['Q3'] = round(q[0], 2), round(q[2], 2)
    else:
        r['примечание'] = 'мало данных (меньше 5), Q1 и Q3 не считаю'
    return r


def build_summary(variant, kept):
    rows = []
    for label in ['все продавцы'] + [b[0] for b in BUCKETS]:
        part = [l for l in kept if label == 'все продавцы' or bucket_of(l['отзывов_продавца']) == label]
        sellers = {l['продавец'] for l in part}
        rows.append(stat_row(variant, label, 'все лоты', [l['цена_руб'] for l in part], len(sellers)))
        seen, nodup = set(), []
        for l in part:                          # один лот на пару «название + цена» внутри среза
            k = dup_key(l)
            if k not in seen:
                seen.add(k)
                nodup.append(l['цена_руб'])
        rows.append(stat_row(variant, label, 'без дублей', nodup, len(sellers)))
        cheap = {}
        for l in part:
            cheap[l['продавец']] = min(cheap.get(l['продавец'], 1e18), l['цена_руб'])
        rows.append(stat_row(variant, label, 'самый дешёвый лот у каждого продавца', list(cheap.values()), len(sellers)))
    return rows


def marks_raw(path=MARKS):
    """marks.csv как есть: id -> {'отметка', 'название'}. Ничего не отбрасывает."""
    rows = {}
    if path and os.path.exists(path):
        with open(path, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f, delimiter=';'):
                if r.get('id'):
                    rows[r['id']] = {'отметка': r.get('отметка') or '', 'название': r.get('название') or ''}
    return rows


def read_marks(path=MARKS):
    """Только валидные отметки: id -> 'скрипт' | 'ниша' | 'нет'."""
    return {i: r['отметка'] for i, r in marks_raw(path).items() if r['отметка'] in MARK_VALUES}


def cmd_parse(argv):
    """CLI: python app.py parse страница.htm --date ГГГГ-ММ-ДД --out папка. Пишет CSV-отчёт и воронку в консоль.
    Файлы: lots_kept.csv, lots_unconfirmed.csv, lots_dropped.csv, price_summary.csv (варианты A: все, B: без «ниша»).
    Ручные отметки неподтверждённых лотов берутся из marks.csv (ставятся в окне программы, вкладка «Отметки»)."""
    ap = argparse.ArgumentParser(prog='app.py parse')
    ap.add_argument('page')
    ap.add_argument('--date', default='не указана', help='дата сохранения страницы, ГГГГ-ММ-ДД')
    ap.add_argument('--out', default=OUT_DIR)
    ap.add_argument('--marks', default=MARKS, help='файл ручных отметок по ID лота')
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    if a.date == 'не указана':
        print('ВНИМАНИЕ: дата сохранения страницы не указана, в файлах будет «не указана».')

    raw = read_lots(a.page)
    units = collections.Counter(l['валюта'] or '(нет значка)' for l in raw)
    print('Валюта цен на странице: ' + ', '.join(f'{u} {n}' for u, n in units.most_common()))
    if set(units) != {CURRENCY_OK}:
        print('ВНИМАНИЕ: не все цены в рублях. Лоты в другой валюте отбрасываются: доллары и рубли сравнивать нельзя.')
    seen, lots, dups = set(), [], 0
    for l in raw:
        if l['id'] in seen:
            dups += 1
            continue
        seen.add(l['id'])
        lots.append(l)

    marks = read_marks(a.marks)
    kept, dropped = [], []
    for l in lots:
        term, reason = classify(l)
        if reason is None and marks.get(l['id']) == 'нет':
            reason = 'ручная отметка: не скрипт (правило подтвердило, но вы отметили «нет»)'
        if reason is None and l['валюта'] != CURRENCY_OK:
            reason = f'цена не в рублях ({l["валюта"] or "нет значка"})'
        if reason is None and l['цена_руб'] is None:
            reason = 'нет цены'
        l['срок'] = term
        l['дата_страницы'] = a.date
        l['источник'] = 'правило'
        m0 = marks.get(l['id'])        # ручная отметка сильнее правила: «ниша» ставит нишу, «скрипт» снимает автониша
        l['ниша'] = 'да' if reason is None and (m0 == 'ниша' or (m0 != 'скрипт' and is_niche(l['название']))) else ''
        if reason:
            l['причина_отброса'] = reason
            dropped.append(l)
        else:
            kept.append(l)
    by_auto = collections.Counter(x['причина_отброса'] for x in dropped)   # воронка до ручных отметок
    unconfirmed = [l for l in dropped if l['причина_отброса'].startswith('не подтверждён')]
    unconfirmed.sort(key=lambda x: x['цена_руб'] if x['цена_руб'] is not None else 1e18)
    for n, l in enumerate(unconfirmed, 1):
        l['№'] = n
    add_dup_flags(unconfirmed)

    promoted, rejected = [], []
    for l in unconfirmed:
        m = marks.get(l['id'], '')
        l['отметка'] = m
        if m in ('скрипт', 'ниша'):
            promoted.append(l)
        elif m == 'нет':
            rejected.append(l)
    for l in promoted:
        if l['валюта'] != CURRENCY_OK or l['цена_руб'] is None:
            continue
        l['срок'], l['источник'], l['ниша'] = '7 дней', 'ручная отметка', 'да' if l['отметка'] == 'ниша' else ''
        kept.append(l)
    kept_ids = {l['id'] for l in kept}
    dropped = [l for l in dropped if l['id'] not in kept_ids]
    for l in rejected:
        l['причина_отброса'] = 'ручная отметка: не скрипт'

    add_dup_flags(kept)
    kept.sort(key=lambda x: x['цена_руб'])
    cols = ['дата_страницы', 'id', 'название', 'продавец', 'срок', 'цена_руб', 'автовыдача', 'онлайн',
            'отзывов_продавца', 'отзывов_нет_счётчика', 'на_сайте', 'промо', 'источник', 'ниша',
            'дубль', 'группа_дубля', 'лотов_в_группе', 'продавцов_в_группе']
    write_csv(f'{a.out}/lots_kept.csv', cols, kept)
    write_csv(f'{a.out}/lots_unconfirmed.csv', ['№', 'отметка', 'id', 'название', 'продавец', 'цена_руб', 'срок',
                                                 'отзывов_продавца', 'автовыдача', 'дубль', 'группа_дубля',
                                                 'дата_страницы'], unconfirmed)
    write_csv(f'{a.out}/lots_dropped.csv', ['причина_отброса', 'id', 'название', 'игра', 'тип', 'срок',
                                            'цена_руб', 'продавец'],
              sorted(dropped, key=lambda x: x['причина_отброса']))
    kept_b = [l for l in kept if not l['ниша']]
    summary = build_summary('A: все лоты', kept)
    if len(kept_b) != len(kept):
        summary += build_summary('B: без лотов «ниша»', kept_b)
    write_csv(f'{a.out}/price_summary.csv', ['вариант', 'срез', 'показатель', 'продавцов', 'лотов_или_цен', 'мин',
                                             'Q1', 'медиана', 'Q3', 'макс', 'примечание'], summary)

    # ---- Отчёт в консоль ----
    print(f'Записей на странице: {len(raw)}; дубликатов по ID: {dups}; уникальных лотов: {len(lots)}')
    left = len(lots)
    print('Воронка автоматических правил (по шагам):')
    for step in STEPS:
        n = sum(v for k, v in by_auto.items() if k.startswith(step))
        if n:
            left -= n
            print(f'  отброшено {n:5d}  осталось {left:5d}  {step}')
    marked_script = [l for l in unconfirmed if l['отметка'] in ('скрипт', 'ниша')]
    unmarked = [l for l in unconfirmed if not l['отметка']]
    in_kept = sum(1 for l in marked_script if l['id'] in kept_ids)
    print(f'Ручные отметки (неподтверждённых {len(unconfirmed)}): скрипт {len(marked_script)} '
          f'(из них «ниша» {sum(1 for l in marked_script if l["отметка"] == "ниша")}), '
          f'нет {len(rejected)}, без отметки {len(unmarked)}')
    if len(marked_script) != in_kept:
        print(f'  Из отмеченных «скрипт» в итог не попало {len(marked_script) - in_kept}: цена не в рублях.')
    unconf_ids = {l['id'] for l in unconfirmed}
    stale = sum(1 for i in marks if i not in unconf_ids)
    if stale:
        print(f'Отметок в marks.csv без лота в этом списке: {stale} (лот снят, изменился или решён правилом).')
    if unmarked:
        print('БЕЗ ОТМЕТКИ (отметьте в окне программы, вкладка «Отметки»):')
        for l in unmarked:
            print(f"  №{l['№']:>2}  {l['цена_руб']:>8} {l['валюта'] or '?'}  {l['продавец'][:14]:<14} {l['название'][:55]}")
    print(f'ОСТАЛОСЬ: {len(kept)}  (проверка: {len(kept)} + {len(dropped)} = {len(kept) + len(dropped)} из {len(lots)})')
    if not kept and set(units) != {CURRENCY_OK}:
        print('Итог пустой из-за валюты: нужна страница с ценами в рублях.')
    d_lots = sum(1 for l in kept if l['дубль'] == 'да')
    d_groups = len({l['группа_дубля'] for l in kept if l['дубль'] == 'да'})
    print(f'Дубли «название + цена» у разных продавцов: {d_lots} лотов в {d_groups} группах')
    variants = [('A: все лоты', kept)] + ([('B: без лотов «ниша»', kept_b)] if len(kept_b) != len(kept) else [])
    for name, part in variants:
        print(f'Срезы цен, ₽, вариант {name} ({len(part)} лотов), дата страницы {a.date}:')
        for r in [x for x in summary if x['вариант'] == name]:
            print(f"  {r['срез']:<14} {r['показатель']:<38} продавцов {r['продавцов']:>2}  n={r['лотов_или_цен']:>2}  "
                  f"мин {r['мин']}  Q1 {r['Q1']}  мед {r['медиана']}  Q3 {r['Q3']}  макс {r['макс']}  {r['примечание']}")
    return 0



# ===== 3. Гостевой загрузчик категории =================================================================
# Один раз скачивает публичную страницу категории КАК ГОСТЬ и сохраняет в pages/kategoriya_ГГГГ-ММ-ДД.htm
# (повторные за день: ..._ЧЧММСС.htm). Потом запускает разбор (cmd_parse).
# Решения пользователя (проект «Бизнесс», 04.11.2026): проверка robots.txt отключена; лимит проходов и интервал
# между ними убраны: запускать можно сколько угодно раз, каждый запуск = один запрос страницы категории.
# ЕДИНСТВЕННОЕ ограничение: если проход сегодня остановлен (блокировка, капча, редирект, HTTP-ошибка), повтор в этот
# день отказывает (fetch_state.json). Загрузчик не входит в аккаунт, не шлёт cookie, кроме валюты показа cy=rub,
# не решает капчу, не меняет адрес и заголовки ради обхода защиты, не ходит параллельно.
PAUSE = float(os.environ['MARKET_TEST_PAUSE']) if 'MARKET_TEST_PAUSE' in os.environ else None
TIMEOUT = float(os.environ.get('MARKET_TEST_TIMEOUT', '30'))
MAX_BYTES = 40 * 1024 * 1024
# Единственная разрешённая cookie: выбор валюты показа (имя cy найдено в браузере в гостевом режиме).
CURRENCY_COOKIES = {'rub': 'cy=rub', 'usd': 'cy=usd', 'eur': 'cy=eur', 'none': None}


class FetchStop(Exception):
    def __init__(self, code, title, detail='', body=b''):
        super().__init__(title)
        self.code, self.title, self.detail, self.body = code, title, detail, body


def pause(lo, hi):
    time.sleep(PAUSE if PAUSE is not None else random.uniform(lo, hi))


def today():
    return datetime.date.today().isoformat()      # дата на вашем ПК


def http_get(url, cookie=None):
    """Один GET без входа и без авторизации. Из cookie можно послать только валюту показа (CURRENCY_COOKIES).
    Возвращает (статус, итоговый адрес, тело)."""
    headers = {'User-Agent': UA_GUEST, 'Accept': 'text/html,text/plain;q=0.9,*/*;q=0.5',
               'Accept-Language': 'ru-RU,ru;q=0.9', 'Accept-Encoding': 'gzip'}
    if cookie:
        headers['Cookie'] = cookie
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener()          # без обработчика cookies: ничего не запоминается между запросами
    try:
        resp = opener.open(req, timeout=TIMEOUT)
        status, final, hdr = resp.status, resp.geturl(), resp.headers
    except urllib.error.HTTPError as e:
        resp, status, final, hdr = e, e.code, e.geturl(), e.headers
    body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise FetchStop(4, 'Ответ слишком большой', f'больше {MAX_BYTES // 1024 // 1024} МБ, не сохраняю')
    if hdr.get('Content-Encoding', '').lower() == 'gzip':
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return status, final, body


def get_once_retry_on_network(url, cookie=None):
    """Сетевая ошибка (таймаут, обрыв): один повтор через паузу. Ответы сайта (403, 429 и т.д.) не повторяются."""
    net = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError)
    try:
        return http_get(url, cookie)
    except net as e1:
        print(f'Сетевая ошибка ({type(e1).__name__}), один повтор через минуту...')
        pause(60, 60)
        try:
            return http_get(url, cookie)
        except net as e2:
            raise FetchStop(5, 'Нет связи с сайтом', f'{type(e2).__name__}: {e2}') from e2


def check_page(status, final, body, path):
    if status in BLOCK_STATUSES:
        raise FetchStop(2, f'Сайт отвечает HTTP {status}', 'Похоже на блокировку, лимит запросов или защиту.', body)
    if status != 200:
        raise FetchStop(4, f'Неожиданный ответ HTTP {status}', 'Страница не отдана, формат неизвестен.', body)
    if urlparse(final).path.rstrip('/') != path.rstrip('/'):
        raise FetchStop(2, 'Сайт перенаправил на другой адрес', f'Вместо {path} пришёл {final} (вход, капча или защита).', body)
    text = body.decode('utf-8', 'replace')
    items = len(re.findall(r'class="tc-item', text))
    if items == 0:
        if re.search(CAPTCHA_MARKERS, text[:300000], re.I):
            raise FetchStop(2, 'Сайт показывает капчу или проверку браузера', 'Загрузчик её не обходит.', body)
        raise FetchStop(4, 'В ответе нет лотов', 'Страница пришла, но разметка лотов не найдена.', body)
    return text, items


def prev_lots_count():
    """Наибольшее число лотов в трёх последних снимках из history/index.csv (0, если истории нет)."""
    try:
        with open(INDEX, encoding='utf-8-sig', newline='') as f:
            rows = [r for r in csv.DictReader(f, delimiter=';') if str(r.get('лотов_на_странице', '')).isdigit()]
    except OSError:
        return 0
    rows.sort(key=lambda r: (r.get('дата', ''), r.get('время', '')))
    return max([int(r['лотов_на_странице']) for r in rows[-3:]] or [0])


def cmd_fetch(argv):
    """CLI: python app.py fetch. Коды выхода: 0 ок, 2 блокировка/капча/редирект, 3 сегодня уже остановлено,
    4 неожиданный ответ, 5 нет связи. Окно программы запускает именно эту подкоманду отдельным процессом."""
    ap = argparse.ArgumentParser(prog='app.py fetch', description='Загрузка страницы категории FunPay (гость).')
    ap.add_argument('--path', default='/lots/1112/', help='путь категории, по умолчанию «Прочее GTA 5 RP, SAMP»')
    ap.add_argument('--pages', default=PAGES)
    ap.add_argument('--out', default=OUT_DIR)
    ap.add_argument('--state', default=STATE)
    ap.add_argument('--marks', default=MARKS)
    ap.add_argument('--currency', choices=sorted(CURRENCY_COOKIES), default='rub',
                    help='валюта показа: rub (по умолчанию), usd, eur или none (не посылать ничего)')
    ap.add_argument('--no-parse', action='store_true')
    a = ap.parse_args(argv)
    if not re.fullmatch(r'/lots/\d+/', a.path):
        sys.exit('Разрешены только страницы категорий вида /lots/ЧИСЛО/.')

    day = today()
    stamp = datetime.datetime.now().strftime('%H%M%S')
    again = False
    state = read_json(a.state, {})
    if state.get('дата') == day:
        last = str(state.get('результат', '?'))
        if last.startswith('остановлен'):
            print(f'Сегодня проход остановлен ({last}). После блокировки, капчи или редиректа повтор в этот день запрещён. Попробуйте завтра.')
            return 3
        again = True
        print(f'Повторный проход за {day} (прошлый результат: {last}).')

    def save_state(result):
        with open(a.state, 'w', encoding='utf-8') as f:
            json.dump({'дата': day, 'результат': result, 'время': datetime.datetime.now().isoformat(timespec='seconds')}, f, ensure_ascii=False)

    save_state('начат, не завершён')               # попытка считается сразу, даже если окно закрыли
    os.makedirs(a.pages, exist_ok=True)
    try:
        print(f'Дата {day}. Гостевой режим, без входа в аккаунт. robots.txt не проверяется (отключено по решению пользователя).')
        cookie = CURRENCY_COOKIES[a.currency]
        print('Загружаю страницу категории (один запрос'
              + (f', валюта показа {cookie}: это настройка отображения, не вход в аккаунт' if cookie else ', без cookie')
              + ')...')
        status, final, body = get_once_retry_on_network(SITE_BASE + a.path, cookie)
        text, items = check_page(status, final, body, a.path)
    except FetchStop as s:
        retry = s.code in (4, 5)                   # не блокировка, а сбой (нет связи, 5xx, пустой ответ): день не блокируем
        save_state(('ошибка, будет повтор: ' if retry else 'остановлен: ') + s.title)
        if s.body:
            stop_file = os.path.join(a.pages, f'_stop_{day}.html')
            with open(stop_file, 'wb') as f:
                f.write(s.body[:500000])
            print(f'Ответ сайта сохранён для просмотра: {stop_file}')
        print(f'\nСТОП: {s.title}. {s.detail}'.rstrip())
        if retry:
            print('Это сбой, а не блокировка: программа сама повторит загрузку позже, ничего делать не нужно.')
        else:
            print('Загрузчик ничего не обходит и сегодня больше не повторит запрос.')
            print('Что делать: сообщите «Бизнесс» через пользователя; решение принимает пользователь.')
            print('Пока можно сохранять страницу вручную в браузере (гостем).')
        return s.code

    base = f'kategoriya_{day}_{stamp}' if again else f'kategoriya_{day}'
    name = base + '.htm'
    if os.path.exists(os.path.join(a.pages, name)):
        name = base + '_auto.htm'                  # не затираем вашу ручную страницу
    page = os.path.join(a.pages, name)
    with open(page, 'wb') as f:
        f.write(body)
    save_state('ok')
    units = set(re.findall(r'<span class="unit">([^<]*)</span>', text))
    print(f'Сохранено: {page} ({len(body) // 1024} КБ). Лотов в ответе: {items}.')
    if 'lang="ru"' not in text[:2000]:
        print('ВНИМАНИЕ: страница пришла не на русском, типы лотов могут не распознаться.')
    if units and units != {'₽'}:
        print(f'ВНИМАНИЕ: цены не в рублях ({", ".join(sorted(units))}). Разбор отбросит такие лоты, сравнивать их с рублёвыми нельзя.')
    if items < 1000:
        print('ВНИМАНИЕ: лотов мало: возможно, пришла только часть страницы. Подгрузку и пролистывание загрузчик не эмулирует.')
    prev = prev_lots_count()
    if prev >= 200 and items < 0.7 * prev:
        print(f'Страница неполная: лотов {items}, в прошлых снимках было до {prev}. Программа сама повторит загрузку.')
        return 6
    if a.no_parse:
        return 0
    print('--- Запускаю разбор страницы ---')
    try:
        return cmd_parse([page, '--date', day, '--out', os.path.join(a.out, f'{day}_{stamp}' if again else day), '--marks', a.marks])
    except Exception:
        traceback.print_exc()
        return 1


# ===== 4. Клиент аккаунта FunPay (golden_key) ==========================================================
# Всё, что идёт «от имени аккаунта»: профиль, формы лотов, поднятие, чаты, заказы. Один общий клиент:
# site_request(). Правила (сделаны намеренно):
#   - при капче, 403, 429, редиректе на вход бросается SiteStop; верхний слой (guarded) блокирует сессию до
#     перезапуска, ничего не повторяет и не обходит;
#   - между запросами минимальная пауза PACE; параллельных запросов нет (guarded держит замок);
#   - в логе manage_log.csv пишутся путь и статус (и ИМЕНА cookie, выданных сайтом), значения не пишутся;
#   - в сохранённых HTML вырезаны csrf-токен и data-app-data (redact()).
# Адреса /users/ID/, /lots/offerEdit, /orders/trade, /chat/, /runner/, /lots/raise написаны по памяти и могут
# отличаться от живого сайта: если разметка не найдена, функции говорят об этом, а не угадывают.
PACE = (0.8, 1.5)                  # минимальный промежуток между запросами, секунд
CAPTCHA = r'captcha|cf-chl|just a moment|attention required|ddos-guard|проверка браузера|вы не робот'
_SITE = {'last_ts': 0.0, 'jar': {}}
ALIASES = {'price': r'^price$', 'amount': r'^amount$', 'auto': r'auto_?deliver', 'title': r'summary',
           'desc': r'desc', 'active': r'^active$', 'secrets': r'^secrets$'}
SECRET_FIELD = r'secret|csrf|token'


def manage_log(path, status):
    new = not os.path.exists(MANAGE_LOG)
    with open(MANAGE_LOG, 'a', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh, delimiter=';')
        if new:
            w.writerow(['время', 'путь', 'статус'])
        w.writerow([datetime.datetime.now().isoformat(timespec='seconds'), path, status])


def redact(html):
    html = re.sub(r'data-app-data="[^"]*"', 'data-app-data="[вырезано]"', html)
    html = re.sub(r"data-app-data='[^']*'", "data-app-data='[вырезано]'", html)
    html = re.sub(r'(csrf[-_]token["\']?\s*[:=]\s*["\'])[^"\']+', r'\1[вырезано]', html, flags=re.I)
    return html


def app_data(html):
    soup = BeautifulSoup(html, 'html.parser')
    raw = soup.body.get('data-app-data') if soup.body else None
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def site_request(path, key, data=None, referer=None):
    """GET, а при data POST (dict или список пар). Шлёт golden_key, cookie_prefs=1 и cookie, которые сайт сам
    выдал в ответах (кроме golden_key и fav_games). Возвращает (статус, итоговый адрес, текст)."""
    gap = random.uniform(*PACE) - (time.time() - _SITE['last_ts'])
    if gap > 0:
        time.sleep(gap)
    _SITE['last_ts'] = time.time()
    jar = {'cookie_prefs': '1'}
    jar.update(_SITE['jar'])
    cookie = '; '.join([f'golden_key={key}'] + [f'{k}={v}' for k, v in jar.items()])
    headers = {'User-Agent': UA_ACCOUNT, 'Accept': 'text/html,application/json;q=0.9',
               'Accept-Language': 'ru-RU,ru;q=0.9', 'Accept-Encoding': 'gzip', 'Cookie': cookie}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode('utf-8')
        headers.update({'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest', 'Origin': SITE_BASE, 'Referer': SITE_BASE + (referer or '/')})
    req = urllib.request.Request(SITE_BASE + path, data=body, headers=headers)
    opener = urllib.request.build_opener()
    try:
        try:
            r = opener.open(req, timeout=30)
            status, final, hdr = r.status, r.geturl(), r.headers
        except urllib.error.HTTPError as e:
            r, status, final, hdr = e, e.code, e.geturl(), e.headers
        raw = r.read(20 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SiteStop(f'Нет связи с сайтом: {type(e).__name__}. Повторите позже сами, запрос не повторяется.')
    if hdr.get('Content-Encoding', '').lower() == 'gzip':
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    names = []
    for c in hdr.get_all('Set-Cookie') or []:
        m = re.match(r'\s*([A-Za-z0-9_.\-]+)=([^;]*)', c)
        if m and m.group(1) not in ('golden_key', 'fav_games') and m.group(2):
            _SITE['jar'][m.group(1)] = m.group(2)
            names.append(m.group(1))
    manage_log(('POST ' if data is not None else '') + path + (' [Set-Cookie: ' + ','.join(names) + ']' if names else ''), status)
    text = raw.decode('utf-8', 'replace')
    if status in BLOCK_STATUSES:
        raise SiteStop(f'Сайт ответил HTTP {status}: похоже на блокировку или защиту. Ничего не повторяю.')
    if status != 200:
        shown = '; '.join(f'{k}: {str(v)[:80]}' for k, v in hdr.items()
                          if k.lower() not in ('set-cookie', 'cookie', 'authorization'))
        raise SiteStop(f'Неожиданный ответ HTTP {status} на {"POST " if data is not None else ""}{path}. '
                       f'Тело ответа: {redact(text)[:300] or "(пустое)"}. Заголовки: {shown[:700]}')
    if re.search(CAPTCHA, text[:300000], re.I) and 'data-app-data' not in text[:5000]:
        raise SiteStop('Сайт показывает капчу или проверку. Программа её не обходит.')
    if data is None and urlparse(final).path.rstrip('/') != urlparse(path).path.rstrip('/'):
        raise SiteStop(f'Сайт перенаправил на {final}: вероятно, ключ недействителен или нужен вход.')
    return status, final, text


# ---- формы лотов: чтение полей как их увидел бы браузер, правка, отправка ----
def find_form(soup):
    return soup.find('form', class_=re.compile('offer|edit', re.I)) or soup.find('form')


def form_fields(form):
    """Поля формы: (значения, неотмеченные галочки, имена галочек)."""
    f, boxes, cbs = {}, {}, set()
    for el in form.find_all(['input', 'textarea', 'select']):
        n = el.get('name')
        if not n:
            continue
        t = (el.get('type') or el.name).lower()
        if t in ('submit', 'button', 'image', 'file', 'reset'):
            continue
        if el.name == 'textarea':
            f[n] = el.get_text()[1:] if el.get_text().startswith('\n') else el.get_text()
        elif el.name == 'select':
            o = el.find('option', selected=True) or el.find('option')
            f[n] = o.get('value', '') if o else ''
        elif t in ('checkbox', 'radio'):
            cbs.add(n)
            if el.has_attr('checked'):
                f[n] = el.get('value', 'on')
            else:
                boxes[n] = el.get('value', 'on')
        else:
            f[n] = el.get('value', '')
    return f, boxes, cbs


def resolve_field(name, names):
    if name in names:
        return name
    pat = ALIASES.get(name)
    if pat:
        c = [n for n in names if re.search(pat, n, re.I)]
        ru = [n for n in c if '[ru]' in n]
        if len(c) == 1:
            return c[0]
        if len(ru) == 1:
            return ru[0]
    raise UserError(f'СТОП: поля «{name}» нет в форме лота (или оно неоднозначно). Поля формы: ' + ', '.join(sorted(names)))


def apply_sets(fields, boxes, cbs, sets):
    """Возвращает (новые значения, список изменений [(поле, было, стало)]). Ничего не отправляет."""
    new, changes = dict(fields), []
    names = set(fields) | set(boxes)
    for item in sets:
        if '=' not in item:
            raise UserError(f'СТОП: «{item}» не похоже на поле=значение.')
        name, val = item.split('=', 1)
        real = resolve_field(name.strip(), names)
        if real in cbs:
            on = val.strip().lower() in ('1', 'on', 'да', 'true', 'yes')
            old = 'отмечено' if real in fields else 'не отмечено'
            if on:
                new[real] = fields.get(real) or boxes.get(real, 'on')
            else:
                new.pop(real, None)
            changes.append((real, old, 'отмечено' if on else 'не отмечено'))
        else:
            if real in ('price', 'amount'):
                try:
                    float(val.replace(',', '.'))
                except ValueError:
                    raise UserError(f'СТОП: для {real} нужно число, а не «{val}».')
                val = val.replace(',', '.')
            changes.append((real, fields.get(real, ''), val))
            new[real] = val
    return new, [c for c in changes if c[1] != c[2]]


def mask(name, v):
    return '[скрыто]' if re.search(SECRET_FIELD, name, re.I) else (v if len(v) <= 70 else v[:67] + '...')


def submit_form(key, form, html, new, page, changes):
    """Отправляет форму лота. Вызывать только после подтверждения пользователя. Возвращает (статус, ответ)."""
    action = form.get('action') or '/lots/offerSave'
    if not action.startswith('/'):
        action = urlparse(action).path or '/lots/offerSave'
    new = dict(new)
    if not any(re.search(r'csrf', n, re.I) for n in new):
        tok = app_data(html).get('csrf-token')
        if not tok:
            raise SiteStop('Не нашёл csrf-токен, отправка невозможна. Ничего не отправлено.')
        new['csrf_token'] = tok
    status, _final, resp = site_request(action, key, data=new, referer=page)
    manage_log('изменены поля: ' + ','.join(c[0] for c in changes), status)
    return status, redact(resp)[:400]



# ===== 5. Детектор: отметки, снимки, цены, история, автоснимок ========================================
# Читает только сохранённые страницы из pages/. Разбор берёт из раздела 2 (своей логики разбора нет).
# Вкладки UI: «Отметки», «Цены», «Данные», «История». Подписи «факт» / «оценка»; продаж и выручки здесь нет.
MARKS_LOCK = threading.Lock()
INDEX_LOCK = threading.Lock()
FETCH_LOCK = threading.Lock()
AUTO_LOCK = threading.Lock()
_LOTS_CACHE = {}                         # (путь, время изменения) -> (лоты, всего лотов)
_LOT_NAMES = {}                          # id -> название, для записи в marks.csv
_HIST_CACHE = {}
AUTO_DEFAULT = {'включено': True, 'пауза_часов': 6}
AUTO_FIRST_DELAY = float(os.environ.get('MARKET_TEST_AUTO_DELAY', '20'))
AUTO_EVERY = float(os.environ.get('MARKET_TEST_AUTO_EVERY', '600'))
INDEX_COLS = ['снимок', 'файл', 'дата', 'время', 'размер', 'лотов_на_странице', 'кандидатов', 'валюты', 'правила', 'ошибка']
LOT_COLS = ['дата', 'время', 'снимок', 'id', 'продавец', 'цена_руб', 'валюта', 'отзывов_продавца', 'на_сайте',
            'срок', 'автовыдача', 'решение', 'название']
SELLER_COLS = ['дата', 'время', 'снимок', 'продавец', 'отзывов_продавца', 'на_сайте', 'лотов_на_странице']
FETCH = {'running': False, 'lines': [], 'code': None, 'started': '', 'source': ''}
EXIT_TEXT = {
    0: 'Готово: страница сохранена, снимок добавлен в историю.',
    2: 'Остановлено: сайт показал блокировку, капчу или перенаправил на другой адрес. Загрузчик ничего не обходит; повтор сегодня запрещён.',
    3: 'Загрузка не выполнена: сегодня проход уже остановлен.',
    4: 'Остановлено: неожиданный ответ сайта (страница не отдана или в ней нет лотов).',
    5: 'Остановлено: нет связи с сайтом.',
    6: 'Страница пришла неполной (лотов заметно меньше, чем в прошлых снимках), повторы не помогли.',
}
FETCH_RETRY_CODES = (4, 5, 6)           # сбой, а не блокировка: загрузчик повторяется сам
FETCH_RETRY_WAIT = (60, 180, 420)       # секунд перед 2-й, 3-й и 4-й попыткой


# ---- отметки ----
def set_mark(lot_id, mark):
    """Ставит или снимает отметку по ID лота. Каждый раз читает файл заново, пишет через временный файл."""
    with MARKS_LOCK:
        rows = marks_raw()
        if os.path.exists(MARKS) and not os.path.exists(MARKS_BACKUP):
            shutil.copyfile(MARKS, MARKS_BACKUP)         # одна копия «до оболочки», не перезаписывается
        if mark == '':
            rows.pop(lot_id, None)
        else:
            old = rows.get(lot_id, {}).get('название', '')
            rows[lot_id] = {'отметка': mark, 'название': (_LOT_NAMES.get(lot_id) or old)[:80]}
        out = [{'id': i, 'отметка': r['отметка'], 'название': r['название']} for i, r in sorted(rows.items())]
        tmp = MARKS + '.tmp'
        try:
            write_csv(tmp, ['id', 'отметка', 'название'], out)
            os.replace(tmp, MARKS)
        except OSError:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise


# ---- страницы и лоты ----
def list_snapshots():
    import glob
    files = [p for p in glob.glob(os.path.join(PAGES, 'kategoriya_*.htm')) if os.path.isfile(p)]
    files.sort(key=os.path.getmtime, reverse=True)       # новая страница первой
    out = []
    for p in files:
        name = os.path.basename(p)
        m = re.match(r'kategoriya_(\d{4}-\d{2}-\d{2})', name)
        out.append({'name': name, 'date': m.group(1) if m else '', 'path': p})
    return out


def load_lots(path):
    """Лоты страницы: ([(лот, 'rule' | 'unc')], всего лотов). 'rule' = правило признало скриптом, 'unc' = неясно, ждёт
    отметки. Лоты, которые правила отбросили (чужой проект, другой срок, не рубли и т.д.), сюда не попадают."""
    key = (path, os.path.getmtime(path))
    if key in _LOTS_CACHE:
        return _LOTS_CACHE[key]
    seen, lots = set(), []
    for l in read_lots(path):
        if l['id'] in seen:
            continue
        seen.add(l['id'])
        lots.append(l)
    items = []
    for l in lots:
        _term, reason = classify(l)
        if reason is None:
            if l['валюта'] == CURRENCY_OK and l['цена_руб'] is not None:
                items.append((l, 'rule'))
        elif reason.startswith('не подтверждён'):
            items.append((l, 'unc'))
    add_dup_flags([l for l, _k in items])
    _LOTS_CACHE.clear()
    _LOTS_CACHE[key] = (items, len(lots))
    return _LOTS_CACHE[key]


def api_lots(snap_name):
    snaps = list_snapshots()
    info = {'version': VERSION, 'snapshots': [{'name': s['name'], 'date': s['date']} for s in snaps]}
    if not snaps:
        info.update(snap='', lots=[], total=0, stale=0,
                    note='В папке pages нет сохранённых страниц. Сохраните страницу категории или нажмите «Обновить» на вкладке «Данные».')
        return info
    chosen = next((s for s in snaps if s['name'] == snap_name), snaps[0])
    items, total = load_lots(chosen['path'])
    marks = marks_raw()
    _LOT_NAMES.clear()
    rows = []
    for l, kind in items:
        lid = l['id']
        _LOT_NAMES[lid] = l['название']
        auto = ''
        if kind == 'rule':
            auto = 'ниша' if is_niche(l['название']) else 'скрипт'
        manual = marks.get(lid, {}).get('отметка', '')
        if manual not in MARK_VALUES:
            manual = ''
        rows.append({'id': lid, 'title': l['название'], 'seller': l['продавец'], 'price': l['цена_руб'],
                     'cur': l['валюта'], 'reviews': l['отзывов_продавца'], 'auto_issue': l['автовыдача'],
                     'dup': l['группа_дубля'], 'kind': kind, 'auto': auto,
                     'mark': manual or auto,
                     'src': 'вручную' if manual else ('правило' if kind == 'rule' else '')})
    rows.sort(key=lambda r: (1 if r['mark'] else 0, r['price'] if r['price'] is not None else 1e18))   # сверху без отметки
    ids = {r['id'] for r in rows}
    info.update(snap=chosen['name'], date=chosen['date'], lots=rows, total=total,
                stale=sum(1 for i in marks if i not in ids), note='')
    return info


def kept_lots(items, marks):
    """Какие лоты идут в итог и цены: [(лот, ниша?, 'rule'|'hand')]. Ручная отметка сильнее правила."""
    out = []
    for l, kind in items:
        manual = marks.get(l['id'], {}).get('отметка', '')
        if manual not in MARK_VALUES:
            manual = ''
        if kind == 'rule':
            if manual == 'нет':
                continue
            niche = manual == 'ниша' or (manual != 'скрипт' and is_niche(l['название']))
        else:
            if manual not in ('скрипт', 'ниша'):
                continue
            if l['валюта'] != CURRENCY_OK or l['цена_руб'] is None:
                continue
            niche = manual == 'ниша'
        out.append((l, niche, 'rule' if (kind == 'rule' and not manual) else 'hand'))
    return out


def api_prices(snap_name):
    snaps = list_snapshots()
    empty = {'version': VERSION, 'snap': '', 'date': '', 'total': 0, 'kept': 0, 'sellers': 0, 'by_rule': 0,
             'by_hand': 0, 'niche': 0, 'unc_open': 0, 'lots': []}
    if not snaps:
        empty['note'] = 'В папке pages нет сохранённых страниц.'
        return empty
    chosen = next((s for s in snaps if s['name'] == snap_name), snaps[0])
    items, total = load_lots(chosen['path'])
    marks = marks_raw()
    kept = kept_lots(items, marks)
    copies = [dict(l) for l, _n, _s in kept]            # копии: флаги дублей здесь не должны менять экран «Отметки»
    add_dup_flags(copies)
    keys, lots = {}, []
    for c, (_l, niche, src) in zip(copies, kept):
        dk = keys.setdefault(dup_key(c)[0], len(keys))
        lots.append({'id': c['id'], 'title': c['название'], 'seller': c['продавец'], 'price': c['цена_руб'],
                     'reviews': c['отзывов_продавца'], 'auto_issue': c['автовыдача'], 'term': '7 дней',
                     'dup': c['группа_дубля'], 'dk': dk, 'niche': niche, 'src': src})
    unc_open = sum(1 for l, kind in items
                   if kind == 'unc' and marks.get(l['id'], {}).get('отметка', '') not in MARK_VALUES)
    return {'version': VERSION, 'snap': chosen['name'], 'date': chosen['date'], 'total': total,
            'kept': len(lots), 'sellers': len({x['seller'] for x in lots}),
            'by_rule': sum(1 for x in lots if x['src'] == 'rule'), 'by_hand': sum(1 for x in lots if x['src'] == 'hand'),
            'niche': sum(1 for x in lots if x['niche']), 'unc_open': unc_open, 'lots': lots, 'note': ''}


# ---- защита и запуск загрузчика ----
def protection():
    """Состояние защиты по fetch_state.json (его пишет загрузчик). Остановка действует до конца дня."""
    st = read_json(STATE, {})
    day = datetime.date.today().isoformat()
    res, d = str(st.get('результат', '')), str(st.get('дата', ''))
    return {'stopped': d == day and res.startswith('остановлен'), 'date': d, 'time': str(st.get('время', '')),
            'result': res, 'reason': res.split(':', 1)[1].strip() if res.startswith('остановлен') and ':' in res else '',
            'stop_file': bool(d) and os.path.exists(os.path.join(PAGES, f'_stop_{d}.html'))}


def _fetch_worker():
    code = -1
    for attempt in range(len(FETCH_RETRY_WAIT) + 1):
        try:
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1')
            pr = subprocess.Popen([sys.executable, os.path.abspath(__file__), 'fetch'], cwd=HERE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                                  errors='replace', env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            timer = threading.Timer(900, pr.kill)       # страховка: зависший загрузчик убираем через 15 минут
            timer.daemon = True
            timer.start()
            for line in pr.stdout:
                FETCH['lines'].append(line.rstrip('\r\n'))
            code = pr.wait()
            timer.cancel()
        except Exception as e:
            FETCH['lines'].append(f'Не удалось запустить загрузчик: {type(e).__name__}: {e}')
            code = -1
        if code not in FETCH_RETRY_CODES or attempt >= len(FETCH_RETRY_WAIT):
            break                                       # успех, блокировка (код 2/3) или попытки кончились
        w = FETCH_RETRY_WAIT[attempt]
        FETCH['lines'].append(f'--- Автоповтор {attempt + 2} из {len(FETCH_RETRY_WAIT) + 1} через {w} с (код {code}) ---')
        time.sleep(w)
    try:
        ensure_index()
    except Exception as e:
        FETCH['lines'].append(f'История не обновлена: {type(e).__name__}: {e}')
    try:
        auto_log(FETCH['started'], FETCH['source'], code)
    except Exception as e:
        FETCH['lines'].append(f'Журнал запусков не записан: {type(e).__name__}: {e}')
    FETCH['code'] = code
    FETCH['running'] = False


def fetch_start(source='вручную'):
    """Один запуск загрузчика на нажатие (или на автоснимок). Не стартует, если уже идёт запуск или сегодня проход остановлен."""
    with FETCH_LOCK:
        if FETCH['running']:
            return 409, {'error': 'Загрузка уже идёт, подождите.'}
        pr = protection()
        if pr['stopped']:
            return 409, {'error': 'Сегодня проход остановлен (' + (pr['reason'] or pr['result']) + '). Повтор запрещён, попробуйте завтра.'}
        FETCH.update(running=True, lines=[], code=None, source=source, started=datetime.datetime.now().isoformat(timespec='seconds'))
    threading.Thread(target=_fetch_worker, daemon=True).start()
    return 200, {'ok': True}


def fetch_status():
    code = FETCH['code']
    text = ''
    if not FETCH['running'] and code is not None:
        text = EXIT_TEXT.get(code, f'Запуск завершился с кодом {code}. Подробности в тексте ниже.')
    return {'running': FETCH['running'], 'code': code, 'text': text, 'started': FETCH['started'], 'source': FETCH['source'],
            'log': '\n'.join(FETCH['lines'][-300:])}


# ---- автоснимок: пока программа открыта, сама запускает загрузчик, если прошла пауза и сегодня нет остановки ----
def auto_read():
    cfg = dict(AUTO_DEFAULT)
    raw = read_json(AUTO_CFG, {})
    if isinstance(raw.get('включено'), bool):
        cfg['включено'] = raw['включено']
    h = raw.get('пауза_часов')
    if isinstance(h, (int, float)) and not isinstance(h, bool) and 1 <= h <= 168:
        cfg['пауза_часов'] = h
    return cfg


def last_attempt():
    """Время последней попытки загрузчика (ручной или автоматической), из fetch_state.json."""
    try:
        return datetime.datetime.fromisoformat(str(read_json(STATE, {}).get('время', '')))
    except ValueError:
        return None


def auto_log(started, source, code):
    text = EXIT_TEXT.get(code, f'код {code}')
    with AUTO_LOCK:
        new = not os.path.exists(AUTO_LOG)
        with open(AUTO_LOG, 'a', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, delimiter=';')
            if new:
                w.writerow(['время', 'источник', 'код', 'результат'])
            w.writerow([started.replace('T', ' '), source, code, text])


def auto_log_tail(n=15):
    rows = []
    try:
        with open(AUTO_LOG, encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f, delimiter=';'))
    except OSError:
        pass
    return [{'time': r.get('время', ''), 'source': r.get('источник', ''), 'text': r.get('результат', '')} for r in rows[-n:][::-1]]


def auto_state():
    """(настройки, время последней попытки, когда можно, причина «не сейчас» или '')."""
    cfg, last, now = auto_read(), last_attempt(), datetime.datetime.now()
    failed = str(read_json(STATE, {}).get('результат', '')).startswith('ошибка')
    due = last + (datetime.timedelta(minutes=30) if failed else datetime.timedelta(hours=cfg['пауза_часов'])) if last else None
    if not cfg['включено']:
        why = 'выключено'
    elif protection()['stopped']:
        why = 'остановка'
    elif FETCH['running']:
        why = 'идёт загрузка'
    elif due and now < due:
        why = 'пауза'
    else:
        why = ''
    return cfg, last, due, why


def network_ok():
    """Только DNS-запрос к системе: есть ли сеть. На сайт запроса нет."""
    try:
        socket.getaddrinfo(os.environ.get('MARKET_TEST_HOST', 'funpay.com'), 443)
        return True
    except OSError:
        return False


def auto_tick():
    _cfg, _last, _due, why = auto_state()
    if why:
        return why
    if not network_ok():
        return 'нет сети'
    code, info = fetch_start('авто')
    return '' if code == 200 else info.get('error', 'не запущено')


def auto_loop():
    time.sleep(AUTO_FIRST_DELAY)
    while True:
        try:
            auto_tick()
        except Exception:
            traceback.print_exc()
        time.sleep(AUTO_EVERY)


def api_auto():
    cfg, _last, due, why = auto_state()
    if not cfg['включено']:
        text = 'Автоснимок выключен.'
    elif why == 'остановка':
        text = 'Сегодня проход остановлен, автоснимок не запускается до завтра.'
    elif why == 'идёт загрузка':
        text = 'Сейчас идёт загрузка.'
    elif due:
        text = ('Следующий автоснимок возможен после ' + due.strftime('%d.%m %H:%M') if why == 'пауза'
                else 'Пауза прошла: автоснимок запустится при ближайшей проверке (раз в 10 минут, пока программа открыта).')
    else:
        text = 'Запусков ещё не было: автоснимок запустится через несколько секунд после старта программы.'
    return {'enabled': cfg['включено'], 'hours': cfg['пауза_часов'], 'text': text, 'log': auto_log_tail()}


# ---- история: по CSV на каждый снимок (папка history/) ----
def rules_hash():
    parts = [str(x) for x in (GAME_OK, TYPE_OK, SAMP_WORDS, CHEAT_WORDS, SCRIPT_WORDS, AUTO_WORDS, AUTO_ISSUE,
                              NICHE_WORDS, ACTIVITY_WORDS)]
    return hashlib.md5('|'.join(parts).encode('utf-8')).hexdigest()[:8]


def read_index():
    idx = {}
    if os.path.exists(INDEX):
        with open(INDEX, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f, delimiter=';'):
                if r.get('снимок'):
                    idx[r['снимок']] = r
    return idx


def index_snapshot(snap, rh):
    """Читает страницу и пишет два файла: лоты-кандидаты (скрипты и неясные) и все продавцы страницы."""
    path, stem = snap['path'], snap['name'][:-4]
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    day, hhmm = snap['date'] or mt.date().isoformat(), mt.strftime('%H:%M')
    seen, lots = set(), []
    for l in read_lots(path):
        if l['id'] not in seen:
            seen.add(l['id'])
            lots.append(l)
    units = {}
    for l in lots:
        u = l['валюта'] or '(нет значка)'
        units[u] = units.get(u, 0) + 1
    cands, sellers = [], {}
    for l in lots:
        sl = sellers.setdefault(l['продавец'], {'дата': day, 'время': hhmm, 'снимок': stem, 'продавец': l['продавец'],
                                                'отзывов_продавца': l['отзывов_продавца'], 'на_сайте': l['на_сайте'],
                                                'лотов_на_странице': 0})
        sl['лотов_на_странице'] += 1
        if not sl['на_сайте'] and l['на_сайте']:
            sl['на_сайте'] = l['на_сайте']
        _term, reason = classify(l)
        if reason is None or reason.startswith('не подтверждён'):
            cands.append({'дата': day, 'время': hhmm, 'снимок': stem, 'id': l['id'], 'продавец': l['продавец'],
                          'цена_руб': '' if l['цена_руб'] is None else l['цена_руб'], 'валюта': l['валюта'],
                          'отзывов_продавца': l['отзывов_продавца'], 'на_сайте': l['на_сайте'], 'срок': '7 дней',
                          'автовыдача': l['автовыдача'], 'решение': 'правило' if reason is None else 'неясно',
                          'название': l['название']})
    os.makedirs(HISTORY, exist_ok=True)
    write_csv_atomic(os.path.join(HISTORY, 'lots_' + stem + '.csv'), LOT_COLS, cands)
    write_csv_atomic(os.path.join(HISTORY, 'sellers_' + stem + '.csv'), SELLER_COLS, sorted(sellers.values(), key=lambda x: x['продавец']))
    return {'снимок': stem, 'файл': snap['name'], 'дата': day, 'время': hhmm, 'размер': os.path.getsize(path),
            'лотов_на_странице': len(lots), 'кандидатов': len(cands),
            'валюты': ', '.join(f'{u} {n}' for u, n in sorted(units.items(), key=lambda x: -x[1])),
            'правила': rh, 'ошибка': ''}


def ensure_index():
    """Каждая страница из pages попадает в историю. Заново читается только новая, изменившаяся или
    разобранная по старым правилам (смена правил в разделе 2)."""
    os.makedirs(HISTORY, exist_ok=True)
    with INDEX_LOCK:
        idx, rh, changed = read_index(), rules_hash(), False
        for snap in list_snapshots():
            stem = snap['name'][:-4]
            e = idx.get(stem)
            files_ok = all(os.path.exists(os.path.join(HISTORY, f'{k}_{stem}.csv')) for k in ('lots', 'sellers'))
            if e and not e.get('ошибка') and files_ok and str(e.get('размер')) == str(os.path.getsize(snap['path'])) \
                    and e.get('правила') == rh:
                continue
            try:
                idx[stem] = index_snapshot(snap, rh)
            except Exception as ex:
                mt = datetime.datetime.fromtimestamp(os.path.getmtime(snap['path']))
                idx[stem] = {'снимок': stem, 'файл': snap['name'], 'дата': snap['date'] or mt.date().isoformat(),
                             'время': mt.strftime('%H:%M'), 'размер': '', 'лотов_на_странице': '', 'кандидатов': '',
                             'валюты': '', 'правила': rh, 'ошибка': f'{type(ex).__name__}: {ex}'[:200]}
            changed = True
        if changed:
            write_csv_atomic(INDEX, INDEX_COLS, [idx[k] for k in sorted(idx)])
        return idx


def read_hist_lots(stem):
    rows = []
    with open(os.path.join(HISTORY, f'lots_{stem}.csv'), encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter=';'):
            r['цена_руб'] = float(r['цена_руб']) if r['цена_руб'] not in ('', None) else None
            rows.append(r)
    return rows


def hist_items(stem):
    items = []
    for r in read_hist_lots(stem):
        if r['решение'] == 'правило':
            if r['валюта'] == CURRENCY_OK and r['цена_руб'] is not None:
                items.append((r, 'rule'))
        else:
            items.append((r, 'unc'))
    return items


def read_hist_sellers(stem):
    out = {}
    with open(os.path.join(HISTORY, f'sellers_{stem}.csv'), encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f, delimiter=';'):
            v = str(r.get('отзывов_продавца', '')).strip()
            out[r['продавец']] = [int(v) if v.isdigit() else 0, r.get('на_сайте', '')]
    return out


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def api_history():
    """Один снимок на день (последний по времени). Лоты в расчёте по текущим правилам и отметкам."""
    idx = ensure_index()
    sig = (_mtime(INDEX), _mtime(MARKS), len(idx))
    if _HIST_CACHE.get('sig') == sig:
        return _HIST_CACHE['val']
    marks = marks_raw()
    best = {}
    for stem, e in idx.items():
        if e.get('ошибка') or not e.get('дата'):
            continue
        key = (e.get('время', ''), stem)
        if e['дата'] not in best or key > best[e['дата']][0]:
            best[e['дата']] = (key, stem)
    keys, per, union = {}, [], set()
    for date in sorted(best):
        (tm, stem) = best[date][0]
        try:
            kept = kept_lots(hist_items(stem), marks)
            page = read_hist_sellers(stem)
        except (OSError, ValueError, KeyError):
            continue
        copies = [dict(l) for l, _n, _s in kept]
        lots = []
        for c, (_l, niche, _src) in zip(copies, kept):
            dk = keys.setdefault(dup_key(c)[0], len(keys))
            rv = str(c['отзывов_продавца']).strip()
            lots.append({'id': c['id'], 'title': c['название'], 'seller': c['продавец'], 'price': c['цена_руб'],
                         'reviews': int(rv) if rv.isdigit() else 0, 'auto_issue': c['автовыдача'], 'dk': dk, 'niche': niche})
        sel = {x['seller'] for x in lots}
        union |= sel
        per.append({'date': date, 'time': tm, 'stem': stem, 'total': idx[stem].get('лотов_на_странице', ''), 'lots': lots, 'sel': sel, 'page': page})
    meta = {}
    for s_name in union:
        m = {'fc': None, 'fs': None}
        for i, d in enumerate(per):
            if m['fc'] is None and s_name in d['page']:
                m['fc'] = i
            if m['fs'] is None and s_name in d['sel']:
                m['fs'] = i
        meta[s_name] = m
    days = [{'date': d['date'], 'time': d['time'], 'stem': d['stem'], 'total': d['total'], 'lots': d['lots'],
             'sellers': {n: d['page'][n] for n in union if n in d['page']}} for d in per]
    val = {'version': VERSION, 'days': days, 'meta': meta, 'snapshots': len(idx)}
    _HIST_CACHE.clear()
    _HIST_CACHE.update(sig=sig, val=val)
    return val


def api_data():
    idx = ensure_index()
    marks = marks_raw()
    day = datetime.date.today().isoformat()
    snaps = []
    for stem, e in idx.items():
        calc = ''
        if not e.get('ошибка'):
            try:
                calc = len(kept_lots(hist_items(stem), marks))
            except (OSError, ValueError, KeyError):
                calc = ''
        units = e.get('валюты', '')
        snaps.append({'stem': stem, 'file': e.get('файл', ''), 'date': e.get('дата', ''), 'time': e.get('время', ''),
                      'total': e.get('лотов_на_странице', ''), 'cands': e.get('кандидатов', ''), 'calc': calc,
                      'units': units, 'not_rub': bool(units) and any(not u.strip().startswith(CURRENCY_OK) for u in units.split(',')),
                      'error': e.get('ошибка', ''), 'page_exists': os.path.exists(os.path.join(PAGES, e.get('файл', '')))})
    snaps.sort(key=lambda x: (x['date'], x['time']), reverse=True)
    return {'version': VERSION, 'today': day, 'protection': protection(), 'can_fetch': True,
            'has_today': any(x['date'] == day and not x['error'] for x in snaps), 'snapshots': snaps,
            'fetch': {'running': FETCH['running']}}


def post_mark(b):
    lot_id, mark = str(b.get('id', '')), b.get('mark', None)
    if not is_id(lot_id, 12) or mark not in MARK_VALUES + ('',):
        return 400, {'error': 'Неверный ID лота или отметка'}
    try:
        set_mark(lot_id, mark)
    except PermissionError:
        return 500, {'error': 'marks.csv занят другой программой. Закройте его в Excel и нажмите ещё раз'}
    except OSError as e:
        return 500, {'error': f'не удалось записать marks.csv: {e}'}
    return 200, {'ok': True, 'id': lot_id, 'mark': mark}


def post_auto(b):
    en, h = b.get('enabled'), b.get('hours')
    if not isinstance(en, bool) or isinstance(h, bool) or not isinstance(h, (int, float)) or not 1 <= h <= 168:
        return 400, {'error': 'Пауза должна быть числом часов от 1 до 168.'}
    try:
        write_json_atomic(AUTO_CFG, {'включено': en, 'пауза_часов': h})
    except OSError as e:
        return 500, {'error': f'не удалось записать auto_settings.json: {e}'}
    return 200, {'ok': True}


ROUTES_DETECTOR = {
    'GET': {'/api/lots': lambda b: (200, api_lots(b.get('snap', ''))),
            '/api/prices': lambda b: (200, api_prices(b.get('snap', ''))),
            '/api/data': lambda b: (200, api_data()),
            '/api/fetch': lambda b: (200, fetch_status()),
            '/api/auto': lambda b: (200, api_auto()),
            '/api/history': lambda b: (200, api_history())},
    'POST': {'/api/mark': post_mark,
             '/api/fetch': lambda b: fetch_start(),
             '/api/auto': post_auto},
}



# ===== 6. Вкладка «Аккаунт»: вход, лоты, форма лота, количество, поднятие =============================
# Ключ golden_key хранится только в памяти; в golden_key.txt пишется лишь по галочке «Запомнить» (простым текстом).
# Правка лота двухшаговая: preview_edit («было → стало», ничего не отправляется) и отдельная кнопка apply_edit.
# Все запросы к сайту идут через guarded(): один замок, остановка сессии при блокировке/капче/редиректе.
ACC = {'key': None, 'me': None, 'avatar': None, 'forms': {}, 'pending': None, 'locked': False}
ACC_LOCK = threading.Lock()
LOCK_WORDS = ('Сайт ответил HTTP', 'капч', 'перенаправил')
AMOUNT_FRESH_SEC = 300
AMOUNTS = {}                        # id лота -> {'a': число строкой, 't': время}  (amounts_cache.json, только числа)
AMOUNTS.update(read_json(AMOUNTS_CACHE, {}))
UI_FIELDS = [('title', 'Название', 'entry'), ('desc', 'Описание', 'text'), ('price', 'Цена, ₽', 'entry'),
             ('amount', 'Количество', 'entry'), ('auto', 'Автовыдача', 'check'),
             ('secrets', 'Товары автовыдачи', 'text'),
             ('active', 'Лот активен (показывается)', 'check')]


def amounts_save():
    try:
        write_json_atomic(AMOUNTS_CACHE, AMOUNTS)
    except OSError:
        pass


def is_service(section):
    return bool(re.search(r'услуг', section or '', re.I))


def guarded(fn):
    """Единая обёртка запросов аккаунта: (код, тело). SiteStop с признаками блокировки блокирует сессию до перезапуска."""
    if ACC['locked']:
        return 409, {'error': 'Сессия остановлена: сайт ответил блокировкой или проверкой. Запросы отключены до перезапуска программы.'}
    try:
        with ACC_LOCK:
            return 200, fn()
    except SiteStop as s:
        msg = str(s)
        if any(w in msg for w in LOCK_WORDS):
            ACC['locked'] = True
            msg += ' Сессия заблокирована: ничего не повторяется и не обходится.'
        return 409, {'error': msg}
    except UserError as e:
        return 400, {'error': str(e)}
    except Exception as e:
        return 500, {'error': f'{type(e).__name__}: {e}'}


def fetch_avatar(url):
    if not url:
        return None
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        url = SITE_BASE + url
    if not re.match(r'https://([a-z0-9-]+\.)?(funpay|sfunpay)\.com/', url):
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA_ACCOUNT})
        with urllib.request.urlopen(req, timeout=15) as r:
            img = r.read(2 * 1024 * 1024)
    except Exception:
        return None
    for sig, mime in ((b'\x89PNG', 'image/png'), (b'GIF8', 'image/gif'), (b'\xff\xd8', 'image/jpeg')):
        if img.startswith(sig):
            return f'data:{mime};base64,' + base64.b64encode(img).decode()
    if img[:4] == b'RIFF' and img[8:12] == b'WEBP':
        return 'data:image/webp;base64,' + base64.b64encode(img).decode()
    return None


def acc_login(key, remember):
    _, _, home = site_request('/', key)
    uid = app_data(home).get('userId')
    if not uid:
        raise SiteStop('Ключ не подошёл: сайт вас не узнал (нет ID). Проверьте golden_key.')
    soup = BeautifulSoup(home, 'html.parser')
    nick_el = soup.select_one('.user-link-name')
    el = soup.select_one('.avatar-photo') or soup.select_one('.user-link-photo')
    url = None
    if el:
        mt = re.search(r'url\(["\']?([^)"\']+)', el.get('style', ''))
        url = mt.group(1) if mt else None
    ACC.update(key=key, me={'uid': str(uid), 'nick': nick_el.get_text(strip=True) if nick_el else '(ник не найден)'},
               avatar=fetch_avatar(url), forms={}, pending=None)
    if remember and not CLOUD:
        with open(KEYFILE, 'w', encoding='utf-8') as f:
            f.write(key)
    return {'ok': True}


def load_offers():
    _, _, prof = site_request(f"/users/{ACC['me']['uid']}/", ACC['key'])
    soup = BeautifulSoup(prof, 'html.parser')
    rows = []
    for block in soup.select('div.offer'):
        title = block.select_one('.offer-list-title a')
        href = title.get('href', '') if title else ''
        node = (re.search(r'/lots/(\d+)/', href) or [None, ''])[1]
        section = title.get_text(' ', strip=True) if title else '?'
        for it in block.select('a.tc-item'):
            t, p, am = it.select_one('.tc-desc-text'), it.select_one('.tc-price'), it.select_one('.tc-amount')
            rows.append({'id': it.get('href', '').split('id=')[-1], 'node': node, 'section': section,
                         'title': t.get_text(' ', strip=True) if t else '',
                         'price': p.get_text(' ', strip=True) if p else '',
                         'amount': am.get_text(strip=True) if am else '',
                         'auto': 'да' if (it.has_attr('data-auto') or it.select_one('[class*="auto"]')) else ''})
    if not rows:
        raise SiteStop('На странице профиля лоты не найдены: разметка другая или лотов нет.')
    now = time.time()
    for r in rows:
        if is_service(r['section']):                      # услуги: количества нет
            r['svc'], r['amount'], r['fresh'] = True, '—', True
            continue
        c = AMOUNTS.get(r['id'])
        if c:
            r['amount'] = c.get('a', '')
            r['fresh'] = now - c.get('t', 0) < AMOUNT_FRESH_SEC
    return {'rows': rows}


def find_name(alias, names):
    c = [n for n in names if re.search(ALIASES[alias], n, re.I)]
    ru = [n for n in c if '[ru]' in n]
    return c[0] if len(c) == 1 else (ru[0] if len(ru) == 1 else None)


def load_form(node, offer):
    page = f'/lots/offerEdit?node={node}&offer={offer}'
    _, _, html = site_request(page, ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    form = find_form(soup)
    if not form:
        raise SiteStop('Форма редактирования не найдена. Ничего не отправлено.')
    fields, boxes, cbs = form_fields(form)
    ACC['forms'][offer] = {'page': page, 'html': html, 'form': form, 'fields': fields, 'boxes': boxes, 'cbs': cbs}
    names, out = set(fields) | set(boxes), []
    for alias, label, kind in UI_FIELDS:
        real = find_name(alias, names)
        if real:
            out.append({'alias': alias, 'label': label, 'kind': kind,
                        'value': (real in fields) if kind == 'check' else fields.get(real, '')})
    return {'fields': out}


def show_value(n, v):
    """Предпросмотр: список товаров автовыдачи не показываем, только число строк."""
    v = str(v)
    if re.fullmatch(r'secrets', n):
        return f"{len([x for x in v.replace(chr(13), '').split(chr(10)) if x.strip()])} строк"
    return mask(n, v)


def preview_edit(offer, vals):
    d = ACC['forms'].get(offer)
    if not d:
        raise SiteStop('Форма лота не загружена. Нажмите «Изменить» заново.')
    names, sets = set(d['fields']) | set(d['boxes']), []
    areal = find_name('auto', names)
    auto_on = bool(vals['auto']) if 'auto' in vals else bool(areal and areal in d['fields'])
    for alias, _label, kind in UI_FIELDS:
        real = find_name(alias, names)
        if not real or alias not in vals:
            continue
        if (alias == 'amount' and auto_on) or (alias == 'secrets' and not auto_on):
            continue                                     # при автовыдаче количество = число строк товаров
        v = vals[alias]
        if kind == 'check':
            if bool(v) != (real in d['fields']):
                sets.append(f'{real}={"1" if v else "0"}')
        else:
            v = str(v).strip() if kind == 'entry' else str(v).replace('\r\n', '\n')
            if v != d['fields'].get(real, '').replace('\r\n', '\n'):
                sets.append(f'{real}={v}')
    if not sets:
        return {'changes': [], 'token': ''}
    new, changes = apply_sets(d['fields'], d['boxes'], d['cbs'], sets)
    if not changes:
        return {'changes': [], 'token': ''}
    token = secrets.token_hex(8)
    ACC['pending'] = {'id': offer, 'new': new, 'changes': changes, 'token': token}
    return {'changes': [{'field': n, 'old': show_value(n, o), 'new': show_value(n, w)} for n, o, w in changes],
            'token': token}


def apply_edit(offer, token):
    p, d = ACC['pending'], ACC['forms'].get(offer)
    if not p or not d or p['id'] != offer or not secrets.compare_digest(p['token'], str(token)):
        raise SiteStop('Нет подтверждённого предпросмотра для этого лота. Ничего не отправлено.')
    ACC['pending'] = None
    sk = find_name('secrets', set(d['fields']) | set(d['boxes']))
    if sk and any(c[0] == sk for c in p['changes']):
        # перед отправкой списка товаров форма перечитывается: если на сайте список уже другой (часть выдана
        # покупателям), отправка отменяется, чтобы не вернуть выданные товары
        _, _, fresh_html = site_request(d['page'], ACC['key'])
        fform = find_form(BeautifulSoup(fresh_html, 'html.parser'))
        if not fform:
            raise SiteStop('Не смог перепроверить список товаров перед отправкой. Ничего не отправлено.')
        now = form_fields(fform)[0].get(sk, '').replace('\r\n', '\n')
        if now != d['fields'].get(sk, '').replace('\r\n', '\n'):
            raise SiteStop('Список товаров на сайте изменился с момента открытия формы (возможно, часть уже выдана покупателям). Ничего не отправлено, откройте лот заново.')
    status, resp = submit_form(ACC['key'], d['form'], d['html'], p['new'], d['page'], p['changes'])
    AMOUNTS.pop(offer, None)
    return {'status': status, 'resp': resp}


def raise_node(node):
    """Поднять предложения одного раздела: открыть /lots/N/trade, найти кнопку, отправить один POST. Ответ сайта не толкуется."""
    page = f'/lots/{node}/trade'
    _, _, html = site_request(page, ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    btn = None
    for e in soup.find_all(['a', 'button']):
        if re.search(r'js-lot-raise', ' '.join(e.get('class', [])), re.I):
            btn = e
            break
    if btn is None:
        for e in soup.find_all(['a', 'button']):
            if re.search(r'поднять', e.get_text(' '), re.I):
                btn = e
                break
    game = (btn.get('data-game') if btn is not None else None) or None
    if btn is not None and not game:
        any_game = soup.find(attrs={'data-game': True})
        game = any_game.get('data-game') if any_game else None
    node_id = (btn.get('data-node') if btn is not None else None) or node
    if btn is None or not game:
        os.makedirs(PAGES_OWN, exist_ok=True)
        out = os.path.join(PAGES_OWN, f'trade_{node}.htm')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(redact(html))
        what = 'кнопка «поднять»' if btn is None else 'номер игры (data-game)'
        raise SiteStop(f'Не нашёл: {what}. Ничего не отправлено. Страница сохранена: {out} (токены вырезаны), пришлите её мне.')
    # Как в браузере: 1-й запрос (game_id, node_id). Если у игры есть другие ваши разделы, сайт отвечает окном
    # с галочками (node_ids[]): 2-м запросом отправляем ВСЕ разделы из окна, тогда поднимаются все сразу.
    def post(ids):
        data = [('game_id', str(game)), ('node_id', str(node_id))] + [('node_ids[]', str(n)) for n in ids]
        _, _, text = site_request('/lots/raise', ACC['key'], data=data, referer=page)
        return text

    def parse(text):
        msg, modal, err, wait = '', '', None, 0
        try:
            j = json.loads(text)
            msg = strip_tags(j.get('msg') or '')
            err, modal = j.get('error'), (j.get('modal') or '')
            try:
                wait = int(j.get('wait') or 0)
            except (TypeError, ValueError):
                wait = 0
            if wait:
                msg += f" (ждать примерно {wait // 60} мин, до {j.get('unlock_at', '?')} UTC)"
        except (ValueError, AttributeError):
            msg = redact(text)[:300]
        return msg, modal, err, wait

    msg, modal, err, wait = parse(post([]))
    raised = [str(node_id)]
    if modal:
        ms = BeautifulSoup(str(modal), 'html.parser')
        ids = []
        for i in ms.select('input[name="node_ids[]"]'):
            v = str(i.get('value') or '')
            if re.fullmatch(r'\d{1,10}', v) and v not in ids:
                ids.append(v)
        if not ids:
            os.makedirs(PAGES_OWN, exist_ok=True)
            out = os.path.join(PAGES_OWN, f'raise_modal_{node}.htm')
            with open(out, 'w', encoding='utf-8') as f:
                f.write(redact(str(modal)))
            raise SiteStop(f'Сайт показал окно выбора разделов, но галочек в нём не нашёл. Ничего не отправлено. '
                           f'Окно сохранено: {out}. Пришлите мне этот файл.')
        msg, _m2, err, wait = parse(post(ids))
        raised = ids
        msg = f'поднимаю разделов: {len(ids)}. ' + msg
    return {'node': node, 'msg': re.sub(r'\s+', ' ', msg).strip()[:400], 'modal': False, 'error': err,
            'wait': wait, 'raised': raised}


def load_node_amounts(node):
    """Количество всех лотов раздела одним запросом: страница /lots/N/trade (колонка «Наличие»)."""
    _, _, html = site_request(f'/lots/{node}/trade', ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    out, now = {}, time.time()
    for it in soup.select('a.tc-item'):
        oid = it.get('data-offer') or (it.get('href') or '').split('id=')[-1]
        am = it.select_one('.tc-amount')
        digits = re.sub(r'\D', '', am.get_text()) if am else ''
        if oid and digits:
            out[oid] = digits
            AMOUNTS[oid] = {'a': digits, 't': now}
    amounts_save()
    return {'amounts': out}


def load_amount(node, offer):
    """Количество одного лота из формы; при автовыдаче это число строк списка товаров, сам список не сохраняется."""
    _, _, html = site_request(f'/lots/offerEdit?node={node}&offer={offer}', ACC['key'])
    form = find_form(BeautifulSoup(html, 'html.parser'))
    if not form:
        raise SiteStop('Форма лота не найдена, количество не загружено.')
    fields, boxes, _cbs = form_fields(form)
    names = set(fields) | set(boxes)
    areal, sreal, mreal = find_name('auto', names), find_name('secrets', names), find_name('amount', names)
    if areal and areal in fields and sreal:
        val = str(len([x for x in fields.get(sreal, '').replace('\r', '').split('\n') if x.strip()]))
    elif mreal:
        val = str(fields.get(mreal, ''))
    else:
        val = ''
    AMOUNTS[offer] = {'a': val, 't': time.time()}
    amounts_save()
    return {'amount': val}


def acc_status():
    me = ACC['me'] or {}
    return {'logged': bool(ACC['key']), 'nick': me.get('nick', ''), 'uid': me.get('uid', ''), 'avatar': ACC['avatar'],
            'keyfile': bool(ENV_KEY) or os.path.exists(KEYFILE), 'cloud': CLOUD, 'locked': ACC['locked']}


def need_login(fn):
    def wrapper(b):
        if not ACC['key']:
            return 409, {'error': 'Сначала войдите.'}
        return fn(b)
    return wrapper


def h_login(b):
    key = ''
    if b.get('use_file') and ENV_KEY:
        key = ENV_KEY
    elif b.get('use_file'):
        try:
            with open(KEYFILE, encoding='utf-8') as f:
                key = f.read().strip()
        except OSError:
            pass
    else:
        key = str(b.get('key', '')).strip()
    if not key or len(key) > 200 or not re.fullmatch(r'[A-Za-z0-9_.=%-]+', key):
        return 400, {'error': 'Ключ пустой или в нём лишние символы.'}
    return guarded(lambda: acc_login(key, bool(b.get('remember')) and not b.get('use_file')))


def h_logout(b):
    ACC.update(key=None, me=None, avatar=None, forms={}, pending=None)
    return 200, {'ok': True}


def h_forget(b):
    if CLOUD:
        return 200, {'ok': True}
    try:
        os.remove(KEYFILE)
    except OSError:
        pass
    return 200, {'ok': True}


def _node_and_id(b, need_id=True):
    """(node, offer, ошибка). Проверка формата номеров, чтобы в адреса сайта попадали только цифры."""
    node, off = str(b.get('node', '')), str(b.get('id', ''))
    if need_id and not is_id(off, 12):
        return None, None, (400, {'error': 'Неверный ID лота'})
    if not is_id(node, 8):
        return None, None, (400, {'error': 'Неверный номер раздела'})
    return node, off, None


def h_raise(b):
    node, _o, err = _node_and_id(b, need_id=False)
    return err or guarded(lambda: raise_node(node))


def h_nodeamounts(b):
    node, _o, err = _node_and_id(b, need_id=False)
    return err or guarded(lambda: load_node_amounts(node))


def h_amount(b):
    node, off, err = _node_and_id(b)
    return err or guarded(lambda: load_amount(node, off))


def h_form(b):
    node, off, err = _node_and_id(b)
    return err or guarded(lambda: load_form(node, off))


def h_preview(b):
    off = str(b.get('id', ''))
    if not is_id(off, 12):
        return 400, {'error': 'Неверный ID лота'}
    return guarded(lambda: preview_edit(off, b.get('values') if isinstance(b.get('values'), dict) else {}))


def h_apply(b):
    off = str(b.get('id', ''))
    if not is_id(off, 12):
        return 400, {'error': 'Неверный ID лота'}
    return guarded(lambda: apply_edit(off, b.get('token', '')))


ROUTES_ACCOUNT = {
    'GET': {'/api/acc/status': lambda b: (200, acc_status())},
    'POST': {'/api/acc/status': lambda b: (200, acc_status()),
             '/api/acc/login': h_login, '/api/acc/logout': h_logout, '/api/acc/forget': h_forget,
             '/api/acc/offers': need_login(lambda b: guarded(load_offers)),
             '/api/acc/raise': need_login(h_raise), '/api/acc/nodeamounts': need_login(h_nodeamounts),
             '/api/acc/amount': need_login(h_amount), '/api/acc/form': need_login(h_form),
             '/api/acc/preview': need_login(h_preview), '/api/acc/apply': need_login(h_apply)},
}


# ===== 7. Сообщения ====================================================================================
# Список диалогов, история выбранного диалога и отправка сообщения, которое написал сам пользователь.
# Переписка держится только в памяти браузера: на диск не пишется, в логи не попадает. Автоответов и рассылок нет:
# одно нажатие «Отправить» = одно сообщение. Разметка /chat/ и /runner/ по памяти, живым сайтом не проверена полностью:
# если не нашлась, программа показывает список классов без текста сообщений.
MAX_CHAT_TEXT = 2000


def class_names(soup, prefixes):
    seen = set()
    for e in soup.find_all(True):
        for c in e.get('class', []):
            if c.startswith(prefixes):
                seen.add(c)
    return ', '.join(sorted(seen)[:40]) or '(нет)'


def chat_list():
    _, _, html = site_request('/chat/', ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for it in soup.select('a.contact-item'):
        cid = it.get('data-id')
        if not cid or not is_id(cid, 15):
            continue
        name = it.select_one('.media-user-name')
        msg = it.select_one('.contact-item-message')
        tm = it.select_one('.contact-item-time')
        rows.append({'id': str(cid),
                     'name': name.get_text(' ', strip=True) if name else '(без имени)',
                     'last': msg.get_text(' ', strip=True)[:120] if msg else '',
                     'time': tm.get_text(' ', strip=True) if tm else '',
                     'unread': 'unread' in it.get('class', [])})
    if not rows:
        raise SiteStop('Диалоги на странице /chat/ не найдены: разметка другая или диалогов нет. '
                       'Классы на странице (без текста переписки): ' + class_names(soup, ('chat', 'contact')) + '. Пришлите мне этот список.')
    return {'rows': rows}


def chat_history(node):
    _, _, html = site_request(f'/chat/?node={node}', ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    uid = ACC['me']['uid']
    items = soup.select('.chat-msg-item')
    if not items:
        raise SiteStop('Сообщения в диалоге не найдены: пусто или разметка другая. '
                       'Классы на странице (без текста переписки): ' + class_names(soup, ('chat', 'contact')) + '. Пришлите мне этот список.')
    out, author, mine, label = [], '', False, ''
    for it in items:
        a = it.select_one('.chat-msg-author-link')
        if it.select_one('.media-user-name') is not None:       # у сообщения есть шапка: метка берётся из неё (или пусто)
            lb = it.select_one('.chat-msg-author-label')
            label = lb.get_text(' ', strip=True).casefold() if lb else ''
        if a:
            author = a.get_text(' ', strip=True)
            mine = f'/users/{uid}/' in a.get('href', '')
        t = it.select_one('.chat-msg-text')
        if not t:
            continue
        d = it.select_one('.chat-msg-date')
        out.append({'author': author, 'mine': mine, 'label': label, 'time': (d.get('title') or d.get_text(strip=True)) if d else '',
                    'text': t.get_text('\n', strip=True)[:3000]})
    return {'messages': out[-60:]}


def chat_send(node, text):
    key = ACC['key']
    page = f'/chat/?node={node}'
    _, _, html = site_request(page, key)        # свежий csrf-токен перед отправкой
    tok = app_data(html).get('csrf-token')
    if not tok:
        raise SiteStop('Не нашёл csrf-токен, отправка невозможна. Ничего не отправлено.')
    objects = [{'type': 'chat_node', 'id': node, 'tag': '0000000000',
                'data': {'node': node, 'last_message': -1, 'content': ''}}]
    req = {'action': 'chat_message', 'data': {'node': node, 'last_message': -1, 'content': text}}
    _, _, resp = site_request('/runner/', key, referer=page,
                              data={'objects': json.dumps(objects), 'request': json.dumps(req, ensure_ascii=False),
                                    'csrf_token': tok})
    err = ''
    try:
        j = json.loads(resp)
        r = j.get('response') if isinstance(j, dict) else None
        if isinstance(r, dict) and r.get('error'):
            err = strip_tags(r['error'])[:300]
    except ValueError:
        pass
    return {'error_site': err, 'note': ('Сайт вернул ошибку: ' + err) if err else
            'Запрос отправлен. Ответ сайта программа не толкует: проверьте, что сообщение появилось в диалоге.'}


def h_chat_list(b):
    return guarded(chat_list)


def h_chat_history(b):
    node = str(b.get('node', ''))
    return guarded(lambda: chat_history(node)) if is_id(node, 15) else (400, {'error': 'Неверный номер диалога'})


def h_chat_send(b):
    node, text = str(b.get('node', '')), str(b.get('text', '')).strip()
    if not is_id(node, 15):
        return 400, {'error': 'Неверный номер диалога'}
    if not text:
        return 400, {'error': 'Сообщение пустое.'}
    if len(text) > MAX_CHAT_TEXT:
        return 400, {'error': f'Сообщение длиннее {MAX_CHAT_TEXT} символов.'}
    return guarded(lambda: chat_send(node, text))


ROUTES_CHAT = {'GET': {}, 'POST': {'/api/chat/list': need_login(h_chat_list), '/api/chat/history': need_login(h_chat_history),
                                   '/api/chat/send': need_login(h_chat_send)}}


# ===== 8. Заказы и напоминания о подтверждении =========================================================
# Общий разбор страницы /orders/trade (order_items, order_time) используют и напоминания, и статистика (раздел 9).
# Напоминания: «Найти заказы» (один запрос страницы, ничего не отправляется) -> список с галочками -> «Отправить
# выбранным» (после подтверждения; по одному покупателю, с паузами). Берутся заказы «Оплачен» старше 24 часов.
# Одному покупателю уходит ОДНО сообщение за раз (несколько заказов перечисляются в одном тексте). Не пишем, если
# напоминали меньше 24 часов назад; на заказ не больше 3 напоминаний; за раз не больше 30 покупателей.
# Журнал reminders_log.json: только ID покупателя, номера заказов и время, текст не хранится.
MIN_AGE_H, GAP_H, MAX_PER_ORDER, MAX_PER_RUN, MAX_REMIND_TEXT = 24, 24, 3, 30, 1000
REMIND = {'groups': {}}              # результат последнего «Найти заказы»: покупатель -> заказы (отправлять можно только из него)
MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
          'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
STATUS = {'оплачен': 'paid', 'закрыт': 'closed', 'возврат': 'refund'}


def order_time(absd, left, now):
    """Время заказа (дата оплаты): сначала «10 ноября, 21:18» / «сегодня, 09:05», потом «5 часов назад». Не разобрали: None."""
    s = (absd or '').strip().lower()
    try:
        m = re.match(r'(сегодня|вчера),?\s*(\d{1,2}):(\d{2})', s)
        if m:
            d = now.date() - datetime.timedelta(days=1 if m.group(1) == 'вчера' else 0)
            return datetime.datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)))
        m = re.match(r'(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?,?\s*(\d{1,2}):(\d{2})', s)
        if m and m.group(2) in MONTHS:
            y = int(m.group(3)) if m.group(3) else now.year
            t = datetime.datetime(y, MONTHS[m.group(2)], int(m.group(1)), int(m.group(4)), int(m.group(5)))
            return t.replace(year=y - 1) if (t > now and not m.group(3)) else t
    except ValueError:
        pass
    s = (left or '').strip().lower()
    m = re.search(r'(\d+)?\s*(минут|мин\b|час|д(?:ень|ня|ней)|недел|месяц)', s)
    if m and 'назад' in s:
        n = int(m.group(1)) if m.group(1) else 1
        u = m.group(2)
        hours = n / 60 if u.startswith('мин') else n if u.startswith('час') else n * 24 if u.startswith('д') \
            else n * (168 if u.startswith('недел') else 720)
        return now - datetime.timedelta(hours=hours)
    return None


def order_buyer(it):
    box = it.select_one('.media-user-name')
    if not box:
        return None, ''
    name = box.get_text(' ', strip=True)
    for e in [box] + box.find_all(True):
        for attr in ('href', 'data-href'):
            m = re.search(r'/users/(\d+)', e.get(attr, '') or '')
            if m:
                return m.group(1), name
    return None, name


def order_items(soup, now):
    """Все блоки a.tc-item страницы заказов: id, status (paid/closed/refund/None), price, cur, title, ts (datetime|None),
    buyer (id|None), buyer_name, has_status."""
    rows = []
    for it in soup.select('a.tc-item'):
        st = it.select_one('.tc-status')
        m = re.search(r'/orders/([A-Za-z0-9]+)', it.get('href', ''))
        p = it.select_one('.tc-price')
        ptxt = p.get_text(' ', strip=True) if p else ''
        num = re.sub(r'[^\d.,]', '', ptxt).replace(',', '.')
        try:
            price = float(num) if num else None
        except ValueError:
            price = None
        left, absd = it.select_one('.tc-date-left'), it.select_one('.tc-date-time')
        t = it.select_one('.order-desc div')
        buyer, buyer_name = order_buyer(it)
        rows.append({'id': m.group(1) if m else '', 'has_status': st is not None,
                     'status': STATUS.get(st.get_text(strip=True).casefold()) if st else None,
                     'price': price, 'cur': '₽' if '₽' in ptxt else (ptxt[-1:] or '?'),
                     'title': t.get_text(' ', strip=True)[:120] if t else '',
                     'ts': order_time(absd.get_text(' ', strip=True) if absd else '', left.get_text(' ', strip=True) if left else '', now),
                     'buyer': buyer, 'buyer_name': buyer_name})
    return rows


def remind_log_read():
    d = read_json(REMIND_LOG, {})
    return {'buyers': dict(d.get('buyers', {})), 'orders': dict(d.get('orders', {}))}


# ---------- напоминания v2: пропуск заказов, по которым уже подключена поддержка ----------
# Поддержка пишет в тот же диалог покупатель-продавец (метка «поддержка», в тексте «запрос на подтверждение заказа»).
# Сообщение поддержки после оплаты заказа = заказ уже рассматривают, покупателю напоминать не нужно.
# В тексте поддержки номера заказа нет, поэтому у покупателя с несколькими заказами пропускаются все заказы,
# оплаченные до этого сообщения; более новые остаются. Время сообщения не разобрали: пропускаем (безопасная сторона).
SUPPORT_TEXT = r'запрос на подтверждение заказа|передан на рассмотрение|ответственный сотрудник присоединится'


def support_times(msgs, now):
    """Времена сообщений поддержки в диалоге (None = время не разобрали)."""
    return [chat_time(m.get('time', ''), now) for m in msgs
            if 'поддержк' in str(m.get('label', '')).casefold() or has(SUPPORT_TEXT, m.get('text', ''))]


def remind_drop_supported(g, orders, now):
    """(оставшиеся заказы, причина, если не осталось, пропущенные номера). Открывает один диалог покупателя."""
    cdb = conf_load()
    keep, skipped = [], []
    for o in orders:
        if cdb['orders'].get(o['id'].upper(), {}).get('ticket_sent_at'):
            skipped.append(o['id'])
        else:
            keep.append(o)
    if skipped and not keep:
        return [], 'по заказу уже отправлен тикет в поддержку', skipped
    me, buyer = int(ACC['me']['uid']), int(g['buyer'])
    try:
        msgs = chat_history(f'users-{min(me, buyer)}-{max(me, buyer)}')['messages']
    except SiteStop as e:
        if str(e).startswith('Сообщения в диалоге не найдены'):
            return keep, '', skipped
        raise
    times = support_times(msgs, now)
    msgs = None                                     # текст переписки дальше не живёт
    if not times:
        return keep, '', skipped
    rest, hit = [], []
    for o in keep:
        paid = now - datetime.timedelta(hours=o['age'])
        (hit if any(t is None or t >= paid - datetime.timedelta(minutes=1) for t in times) else rest).append(o)
    if hit:
        known = [t for t in times if t]
        try:
            conf_mark_support([o['id'] for o in hit], max(known) if known else now)
        except Exception:
            traceback.print_exc()
    skipped += [o['id'] for o in hit]
    if not rest:
        return [], 'поддержка уже подключена к заказу (её сообщение в чате)', skipped
    return rest, '', skipped


def orders_pages(now, pages=1):
    """Страница /orders/trade и, если pages > 1, продолжения («continue») до конца или до pages страниц.
    Возвращает (строки без повторов, разметка первой страницы, прочитано страниц)."""
    key = ACC['key']
    _, _, html = site_request('/orders/trade', key)
    first, rows, ids, seen, used = None, [], set(), set(), 1
    while True:
        soup = BeautifulSoup(html, 'html.parser')
        first = first or soup
        page_rows = order_items(soup, now)
        for r in page_rows:
            if r.get('id') and r['id'].upper() in ids:
                continue
            if r.get('id'):
                ids.add(r['id'].upper())
            rows.append(r)
        cont = soup.find('input', attrs={'name': 'continue'})
        val = cont.get('value') if cont else ''
        if used >= pages or not page_rows or not val or val in seen:
            break
        seen.add(val)
        _, _, html = site_request('/orders/trade', key, data={'continue': val}, referer='/orders/trade')
        used += 1
    return rows, first, used


def remind_scan(max_run=None, pages=1):
    max_run = max_run or MAX_PER_RUN
    now = datetime.datetime.now()
    rows, soup, _used = orders_pages(now, pages)
    if not rows or not any(r['has_status'] for r in rows):
        raise SiteStop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет. '
                       'Классы на странице (без содержимого заказов): ' + class_names(soup, ('tc-', 'order'))
                       + '. Пришлите мне этот список.')
    try:
        conf_sync(rows, now)                    # раздел 8б: учёт заказов (строка добавлена этапом 1)
    except Exception:
        traceback.print_exc()
    log = remind_log_read()
    cnt = {'on_page': len(rows), 'paid': 0, 'young': 0, 'no_date': 0, 'no_buyer': 0, 'support': 0}
    by = {}
    for r in rows:
        if r['status'] != 'paid':
            continue
        cnt['paid'] += 1
        if not r['id'] or not r['buyer']:
            cnt['no_buyer'] += 1
            continue
        if r['ts'] is None:
            cnt['no_date'] += 1
            continue
        age = max(0.0, (now - r['ts']).total_seconds() / 3600)
        if age < MIN_AGE_H:
            cnt['young'] += 1
            continue
        g = by.setdefault(r['buyer'], {'buyer': r['buyer'], 'name': r['buyer_name'], 'orders': []})
        g['orders'].append({'id': r['id'], 'age': round(age, 1), 'title': r['title'][:80], 'sent': int(log['orders'].get(r['id'], 0))})
    groups, n_ok = [], 0
    REMIND['groups'] = {}
    for g in sorted(by.values(), key=lambda x: -max(o['age'] for o in x['orders'])):
        last = log['buyers'].get(g['buyer'])
        left_orders = [o for o in g['orders'] if o['sent'] < MAX_PER_ORDER]
        g['ok'], g['reason'] = True, ''
        try:
            hrs = (now - datetime.datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
        except ValueError:
            hrs = None
        if hrs is not None and hrs < GAP_H:
            g['ok'], g['reason'] = False, f'напоминали {hrs:.0f} ч назад'
        elif not left_orders:
            g['ok'], g['reason'] = False, f'уже {MAX_PER_ORDER} напоминания по заказу'
        elif n_ok >= max_run:
            g['ok'], g['reason'] = False, f'лимит {max_run} за раз, повторите позже'
        g['note'] = ''
        if g['ok']:                              # v2: заказы с подключённой поддержкой не напоминаем
            left_orders, why, skipped = remind_drop_supported(g, left_orders, now)
            cnt['support'] += len(skipped)
            if skipped and left_orders:
                g['note'] = 'без заказов у поддержки: ' + ', '.join('#' + x for x in skipped)
            if not left_orders:
                g['ok'], g['reason'] = False, why
        if g['ok']:
            n_ok += 1
            g['orders'] = left_orders
            REMIND['groups'][g['buyer']] = {'name': g['name'], 'orders': [o['id'] for o in left_orders]}
        groups.append(g)
    return {'groups': groups, 'counts': cnt}


def remind_send_one(buyer, template):
    g = REMIND['groups'].get(buyer)
    if not g:
        raise SiteStop('Этого покупателя нет в последнем списке. Нажмите «Найти заказы» заново. Ничего не отправлено.')
    log = remind_log_read()
    last = log['buyers'].get(buyer)
    try:
        too_soon = bool(last) and (datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds() < GAP_H * 3600
    except ValueError:
        too_soon = False
    if too_soon:
        raise SiteStop('Этому покупателю напоминание уже ушло меньше 24 часов назад. Ничего не отправлено.')
    text = template.replace('{order}', ', '.join('#' + o for o in g['orders']))
    try:
        tpl_save(template)
    except OSError:
        pass
    me = int(ACC['me']['uid'])
    node = f'users-{min(me, int(buyer))}-{max(me, int(buyer))}'
    res = chat_send(node, text)
    if not res['error_site']:
        log['buyers'][buyer] = datetime.datetime.now().isoformat(timespec='seconds')
        for o in g['orders']:
            log['orders'][o] = int(log['orders'].get(o, 0)) + 1
        write_json_atomic(REMIND_LOG, log)
        try:
            conf_on_reminded(g['orders'])        # раздел 8б: фиксируем время напоминания (строка добавлена этапом 1)
        except Exception:
            traceback.print_exc()
        REMIND['groups'].pop(buyer, None)
    return {'note': res['note'], 'error_site': res['error_site']}


def h_remind_send(b):
    buyer, text = str(b.get('buyer', '')), str(b.get('text', '')).strip()
    if not is_id(buyer, 15):
        return 400, {'error': 'Неверный ID покупателя'}
    if not text or len(text) > MAX_REMIND_TEXT:
        return 400, {'error': f'Текст пустой или длиннее {MAX_REMIND_TEXT} символов.'}
    return guarded(lambda: remind_send_one(buyer, text))


ROUTES_REMIND = {'GET': {}, 'POST': {'/api/remind/preview': need_login(lambda b: guarded(remind_scan)),
                                     '/api/remind/send': need_login(h_remind_send)}}


# ===== 8б. Подтверждение заказов: состояния, таймер 24 ч, журнал, текст тикета (этап 1) ===================
# Зачем: если покупатель забыл нажать «подтвердить», FunPay сам заказ не закрывает: нужен тикет в поддержку.
# Здесь только учёт и подготовка текста. Ничего не отправляется ни покупателю, ни в поддержку: тикет вы
# отправляете вручную (https://support.funpay.com/tickets/new), напоминание покупателю уходит из раздела 8.
# Состояния: paid (оплачен) -> delivered (товар выдан) -> reminded (напоминание отправлено, время, старт таймера)
#            -> confirmed (подтверждён). Боковое: refunded (возврат). «Не подтвердил» не хранится, а вычисляется:
#            reminded и после последнего напоминания прошло CONF_HOURS часов. Повторное напоминание перезапускает таймер.
#            Выдачу можно пропустить: из paid сразу в reminded (так и бывает, если заказ подхвачен автоматически).
# Откуда берутся данные: вручную (вкладка/маршруты ниже) и автоматически из страницы /orders/trade, которую уже
# читает раздел 8: conf_sync() заводит «Оплачен» как paid и ставит confirmed/refunded тем, что сайт показал
# «Закрыт»/«Возврат»; conf_on_reminded() фиксирует напоминание, отправленное из раздела 8. Покупателей храним
# только по ID (как и reminders_log.json), текст переписки не храним.
# Тикет готовится только для заказов: reminded + прошло 24 ч + ваша отметка chat_ok («чат проверен: услуга оказана,
# покупатель однозначно просто забыл подтвердить»). Отметку ставите вы, программа чат не читает и не проверяет.
# Проверка чатов (по кнопке «Проверить чаты»): для каждого покупателя открывается один диалог (/chat/?node=users-A-B), читается
# ТОЛЬКО последнее сообщение. Заказ «подходит», если последнее сообщение написали вы, оно совпадает с текстом напоминания
# (в нём есть номер заказа) и написано 24 часа назад или раньше. Если последним писал покупатель или не прошло 24 часа, не подходит.
# Сохраняется только результат проверки (подходит / не подходит и причина) и время сообщения, текст переписки не хранится.
# Отметку «чат проверен» при подходящем заказе ставит программа (chat_auto); это не проверка того, что услуга оказана.
# Файлы: confirm_orders.json (состояния), confirm_log.csv (журнал всех действий и отказов), tickets/ (тексты тикетов).
CONF_DB = P('confirm_orders.json')
CONF_LOG = P('confirm_log.csv')
TICKETS_DIR = P('tickets')
CONF_LOCK = threading.RLock()
CONF_HOURS = 24
SELLER_NICK = 'TalentSeller'
TICKET_URL = 'https://support.funpay.com/tickets/new'
CONF_STATUS_RU = {'paid': 'оплачен', 'delivered': 'товар выдан', 'reminded': 'напоминание отправлено',
                  'confirmed': 'подтверждён', 'refunded': 'возврат'}
CONF_DONE = ('confirmed', 'refunded')


def conf_load():
    d = read_json(CONF_DB, {})
    d.setdefault('orders', {})
    return d


def conf_save(d):
    write_json_atomic(CONF_DB, d)


def conf_log(order_id, action, detail='', ok=True):
    """Журнал для человека (открывается в Excel). Пишутся и успехи, и отказы."""
    new = not os.path.exists(CONF_LOG)
    with CONF_LOCK, open(CONF_LOG, 'a', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        if new:
            w.writerow(['время', 'заказ', 'действие', 'подробности', 'результат'])
        w.writerow([datetime.datetime.now().isoformat(timespec='seconds'), order_id or '', action, detail, 'ок' if ok else 'отказ'])


def conf_log_tail(order_id=None, n=200):
    try:
        with open(CONF_LOG, encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f, delimiter=';'))
    except OSError:
        return []
    if order_id:
        rows = [r for r in rows if r.get('заказ') == order_id]
    return [{'time': r.get('время', ''), 'order': r.get('заказ', ''), 'action': r.get('действие', ''),
             'detail': r.get('подробности', ''), 'ok': r.get('результат') == 'ок'} for r in rows[-n:][::-1]]


def conf_id(x):
    x = str(x or '').strip().lstrip('#').strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{3,20}', x):
        raise UserError(f'Номер заказа «{x}» выглядит неправильно (буквы и цифры, например AB12CD34, без «#»).')
    return x


def conf_time(s):
    if not s:
        return datetime.datetime.now().replace(microsecond=0)
    s = str(s).strip().replace('T', ' ')
    for f in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d.%m.%Y %H:%M', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(s, f)
        except ValueError:
            pass
    raise UserError(f'Не понял время «{s}». Формат: ГГГГ-ММ-ДД ЧЧ:ММ (например 2026-11-13 18:30).')


def conf_iso(dt):
    return dt.isoformat(timespec='seconds')


def conf_dt(s):
    try:
        return datetime.datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def conf_human(s):
    dt = conf_dt(s)
    return dt.strftime('%d.%m.%Y %H:%M') if dt else '—'


def conf_deadline(o):
    r = conf_dt(o.get('reminder_at'))
    return r + datetime.timedelta(hours=CONF_HOURS) if r else None


def conf_overdue(o, now=None):
    d = conf_deadline(o)
    return bool(d) and o['status'] == 'reminded' and (now or datetime.datetime.now()) >= d


def conf_left(o, now=None):
    d = conf_deadline(o)
    if not d or o['status'] != 'reminded':
        return ''
    mins = int((d - (now or datetime.datetime.now())).total_seconds() // 60)
    if mins <= 0:
        return f'просрочено на {-mins // 60} ч {-mins % 60} мин'
    return f'осталось {mins // 60} ч {mins % 60} мин'


def conf_blockers(o, now=None):
    """Почему заказ нельзя включить в тикет (пустой список = можно)."""
    why = []
    if o['status'] in CONF_DONE:
        why.append('заказ уже закрыт (' + CONF_STATUS_RU[o['status']] + ')')
        return why
    if o['status'] != 'reminded':
        why.append('нет зафиксированного напоминания покупателю')
    if o.get('support_at'):
        why.append('поддержка уже подключена к заказу (её сообщение в чате от ' + conf_human(o['support_at']) + ')')
    elif not conf_overdue(o, now):
        why.append(f'таймер {CONF_HOURS} ч не вышел ({conf_left(o, now)})')
    if not o.get('chat_ok'):
        why.append('нет вашей отметки «чат проверен» (услуга оказана, покупатель однозначно забыл подтвердить)')
    return why


def conf_dialog_url(d, o):
    if o.get('dialog_url'):
        return o['dialog_url']
    me = (ACC.get('me') or {}).get('uid') or d.get('me_uid')
    if me and o.get('buyer') and is_id(me, 15) and is_id(o['buyer'], 15):
        a, b = sorted((int(me), int(o['buyer'])))
        return f'https://funpay.com/chat/?node=users-{a}-{b}'     # тот же вид адреса диалога, что в разделе 7
    return f'https://funpay.com/orders/{o["id"]}/'                # запасной вариант: страница заказа (формат по памяти)


def conf_view(d, o, now=None):
    return {'id': o['id'], 'status': o['status'], 'status_ru': CONF_STATUS_RU[o['status']], 'lot': o.get('lot', ''),
            'price': o.get('price', ''), 'buyer': o.get('buyer', ''), 'paid_at': o.get('paid_at'),
            'delivered_at': o.get('delivered_at'), 'reminder_at': o.get('reminder_at'), 'reminders': o.get('reminders', 0),
            'confirmed_at': o.get('confirmed_at'), 'confirmed_by': o.get('confirmed_by', ''),
            'deadline': conf_iso(conf_deadline(o)) if conf_deadline(o) else None, 'left': conf_left(o, now),
            'overdue': conf_overdue(o, now), 'chat_ok': bool(o.get('chat_ok')), 'dialog_url': o.get('dialog_url', ''),
            'ticket_at': o.get('ticket_at'), 'ticket_sent_at': o.get('ticket_sent_at'), 'note': o.get('note', ''),
            'chat_check': o.get('chat_check'), 'chat_auto': bool(o.get('chat_auto')),
            'ticket_blockers': conf_blockers(o, now)}


def conf_refuse(order_id, action, why):
    conf_log(order_id, action, why, ok=False)
    raise UserError(why)


def conf_get(d, order_id, action):
    o = d['orders'].get(order_id)
    if not o:
        conf_refuse(order_id, action, f'Заказа {order_id} нет в учёте. Сначала добавьте его.')
    return o


def conf_new(order_id, at, lot='', price='', buyer=''):
    return {'id': order_id, 'status': 'paid', 'lot': str(lot)[:120], 'price': str(price)[:20], 'buyer': str(buyer),
            'paid_at': conf_iso(at) if at else None, 'delivered_at': None, 'reminder_at': None, 'reminders': 0,
            'confirmed_at': None, 'confirmed_by': '', 'chat_ok': False, 'dialog_url': '', 'ticket_at': None,
            'ticket_sent_at': None, 'note': ''}


# ---------- действия (каждое под замком; отказ пишется в журнал, данные не меняются) ----------
def conf_add(b):
    oid = conf_id(b.get('id'))
    buyer = str(b.get('buyer', '')).strip()
    if buyer and not is_id(buyer, 15):
        raise UserError('ID покупателя это число (из адреса его профиля), либо оставьте пустым.')
    with CONF_LOCK:
        d = conf_load()
        if oid in d['orders']:
            conf_refuse(oid, 'add', f'Заказ {oid} уже есть в учёте.')
        t = conf_time(b.get('at'))
        d['orders'][oid] = conf_new(oid, t, b.get('lot', ''), b.get('price', ''), buyer)
        conf_save(d)
        conf_log(oid, 'add', f'оплачен {conf_iso(t)}; лот: {b.get("lot") or "—"}; сумма: {b.get("price") or "—"}')
    return {'id': oid}


def conf_deliver(b):
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'deliver')
        if o['status'] != 'paid':
            conf_refuse(oid, 'deliver', f'Выдать можно только оплаченный заказ, сейчас: {CONF_STATUS_RU[o["status"]]}.')
        t = conf_time(b.get('at'))
        if conf_dt(o['paid_at']) and t < conf_dt(o['paid_at']):
            conf_refuse(oid, 'deliver', 'Время выдачи раньше времени оплаты.')
        o['status'], o['delivered_at'] = 'delivered', conf_iso(t)
        conf_save(d)
        conf_log(oid, 'deliver', f'товар выдан {conf_iso(t)}')
    return {'id': oid}


def conf_set_reminded(d, o, t, source):
    """Общая часть: ручное «напоминание отправлено» и автоматическая фиксация из раздела 8."""
    again = o['status'] == 'reminded'
    o['status'], o['reminder_at'], o['reminders'] = 'reminded', conf_iso(t), int(o.get('reminders', 0)) + 1
    conf_log(o['id'], 'remind', f'{"повторное " if again else ""}напоминание {conf_iso(t)} ({source}); '
             f'таймер до {conf_iso(t + datetime.timedelta(hours=CONF_HOURS))}'
             + ('' if o.get('delivered_at') else '; выдача не отмечена'))


def conf_remind(b):
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'remind')
        if o['status'] in CONF_DONE:
            conf_refuse(oid, 'remind', f'Заказ уже закрыт ({CONF_STATUS_RU[o["status"]]}), напоминание не нужно.')
        t = conf_time(b.get('at'))
        floor = conf_dt(o.get('reminder_at')) or conf_dt(o.get('delivered_at')) or conf_dt(o.get('paid_at'))
        if floor and t < floor:
            conf_refuse(oid, 'remind', 'Время напоминания раньше предыдущего события по заказу.')
        conf_set_reminded(d, o, t, 'вручную')
        conf_save(d)
    return {'id': oid}


def conf_confirm(b):
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'confirm')
        if o['status'] in CONF_DONE:
            conf_refuse(oid, 'confirm', f'Заказ уже закрыт ({CONF_STATUS_RU[o["status"]]}).')
        t = conf_time(b.get('at'))
        late = ' (после просрочки таймера)' if conf_overdue(o, t) else ''
        warn = ''
        if o.get('ticket_sent_at'):
            warn = 'тикет уже отправлен: сообщите поддержке, что покупатель подтвердил'
        elif o.get('ticket_at'):
            warn = 'текст тикета был подготовлен, но не отправлен: тикет больше не нужен'
        o['status'], o['confirmed_at'], o['confirmed_by'] = 'confirmed', conf_iso(t), 'вручную'
        conf_save(d)
        conf_log(oid, 'confirm', f'покупатель подтвердил {conf_iso(t)}{late}' + (f'; {warn}' if warn else ''))
    return {'id': oid, 'warn': warn}


def conf_chat_ok(b):
    oid = conf_id(b.get('id'))
    off = bool(b.get('off'))
    url = str(b.get('url', '')).strip()
    if url and not re.match(r'https://(www\.)?funpay\.com/', url):
        conf_refuse(oid, 'chat-ok', 'Ссылка на диалог должна начинаться с https://funpay.com/')
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'chat-ok')
        if off:
            o['chat_ok'], o['chat_auto'] = False, False
            conf_log(oid, 'chat-ok', 'отметка «чат проверен» снята')
        else:
            if o['status'] in CONF_DONE:
                conf_refuse(oid, 'chat-ok', f'Заказ уже закрыт ({CONF_STATUS_RU[o["status"]]}), отметка не нужна.')
            o['chat_ok'], o['chat_auto'] = True, False
            if url:
                o['dialog_url'] = url
            conf_log(oid, 'chat-ok', 'пользователь подтвердил: услуга оказана, из чата однозначно видно, что покупатель забыл подтвердить'
                     + (f'; ссылка: {url}' if url else ''))
        conf_save(d)
    return {'id': oid}


def conf_note(b):
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        conf_get(d, oid, 'note')['note'] = str(b.get('note', ''))[:300]
        conf_save(d)
        conf_log(oid, 'note', 'заметка изменена')
    return {'id': oid}


def conf_build_ticket(d, rows):
    first = rows[0]['id']
    out = [f'ТИКЕТ: заполните форму {TICKET_URL}',
           '  Вариант: «Проблема с заказом»',
           f'  Ваш ник (логин) на FunPay: {SELLER_NICK}',
           f'  Номер заказа: {first}' + ('  (первый из списка, остальные в комментарии)' if len(rows) > 1 else ''),
           '  Вы покупатель или продавец?: Продавец',
           '  Тема заявки: Покупатель забыл подтвердить заказ', '',
           'КОММЕНТАРИЙ (скопируйте всё, что ниже линии):', '-' * 60,
           ('Здравствуйте! Прошу подтвердить заказ: покупатель забыл нажать кнопку подтверждения.' if len(rows) == 1 else
            'Здравствуйте! Прошу подтвердить заказы, в которых покупатели забыли нажать кнопку подтверждения.'),
           'Услуга оказана, по чату заказа это видно однозначно.', '']
    for i, o in enumerate(rows, 1):
        out.append(f'{i}. Заказ #{o["id"]}')
        parts = [f'оплачен: {conf_human(o["paid_at"])}']
        if o.get('delivered_at'):
            parts.append(f'товар выдан: {conf_human(o["delivered_at"])}')
        parts.append(f'напоминание покупателю: {conf_human(o["reminder_at"])} (прошло больше {CONF_HOURS} ч), подтверждения нет')
        out.append('   ' + '; '.join(parts).capitalize() + '.')
        out.append(f'   Диалог: {conf_dialog_url(d, o)}')
    out += ['', 'Спасибо!']
    return '\n'.join(out) + '\n'


def conf_ticket(b):
    """Готовит текст тикета (файл в tickets/ и текст в ответе). Без списка id берутся все готовые заказы."""
    ids = [conf_id(i) for i in (b.get('ids') or [])]
    again = bool(b.get('again'))
    with CONF_LOCK:
        d = conf_load()
        cand = [conf_get(d, i, 'ticket') for i in ids] if ids else \
            sorted((o for o in d['orders'].values() if o['status'] == 'reminded'), key=lambda o: o['reminder_at'] or '')
        ready, skipped = [], []
        for o in cand:
            why = conf_blockers(o)
            if o.get('ticket_sent_at'):
                why.append('тикет уже отправлен')
            elif o.get('ticket_at') and not again:
                why.append('текст тикета уже готовили (чтобы повторить, включите «повторить»)')
            if why:
                skipped.append({'id': o['id'], 'why': why})
                if ids:                       # молча пропущенные при общем запросе не засоряют журнал
                    conf_log(o['id'], 'ticket-skipped', '; '.join(why), ok=False)
            else:
                ready.append(o)
        res = {'ready': [o['id'] for o in ready], 'skipped': skipped, 'text': '', 'file': ''}
        if ready:
            now = datetime.datetime.now().replace(microsecond=0)
            os.makedirs(TICKETS_DIR, exist_ok=True)
            res['text'] = conf_build_ticket(d, ready)
            res['file'] = os.path.join(TICKETS_DIR, f'ticket_{now.strftime("%Y%m%d_%H%M%S")}.txt')
            with open(res['file'], 'w', encoding='utf-8') as f:
                f.write(res['text'])
            for o in ready:
                o['ticket_at'] = conf_iso(now)
                conf_log(o['id'], 'ticket-prepared', f'текст тикета подготовлен: {os.path.basename(res["file"])} '
                         f'(заказов в тикете: {len(ready)}); НЕ отправлен')
            conf_save(d)
    return res


def conf_ticket_sent(b):
    ids = [conf_id(i) for i in (b.get('ids') or [])]
    if not ids:
        raise UserError('Не выбраны заказы.')
    with CONF_LOCK:
        d = conf_load()
        for i in ids:                         # сначала проверяем все, потом пишем: либо все, либо ни одного
            o = conf_get(d, i, 'ticket-sent')
            if not o.get('ticket_at'):
                conf_refuse(i, 'ticket-sent', f'По заказу {i} текст тикета не готовили.')
            if o['status'] in CONF_DONE:
                conf_refuse(i, 'ticket-sent', f'Заказ {i} уже закрыт, тикет не нужен.')
        now = conf_iso(datetime.datetime.now().replace(microsecond=0))
        for i in ids:
            d['orders'][i]['ticket_sent_at'] = now
            conf_log(i, 'ticket-sent', 'пользователь отметил: тикет отправлен вручную')
        conf_save(d)
    return {'ids': ids}

# ---------- проверка чатов: последнее сообщение моё, совпадает с напоминанием, прошло 24 ч ----------
CHECK_MAX_BUYERS = 30
REMIND_TPL = P('reminder_templates.json')      # тексты ваших напоминаний (шаблоны, не переписка), чтобы узнавать их в чатах


def tpl_load():
    return [t for t in read_json(REMIND_TPL, {}).get('templates', []) if isinstance(t, str) and t.strip()]


def tpl_save(template):
    t = str(template).strip()
    if not t:
        return
    lst = [x for x in tpl_load() if chat_norm(x) != chat_norm(t)]
    write_json_atomic(REMIND_TPL, {'templates': ([t] + lst)[:10]})

CHAT_RES_RU = {'ok': 'подходит', 'young': 'ещё нет 24 ч', 'client_last': 'последним писал покупатель',
               'no_match': 'последнее сообщение не напоминание', 'no_time': 'время сообщения не разобрано',
               'no_buyer': 'нет покупателя', 'no_chat': 'диалог не найден'}


def chat_norm(s):
    return re.sub(r'\s+', ' ', str(s).replace('\xa0', ' ')).strip().casefold()


def chat_time(s, now):
    """Время сообщения: «13 ноября, 22:30:52», «13 ноября 2026, 22:30», «13.11.2026, 22:30:52», «сегодня, 22:30», ISO. Не разобрали: None."""
    s = chat_norm(s)
    try:
        m = re.match(r'(сегодня|вчера),?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?', s)
        if m:
            d = now.date() - datetime.timedelta(days=1 if m.group(1) == 'вчера' else 0)
            return datetime.datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)), int(m.group(4) or 0))
        m = re.match(r'(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?\s*(?:г\.?)?,?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?', s)
        if m and m.group(2) in MONTHS:
            y = int(m.group(3)) if m.group(3) else now.year
            t = datetime.datetime(y, MONTHS[m.group(2)], int(m.group(1)), int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
            return t.replace(year=y - 1) if (t > now and not m.group(3)) else t
        m = re.match(r'(\d{1,2})\.(\d{2})\.(\d{2,4}),?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?', s)
        if m:
            y = int(m.group(3)) + (2000 if int(m.group(3)) < 100 else 0)
            return datetime.datetime(y, int(m.group(2)), int(m.group(1)), int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})[ t](\d{1,2}):(\d{2})(?::(\d{2}))?', s)
        if m:
            return datetime.datetime(*(int(x or 0) for x in m.groups()))
    except ValueError:
        pass
    return None


def remind_matches(template, text, order_id):
    """Сообщение = текст напоминания: {order} подставлен любым списком номеров, и номер этого заказа в сообщении есть."""
    parts = chat_norm(template).split('{order}')
    body = chat_norm(text)
    if re.fullmatch('.+?'.join(re.escape(p) for p in parts), body, re.S) is None:
        return False
    return len(parts) == 1 or ('#' + order_id.casefold()) in body


def conf_buyer(o):
    if o.get('buyer'):
        return str(o['buyer'])
    m = re.search(r'users-(\d+)-(\d+)', o.get('dialog_url', '') or '')
    me = str((ACC.get('me') or {}).get('uid', ''))
    if m and me in (m.group(1), m.group(2)):
        return m.group(2) if m.group(1) == me else m.group(1)
    return ''


def match_hint(templates, text, order_id):
    """Где сообщение расходится с лучшим из текстов напоминания (по 40 символов вокруг места расхождения)."""
    body, best = chat_norm(text), (-1, '', 0)
    for t in templates:
        exp = chat_norm(t).replace('{order}', '#' + order_id.casefold())
        i = 0
        while i < min(len(exp), len(body)) and exp[i] == body[i]:
            i += 1
        if i > best[0]:
            best = (i, exp, i)
    i, exp, _ = best
    return f'расхождение с позиции {i}: в чате «{body[i:i + 40]}», в тексте напоминания «{exp[i:i + 40]}»'


def conf_judge(o, last, templates, now):
    """(результат, пояснение, время сообщения или None) по последнему сообщению диалога."""
    if not last['mine']:
        return 'client_last', 'последнее сообщение в чате от покупателя', None
    mt = chat_time(last['time'], now)
    if mt is None:
        return 'no_time', f'не разобрал время последнего сообщения («{str(last["time"])[:40]}»)', None
    if not any(remind_matches(t, last['text'], o['id']) for t in templates):
        return 'no_match', 'последнее сообщение ваше, но текст не совпадает с напоминанием (или в нём нет номера заказа); ' + match_hint(templates, last['text'], o['id']), mt
    paid = conf_dt(o.get('paid_at'))
    if paid and mt < paid - datetime.timedelta(minutes=1):
        return 'no_match', 'напоминание написано раньше оплаты заказа', mt
    hrs = (now - mt).total_seconds() / 3600
    if hrs < CONF_HOURS:
        mins = int((CONF_HOURS - hrs) * 60)
        return 'young', f'напоминание {conf_human(conf_iso(mt))}, не прошло {CONF_HOURS} ч (осталось {mins // 60} ч {mins % 60} мин)', mt
    return 'ok', f'последнее сообщение ваше, напоминание {conf_human(conf_iso(mt))}, прошло больше {CONF_HOURS} ч', mt


def conf_chat_check(b):
    template = str(b.get('template', '')).strip()
    if not template or len(template) > MAX_REMIND_TEXT:
        raise UserError(f'Нужен текст напоминания (до {MAX_REMIND_TEXT} символов): он берётся из вкладки «Напоминания».')
    templates = [template] + [t for t in tpl_load() if chat_norm(t) != chat_norm(template)]
    try:
        tpl_save(template)                       # запоминаем: проверка и дальше узнаёт это напоминание
    except OSError:
        pass
    me = str((ACC.get('me') or {}).get('uid', ''))
    if not is_id(me, 15):
        raise UserError('Не знаю ваш ID на FunPay. Войдите заново на вкладке «Аккаунт».')
    now = datetime.datetime.now().replace(microsecond=0)
    with CONF_LOCK:
        snap = [dict(o) for o in conf_load()['orders'].values() if o['status'] not in CONF_DONE]
    snap.sort(key=lambda o: o.get('paid_at') or '')
    by, results = {}, {}
    for o in snap:
        buyer = conf_buyer(o)
        if is_id(buyer, 15):
            by.setdefault(buyer, []).append(o)
        else:
            results[o['id']] = ('no_buyer', 'у заказа нет ID покупателя: добавьте его или синхронизируйте с сайтом', None)
    def last_check(buyer):
        return min((o.get('chat_check') or {}).get('at', '') for o in by[buyer])
    order = sorted(by, key=last_check)                # непроверенные первыми, затем проверенные давнее всех: лимит не зацикливается
    buyers = order[:CHECK_MAX_BUYERS]
    left = len(by) - len(buyers)
    stop = None
    for buyer in buyers:
        node = f'users-{min(int(me), int(buyer))}-{max(int(me), int(buyer))}'
        try:
            msgs = chat_history(node)['messages']
        except SiteStop as e:
            if str(e).startswith('Сообщения в диалоге не найдены'):
                for o in by[buyer]:
                    results[o['id']] = ('no_chat', 'в диалоге с покупателем нет сообщений', None)
                continue
            stop = e
            break
        for o in by[buyer]:
            results[o['id']] = conf_judge(o, msgs[-1], templates, now) if msgs else ('no_chat', 'в диалоге нет сообщений', None)
        msgs = None                                   # текст переписки дальше не живёт
    cnt = {'ok': 0, 'bad': 0}
    reasons = {}
    for _res, _d, _m in results.values():
        reasons[CHAT_RES_RU[_res]] = reasons.get(CHAT_RES_RU[_res], 0) + 1
    with CONF_LOCK:
        d = conf_load()
        for oid, (res, detail, mt) in results.items():
            o = d['orders'].get(oid)
            if not o or o['status'] in CONF_DONE:
                continue
            o['chat_check'] = {'at': conf_iso(now), 'result': res, 'text': CHAT_RES_RU[res], 'detail': detail,
                               'msg_at': conf_iso(mt) if mt else None}
            cnt['ok' if res == 'ok' else 'bad'] += 1
            if res in ('ok', 'young'):                # время напоминания берём из чата: это факт, а не наша запись
                cur = conf_dt(o.get('reminder_at'))
                if o['status'] != 'reminded':
                    conf_set_reminded(d, o, mt, 'по чату')
                elif cur is None or abs((cur - mt).total_seconds()) > 600:
                    o['reminder_at'] = conf_iso(mt)
                    conf_log(oid, 'remind', f'время напоминания уточнено по чату: {conf_iso(mt)}')
            if res == 'ok' and not o.get('chat_ok'):
                o['chat_ok'], o['chat_auto'] = True, True
                conf_log(oid, 'chat-ok', 'авто по чату: ' + detail + '. Это не проверка того, что услуга оказана')
            elif res != 'ok' and o.get('chat_ok') and o.get('chat_auto'):
                o['chat_ok'], o['chat_auto'] = False, False
                conf_log(oid, 'chat-ok', 'авто-отметка снята: ' + detail)
        conf_save(d)
        conf_log('', 'chat-check', f'проверено покупателей: {len(buyers) - (1 if stop else 0)}, заказов: {cnt["ok"] + cnt["bad"]}: '
                 f'подходят {cnt["ok"]}, не подходят {cnt["bad"]} (' + ', '.join(f'{k}: {v}' for k, v in reasons.items()) + ') [проверка v3]' + (f'; не проверено из-за лимита {CHECK_MAX_BUYERS}: {left}' if left else '')
                 + ('; остановлено: ' + str(stop)[:150] if stop else ''))
    if stop:
        raise stop
    return {'buyers': len(buyers), 'ok': cnt['ok'], 'bad': cnt['bad'], 'left': left, 'reasons': reasons}


def conf_mark_support(order_ids, when):
    """Запоминает, что в чате по заказу есть сообщение поддержки (только время, текст не хранится)."""
    with CONF_LOCK:
        d, changed = conf_load(), False
        for oid in order_ids:
            o = d['orders'].get(str(oid).upper())
            if not o or o['status'] in CONF_DONE or o.get('support_at'):
                continue
            o['support_at'] = conf_iso(when.replace(microsecond=0))
            conf_log(o['id'], 'support', 'в чате есть сообщение поддержки после оплаты: напоминание покупателю не отправляется')
            changed = True
        if changed:
            conf_save(d)


# ---------- связь с разделом 8 (страница /orders/trade) ----------
def conf_sync(rows, now):
    """Вызывается из remind_scan с уже прочитанными заказами. Заводит «Оплачен» как paid; тем, что уже в учёте,
    ставит confirmed («Закрыт») или refunded («Возврат»). Своих запросов к сайту не делает."""
    cnt = {'new': 0, 'confirmed': 0, 'refunded': 0}
    with CONF_LOCK:
        d = conf_load()
        me = (ACC.get('me') or {}).get('uid')
        if me:
            d['me_uid'] = str(me)
        for r in rows:
            if not r.get('id'):
                continue
            oid = r['id'].upper()
            o = d['orders'].get(oid)
            if o is None:
                if r['status'] == 'paid':
                    d['orders'][oid] = conf_new(oid, r['ts'], r['title'], r['price'] if r['price'] is not None else '', r['buyer'] or '')
                    conf_log(oid, 'add', 'найден на странице заказов со статусом «Оплачен» (автоматически)')
                    cnt['new'] += 1
                continue
            if o['status'] in CONF_DONE:
                continue
            if not o.get('buyer') and r.get('buyer'):
                o['buyer'] = r['buyer']
            if r['status'] == 'closed':
                o['status'], o['confirmed_at'], o['confirmed_by'] = 'confirmed', conf_iso(now.replace(microsecond=0)), 'сайт: статус «Закрыт»'
                conf_log(oid, 'confirm', 'на странице заказов статус «Закрыт» (время = когда заметили)'
                         + ('; тикет уже отправлен: сообщите поддержке' if o.get('ticket_sent_at') else ''))
                cnt['confirmed'] += 1
            elif r['status'] == 'refund':
                o['status'] = 'refunded'
                conf_log(oid, 'refund', 'на странице заказов статус «Возврат»')
                cnt['refunded'] += 1
        conf_save(d)
    return cnt


def conf_on_reminded(order_ids):
    """Вызывается из remind_send_one после успешной отправки напоминания: фиксирует время и запускает таймер."""
    now = datetime.datetime.now().replace(microsecond=0)
    with CONF_LOCK:
        d = conf_load()
        for oid in order_ids:
            oid = str(oid).upper()
            o = d['orders'].get(oid)
            if o is None:
                o = d['orders'][oid] = conf_new(oid, None)
                conf_log(oid, 'add', 'заведён при отправке напоминания (дата оплаты неизвестна)')
            if o['status'] in CONF_DONE:
                continue
            conf_set_reminded(d, o, now, 'отправлено из раздела «Напоминания»')
        conf_save(d)


# ---------- маршруты ----------
def conf_call(fn):
    def wrapper(b):
        try:
            return 200, fn(b)
        except UserError as e:
            return 400, {'error': str(e)}
    return wrapper


def h_conf_list(q):
    show_all = str(q.get('all', '')) in ('1', 'true')
    now = datetime.datetime.now()
    d = conf_load()
    rows = [conf_view(d, o, now) for o in d['orders'].values() if show_all or o['status'] not in CONF_DONE]
    rows.sort(key=lambda r: (not r['overdue'], r['deadline'] or '9999', r['paid_at'] or ''))
    one = str(q.get('id', ''))
    return 200, {'hours': CONF_HOURS, 'templates': tpl_load(), 'orders': rows, 'log': conf_log_tail(one if one else None, 100),
                 'overdue': sum(1 for r in rows if r['overdue']), 'ready': sum(1 for r in rows if not r['ticket_blockers'] and not r['ticket_sent_at'] and not r['ticket_at'])}


def h_conf_sync(b):
    def run():
        _, _, html = site_request('/orders/trade', ACC['key'])
        rows = order_items(BeautifulSoup(html, 'html.parser'), datetime.datetime.now())
        if not rows or not any(r['has_status'] for r in rows):
            raise SiteStop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет.')
        return conf_sync(rows, datetime.datetime.now())
    return guarded(run)


ROUTES_CONFIRM = {'GET': {'/api/confirm/list': h_conf_list},
                  'POST': {'/api/confirm/add': conf_call(conf_add), '/api/confirm/deliver': conf_call(conf_deliver),
                           '/api/confirm/remind': conf_call(conf_remind), '/api/confirm/confirm': conf_call(conf_confirm),
                           '/api/confirm/chat-ok': conf_call(conf_chat_ok), '/api/confirm/note': conf_call(conf_note),
                           '/api/confirm/ticket': conf_call(conf_ticket), '/api/confirm/ticket-sent': conf_call(conf_ticket_sent),
                           '/api/confirm/sync': need_login(h_conf_sync),
                           '/api/confirm/chat-check': need_login(lambda b: guarded(lambda: conf_chat_check(b)))}}


# ===== 8в. Просьба об отзыве и награда за отзыв 5★ (этап 2) ============================================
# После того как заказ стал «подтверждён» (раздел 8б), покупателю можно отправить одно сообщение с просьбой об отзыве.
# Как работает: «Обновить список» показывает подтверждённые заказы и готовый текст для каждого (локально, без запросов к сайту);
# «Отправить» шлёт ОДНО сообщение по ОДНОМУ заказу после вашего подтверждения в окне. Автоотправки нет.
# Шаблоны: общий + свой на лот. Лот определяется по названию в заказе: правило «если название лота содержит ...».
#   Подстановки: {order} номер заказа, {lot} название лота, {price} сумма, {link} страница заказа (там оставляют отзыв),
#   {reward} строка про награду (пустая, пока награда не разрешена, см. ниже). Неизвестная подстановка = отказ, ничего не уходит.
# Защиты: на заказ одна просьба (повторно не шлём); покупателю не чаще раза в RV_GAP_H часов; нет ID покупателя = нельзя;
#   после возврата просьбы нет; «Не просить» исключает заказ; задержка после подтверждения настраивается (по умолчанию 0 ч).
# Награда (только за отзыв нужной оценки, по умолчанию 5★; НЕ сразу):
#   1) в просьбе есть строка-обещание {promise} «если оставите отзыв на 5 из 5, подарю ...» (только если награда включена в правиле лота;
#      сама награда в просьбе НЕ отправляется); условия запоминаются в заказе (review_reward) и позже не меняются;
#   2) оценку отзыва читает кнопка «Прочитать оценку» (один запрос страницы заказа, блок .review-container) или вы вносите вручную (поле review_stars):
#      кнопка «Показать структуру отзыва» сохраняет только блок отзыва страницы заказа (без чата), по нему делается разбор;
#   3) награда выдаётся кнопкой «Выдать награду» (одно сообщение, после вашего подтверждения), только если награда была обещана,
#      оценка записана и равна нужной, награда ещё не выдавалась. Повторно по заказу не выдаётся.
#   Тип награды: «штучный» (список промокодов в review_stock.json, 1 строка = 1 штука, за отзыв уходит N первых строк, они
#   удаляются из списка только после успешной отправки) или «бесконечный» (один и тот же текст/ссылка, список не расходуется).
#   Коды и тексты наград в журнал не пишутся, видны только количество и остаток.
# Данные: шаблоны и настройки в review_settings.json; список промокодов в review_stock.json (ключ = фрагмент названия лота);
#   состояние в confirm_orders.json (поля review_at, review_key, review_skip, review_reward, review_stars, reward_at в заказе);
#   журнал confirm_log.csv (действия review-*). Текст сообщений нигде не хранится: в журнал идёт только имя шаблона.
REVIEW_CFG = P('review_settings.json')
REVIEW_STOCK = P('review_stock.json')
RV_GAP_H, RV_MAX_PER_RUN, RV_MAX_TEXT, RV_MAX_RULES = 24, 30, 1000, 50
RV_MAX_STOCK, RV_MAX_LINE = 5000, 200
RV_MAX_MATCHES = 60                    # лотов в одном правиле
RV_VARS = ('order', 'lot', 'price', 'link', 'promise', 'reward')   # {promise} = строка-обещание; {reward} старое имя того же
RV_THANKS_VARS = ('order', 'stars', 'reward')
RV_TYPES = ('stock', 'endless')
RV_DEFAULT_TEXT = ('Здравствуйте! Спасибо за покупку, заказ {order} ({lot}). Если всё работает, оставьте, пожалуйста, '
                   'отзыв о заказе: {link}\n{promise}\nСпасибо!')
RV_THANKS_DEFAULT = 'Спасибо за отзыв на {stars} из 5! Ваша награда по заказу {order}:\n{reward}'


def rv_int(v, lo, hi, what):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise UserError(f'{what}: нужно целое число от {lo} до {hi}.')
    if not lo <= n <= hi or isinstance(v, bool):
        raise UserError(f'{what}: нужно целое число от {lo} до {hi}.')
    return n


def rv_check_text(text, what, allowed=RV_VARS):
    text = str(text or '').strip()
    if not text or len(text) > RV_MAX_TEXT:
        raise UserError(f'{what}: текст пустой или длиннее {RV_MAX_TEXT} символов.')
    bad = sorted({m for m in re.findall(r'\{([^{}]*)\}', text) if m not in allowed})
    if bad:
        raise UserError(f'{what}: неизвестные подстановки {", ".join("{" + b + "}" for b in bad)}. Можно: '
                        + ', '.join('{' + v + '}' for v in allowed) + '.')
    return text


def rv_reward(rw, what='', strict=False):
    """Награда правила: enabled, stars (нужная оценка), units (сколько штук), type (stock|endless), endless_text, thanks."""
    rw = rw if isinstance(rw, dict) else {}

    def num(key, lo, hi, dflt, label):
        try:
            return rv_int(rw.get(key, dflt), lo, hi, what + label)
        except UserError:
            if strict:
                raise
            return dflt
    raw_cost = rw.get('unit_cost', 0)
    try:
        cost = round(float(str(raw_cost if raw_cost not in (None, '') else 0).replace(',', '.')), 2)
        if not 0 <= cost <= 1000000:
            raise ValueError
    except ValueError:
        if strict:
            raise UserError(f'{what}стоимость 1 шт.: нужно число в рублях от 0 до 1 000 000.')
        cost = 0.0
    typ = rw.get('type')
    if typ not in RV_TYPES:
        if strict and typ is not None:
            raise UserError(f'{what}тип награды: «штучный» или «бесконечный».')
        typ = 'stock'
    out = {'enabled': rw.get('enabled') is True, 'stars': num('stars', 1, 5, 5, 'нужная оценка'),
           'units': num('units', 1, 1000, 1, 'сколько штук'), 'unit_cost': cost, 'type': typ,
           'endless_text': str(rw.get('endless_text') or '').strip()[:RV_MAX_TEXT],
           'thanks': str(rw.get('thanks') or '').strip()[:RV_MAX_TEXT] or RV_THANKS_DEFAULT}
    if strict:
        rv_check_text(out['thanks'], what + 'текст благодарности', RV_THANKS_VARS)
        if '{reward}' not in out['thanks']:
            raise UserError(f'{what}в тексте благодарности нет {{reward}}: покупатель не получит награду.')
        if out['enabled'] and typ == 'endless' and not out['endless_text']:
            raise UserError(f'{what}для бесконечной награды впишите текст или ссылку.')
    return out


def rv_matches(r):
    """Фрагменты названий лота правила: список matches (новый формат) или одиночный match (старый). Без пустых и повторов."""
    raw = r.get('matches') if isinstance(r.get('matches'), list) else [r.get('match')]
    out, seen = [], set()
    for m in raw:
        m = str(m or '').strip()[:80]
        if m and m.casefold() not in seen:
            seen.add(m.casefold())
            out.append(m)
    return out[:RV_MAX_MATCHES]


def rv_load():
    d = read_json(REVIEW_CFG, {})
    lots = []
    for r in d.get('lots', []) if isinstance(d.get('lots'), list) else []:
        if not (isinstance(r, dict) and isinstance(r.get('text'), str)):
            continue
        ms = rv_matches(r)
        if not ms:
            continue
        lots.append({'key': str(r.get('key') or ms[0]).strip()[:80] or ms[0], 'matches': ms, 'match': ms[0],
                     'text': r['text'].strip().replace('{reward}', '{promise}')[:RV_MAX_TEXT], 'reward': rv_reward(r.get('reward'))})
    text = d.get('default') if isinstance(d.get('default'), str) and d['default'].strip() else RV_DEFAULT_TEXT
    try:
        delay = float(d.get('delay_hours', 0))
        delay = delay if 0 <= delay <= 168 else 0.0
    except (TypeError, ValueError):
        delay = 0.0
    return {'default': text.strip().replace('{reward}', '{promise}')[:RV_MAX_TEXT], 'lots': lots, 'delay_hours': delay}


def rv_save(b):
    """Сохраняет шаблоны целиком."""
    with CONF_LOCK:
        default = rv_check_text(b.get('default'), 'Общий шаблон')
        raw = b.get('lots') if isinstance(b.get('lots'), list) else []
        if len(raw) > RV_MAX_RULES:
            raise UserError(f'Правил на лот не больше {RV_MAX_RULES}.')
        lots, seen, keys = [], {}, set()
        for i, r in enumerate(raw, 1):
            if not isinstance(r, dict):
                raise UserError(f'Правило {i}: непонятный формат.')
            ms = rv_matches(r)
            if not ms:
                raise UserError(f'Правило {i}: выберите хотя бы один лот.')
            for m in ms:
                if m.casefold() in seen:
                    raise UserError(f'Правило {i}: лот «{m[:40]}» уже входит в правило {seen[m.casefold()]} (сработает только первое). Уберите его из одного из правил.')
                seen[m.casefold()] = i
            key = str(r.get('key') or ms[0]).strip()[:80] or ms[0]
            while key.casefold() in keys:            # ключ списка промокодов уникален; у существующего правила он не меняется
                key = (key[:70] + '#' + str(i))[:80]
            keys.add(key.casefold())
            what = f'Правило {i} («{ms[0][:30]}»): '
            lots.append({'key': key, 'matches': ms, 'match': ms[0], 'text': rv_check_text(r.get('text'), what.rstrip(': ')),
                         'reward': rv_reward(r.get('reward'), what, strict=True)})
        try:
            delay = float(str(b.get('delay_hours', 0)).replace(',', '.'))
        except ValueError:
            raise UserError('Задержка после подтверждения: нужно число часов от 0 до 168.')
        if not 0 <= delay <= 168:
            raise UserError('Задержка после подтверждения: нужно число часов от 0 до 168.')
        write_json_atomic(REVIEW_CFG, {'default': default, 'lots': lots, 'delay_hours': delay})   # лот match дублирует matches[0] для старых версий
        conf_log(None, 'review-settings', f'шаблоны сохранены: правил на лот {len(lots)}, задержка {delay:g} ч, '
                 f'наград включено в правилах {sum(1 for r in lots if r["reward"]["enabled"])}')
    return {'ok': True}


# ---------- список промокодов (штучная награда) ----------
def rv_stock_load():
    out = {}
    lots = read_json(REVIEW_STOCK, {}).get('lots')
    for k, v in (lots.items() if isinstance(lots, dict) else []):
        if isinstance(v, list):
            out[str(k)] = [str(x) for x in v if str(x).strip()]
    return out


def rv_stock_set(b):
    """Список промокодов правила: 1 строка = 1 штука. «Заменить» или «Добавить». Содержимое в журнал не пишется."""
    match, append = str(b.get('key') or b.get('match') or '').strip(), b.get('append') is True
    lines, seen = [], set()
    for ln in str(b.get('text', '')).splitlines():
        s = ln.strip()
        if not s or s in seen:
            continue
        if len(s) > RV_MAX_LINE:
            raise UserError(f'Строка длиннее {RV_MAX_LINE} символов: одна строка это одна награда.')
        seen.add(s)
        lines.append(s)
    with CONF_LOCK:
        if match.casefold() not in {r['key'].casefold() for r in rv_load()['lots']}:
            raise UserError('Правило ещё не сохранено: выберите в нём хотя бы один лот и подождите пару секунд, потом загружайте список.')
        st = rv_stock_load()
        key = match.casefold()
        if append:
            have = st.get(key, [])
            lines = have + [x for x in lines if x not in set(have)]
        if len(lines) > RV_MAX_STOCK:
            raise UserError(f'В списке не больше {RV_MAX_STOCK} строк.')
        st[key] = lines
        write_json_atomic(REVIEW_STOCK, {'lots': st})
        conf_log(None, 'review-stock', f'список наград правила «{match[:30]}» {"дополнен" if append else "заменён"}: теперь {len(lines)} шт. '
                 '(содержимое в журнал не пишется)')
    return {'count': len(lines)}


# ---------- просьба об отзыве ----------
def rv_pick(cfg, lot):
    """(текст шаблона, правило или None, имя шаблона). Первое правило, чей фрагмент есть в названии лота; иначе общий."""
    low = (lot or '').casefold()
    for r in cfg['lots']:
        if any(m.casefold() in low for m in r['matches']):
            return r['text'], r, 'лот: ' + r['matches'][0][:40] + (f' (+{len(r["matches"]) - 1})' if len(r['matches']) > 1 else '')
    return cfg['default'], None, 'общий'


def rv_promise(rw):
    if rw['type'] == 'stock':
        return f'Если оставите отзыв на {rw["stars"]} из 5, подарю награду: {rw["units"]} шт.'
    return f'Если оставите отзыв на {rw["stars"]} из 5, подарю бонус.'


def rv_render(cfg, o):
    """Готовый текст просьбы. Ничего не отправляет. Возвращает (текст, имя шаблона, обещанная награда или None)."""
    text, rule, label = rv_pick(cfg, o.get('lot', ''))
    rv_check_text(text, 'Шаблон ' + label)
    promised = None
    if rule and rule['reward']['enabled']:
        rw = rule['reward']
        promised = {'match': rule['key'], 'stars': rw['stars'], 'units': rw['units'] if rw['type'] == 'stock' else 0, 'type': rw['type']}
    vals = {'order': '#' + o['id'], 'lot': o.get('lot') or 'заказ', 'price': str(o.get('price') or ''),
            'link': f'https://funpay.com/orders/{o["id"]}/', 'promise': rv_promise(rule['reward']) if promised else ''}
    vals['reward'] = vals['promise']                # старые шаблоны с {reward} работают как раньше
    out = re.sub(r'\{(\w+)\}', lambda m: vals.get(m.group(1), m.group(0)), text)
    out = re.sub(r'[ \t]+\n', '\n', out)
    out = re.sub(r'\n{3,}', '\n\n', out).strip()
    return out, label, promised


def rv_last_by_buyer(d):
    last = {}
    for o in d['orders'].values():
        t, b = conf_dt(o.get('review_at')), conf_buyer(o)
        if t and b and (b not in last or t > last[b]):
            last[b] = t
    return last


def rv_blockers(o, cfg, now, last):
    """Почему просьбу нельзя отправить сейчас (пустой список = можно)."""
    if o['status'] == 'refunded':
        return ['по заказу возврат']
    if o['status'] != 'confirmed':
        return ['заказ ещё не подтверждён (' + CONF_STATUS_RU[o['status']] + ')']
    if o.get('review_at'):
        return ['просьба уже отправлена ' + conf_human(o['review_at'])]
    if o.get('review_skip'):
        return ['вы отметили «не просить»']
    if o.get('reward_at') or o.get('review_stars') is not None:
        return ['покупатель уже оставил отзыв (оценка записана): просьба не нужна']
    if o.get('confirm_kind') == 'администратор' or (o.get('confirmed_by') or '').lower().startswith('администратор'):
        return ['заказ подтвердил администратор, а не покупатель: отзыв не просим']
    why = []
    b = conf_buyer(o)
    if not b:
        why.append('неизвестен ID покупателя (нажмите «Синхронизировать с сайтом» на вкладке «Подтверждения» или впишите вручную)')
    elif b in last and (now - last[b]).total_seconds() < RV_GAP_H * 3600:
        why.append(f'этому покупателю уже просили отзыв меньше {RV_GAP_H} ч назад')
    c = conf_dt(o.get('confirmed_at'))
    if c and cfg['delay_hours'] and now < c + datetime.timedelta(hours=cfg['delay_hours']):
        left = (c + datetime.timedelta(hours=cfg['delay_hours']) - now).total_seconds() / 3600
        why.append(f'задержка после подтверждения: ещё {left:.1f} ч')
    return why


def rv_node(o):
    buyer, me = conf_buyer(o), (ACC.get('me') or {}).get('uid')
    if not (me and is_id(me, 15) and is_id(buyer, 15)):
        return None
    return f'users-{min(int(me), int(buyer))}-{max(int(me), int(buyer))}'


def rv_reward_snap(o, cfg):
    """Условия награды по заказу: (условия или None, «без просьбы»?). Если просьба уходила с обещанием, берутся записанные
    в заказе условия. Если просьбы об отзыве не было вовсе, берутся условия правила на этот лот (покупатель сам оставил отзыв).
    Если просьба была без обещания награды, награды нет: её не обещали."""
    snap = o.get('review_reward')
    if snap:
        return snap, False
    if o.get('review_at'):
        return None, False
    _t, rule, _l = rv_pick(cfg, o.get('lot', ''))
    if rule and rule['reward']['enabled']:
        rw = rule['reward']
        return {'match': rule['key'], 'stars': rw['stars'], 'units': rw['units'] if rw['type'] == 'stock' else 0,
                'type': rw['type']}, True
    return None, False


def rv_reward_blockers(o, cfg):
    """Почему награду нельзя выдать сейчас (пустой список = можно). Награда только за отзыв нужной оценки."""
    snap, _unreq = rv_reward_snap(o, cfg)
    if not snap:
        return ['в просьбе не было обещания награды'] if o.get('review_at') else ['у лота нет правила с включённой наградой']
    if o['status'] != 'confirmed':
        return ['заказ не в статусе «подтверждён»']
    if o.get('reward_at'):
        return ['награда уже выдана ' + conf_human(o['reward_at'])]
    why = []
    st = o.get('review_stars')
    if st is None:
        why.append('оценка отзыва не записана: проверьте отзыв и укажите оценку')
    elif st != snap['stars']:
        why.append(f'оценка {st}, для награды нужна {snap["stars"]}')
    return why


def rv_list(q):
    now = datetime.datetime.now()
    d, cfg, stock = conf_load(), rv_load(), rv_stock_load()
    last = rv_last_by_buyer(d)
    rows = []
    by_key = {r['key'].casefold(): r for r in cfg['lots']}
    costs = {'given_n': 0, 'given_units': 0, 'spent': 0.0, 'est_n': 0, 'ready_n': 0, 'ready_units': 0, 'ready_cost': 0.0,
             'any_cost': any(float(r['reward'].get('unit_cost') or 0) > 0 for r in cfg['lots'] if r['reward']['enabled'] and r['reward']['type'] == 'stock')}
    for o in d['orders'].values():
        if o['status'] != 'confirmed':
            continue
        why = rv_blockers(o, cfg, now, last)
        try:
            text, label, promised = rv_render(cfg, o)
        except UserError as e:
            text, label, promised, why = '', '', None, why + [str(e)]
        snap, unreq = rv_reward_snap(o, cfg)
        rwhy = rv_reward_blockers(o, cfg) if snap else []
        uc, spent, spent_est = 0.0, None, False
        units = snap['units'] if snap and snap['type'] == 'stock' else 0
        if snap:
            r_ = by_key.get(snap['match'].casefold())
            uc = float(r_['reward'].get('unit_cost') or 0) if r_ else 0.0
            if o.get('reward_at'):
                if o.get('reward_cost') is not None:
                    spent, units = float(o['reward_cost']), int(o.get('reward_units') or units)
                else:
                    spent, spent_est = round(units * uc, 2), True        # выдана до ввода цены: считаем по текущей
                costs['given_n'] += 1
                costs['given_units'] += units
                costs['spent'] = round(costs['spent'] + spent, 2)
                costs['est_n'] += 1 if spent_est else 0
            elif not rwhy:
                costs['ready_n'] += 1
                costs['ready_units'] += units
                costs['ready_cost'] = round(costs['ready_cost'] + units * uc, 2)
        rows.append({'id': o['id'], 'lot': o.get('lot', ''), 'price': o.get('price', ''), 'confirmed_at': o.get('confirmed_at'), 'confirmed_by': o.get('confirmed_by') or '',
                     'review_at': o.get('review_at'), 'skip': bool(o.get('review_skip')), 'key': o.get('review_key') or label,
                     'text': text, 'reward_in_text': bool(promised), 'blockers': why, 'can': not why,
                     'stars': o.get('review_stars'), 'stars_src': o.get('review_stars_src') or '',
                     'reward': ({'need': snap['stars'], 'units': snap['units'], 'type': snap['type'], 'at': o.get('reward_at'), 'unrequested': unreq,
                                 'unit_cost': uc, 'cost': round(units * uc, 2), 'spent': spent, 'spent_est': spent_est,
                                 'blockers': rwhy, 'can': not rwhy} if snap else None)})
    rows.sort(key=lambda r: (not (r['can'] or (r['reward'] and r['reward']['can'])), r['review_at'] is not None,
                             -(conf_dt(r['confirmed_at']) or datetime.datetime.min).timestamp()))
    log = [r for r in conf_log_tail(None, 400) if r['action'].startswith('review')][:100]
    out_cfg = dict(cfg, stock={r['key']: len(stock.get(r['key'].casefold(), [])) for r in cfg['lots']})
    return 200, {'settings': out_cfg, 'orders': rows[:300], 'total': len(rows), 'ready': sum(1 for r in rows if r['can']),
                 'sent': sum(1 for r in rows if r['review_at']), 'reward_ready': sum(1 for r in rows if r['reward'] and r['reward']['can']),
                 'costs': costs, 'max_per_run': RV_MAX_PER_RUN, 'log': log, 'vars': list(RV_VARS),
                 'lots_seen': sorted({o.get('lot', '') for o in d['orders'].values() if o.get('lot')})[:200]}


def rv_send(b):
    """Одно сообщение по одному заказу. Все проверки повторяются на сервере: текст строится из шаблона, а не берётся из браузера."""
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'review-send')
        rv_verify_page(d, o, oid, 'review-send', 'просьба не отправлена')
        cfg, now = rv_load(), datetime.datetime.now()
        why = rv_blockers(o, cfg, now, rv_last_by_buyer(d))
        if why:
            conf_refuse(oid, 'review-send', 'просьба не отправлена: ' + '; '.join(why))
        try:
            text, label, promised = rv_render(cfg, o)
        except UserError as e:
            conf_refuse(oid, 'review-send', str(e))
        if len(text) > MAX_CHAT_TEXT:
            conf_refuse(oid, 'review-send', f'Готовый текст длиннее {MAX_CHAT_TEXT} символов.')
        node = rv_node(o)
        if not node:
            conf_refuse(oid, 'review-send', 'Нет ID вашего аккаунта или покупателя: войдите на вкладке «Аккаунт».')
        res = chat_send(node, text)
        if res['error_site']:
            conf_log(oid, 'review-send', f'сайт вернул ошибку, просьба НЕ отмечена отправленной (шаблон: {label}): {res["error_site"]}', ok=False)
            return {'id': oid, 'sent': False, 'error_site': res['error_site'], 'note': res['note']}
        o['review_at'], o['review_key'] = conf_iso(now.replace(microsecond=0)), label
        if promised:
            o['review_reward'] = promised           # условия награды фиксируются на момент просьбы
        conf_save(d)
        conf_log(oid, 'review-request', f'просьба об отзыве отправлена (шаблон: {label}; награда обещана: '
                 f'{("да, за " + str(promised["stars"]) + " из 5") if promised else "нет"}; {len(text)} символов). '
                 'Ответ сайта не толкуется: проверьте сообщение в диалоге')
    return {'id': oid, 'sent': True, 'error_site': '', 'note': res['note']}


def rv_skip(b):
    oid, off = conf_id(b.get('id')), b.get('off') is True
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'review-skip')
        if off:
            o.pop('review_skip', None)
        else:
            o['review_skip'] = True
        conf_save(d)
        conf_log(oid, 'review-skip', 'отметка «не просить отзыв» снята' if off else 'отметка «не просить отзыв» поставлена')
    return {'id': oid}


# ---------- оценка отзыва и выдача награды ----------
def rv_stars(b):
    """Оценка отзыва, записанная вами вручную (автоматического чтения пока нет). stars=null снимает запись."""
    oid = conf_id(b.get('id'))
    raw = b.get('stars')
    stars = None if raw in (None, '') else rv_int(raw, 1, 5, 'Оценка')
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'review-stars')
        if o['status'] != 'confirmed':
            conf_refuse(oid, 'review-stars', 'Оценку можно записать только у подтверждённого заказа.')
        if o.get('reward_at'):
            conf_refuse(oid, 'review-stars', 'Награда по заказу уже выдана, оценку менять нельзя.')
        if stars is None:
            o.pop('review_stars', None)
        else:
            o['review_stars'] = stars
            o['review_stars_src'] = 'hand'
        conf_save(d)
        conf_log(oid, 'review-stars', 'оценка отзыва снята' if stars is None else f'оценка отзыва записана вручную: {stars} из 5')
    return {'id': oid}


def rv_parse_review(html, oid, buyer=''):
    """Читает оценку отзыва со страницы заказа (блок .review-container). Ничего не угадывает.
    Возвращает {'found': bool, 'stars': int|None, 'note': str}. Берётся только строка отзыва покупателя
    (data-row="review"), строка «Ответ продавца» (data-row="reply") игнорируется."""
    soup = BeautifulSoup(html, 'html.parser')
    cont = soup.select_one('.review-container')
    if cont is None:
        return {'found': False, 'stars': None, 'note': 'Отзыва на странице заказа нет.'}
    if cont.get('data-order') and cont.get('data-order') != oid:
        return {'found': False, 'stars': None, 'note': 'Блок отзыва относится к другому заказу, не использую.'}
    row = cont.select_one('.review-item-row[data-row="review"]')
    if row is None:
        return {'found': False, 'stars': None, 'note': 'Строка отзыва покупателя не найдена: отзыва нет или разметка другая.'}
    if row.select_one('.review-empty-text') and not row.select_one('.rating'):
        return {'found': False, 'stars': None, 'note': 'Отзыва пока нет (на странице «Отсутствует»).'}
    author = str(row.get('data-author') or '')
    if buyer and author and author != str(buyer):
        return {'found': True, 'stars': None, 'note': f'Автор отзыва ({author}) не совпадает с покупателем заказа ({buyer}), оценку не беру.'}
    vals = set()
    mx = str(cont.get('data-rating-max') or '5')
    if re.fullmatch(r'[1-5]', str(cont.get('data-rating') or '')) and mx == '5':
        vals.add(int(cont['data-rating']))
    for e in row.select('.rating [class*="rating"]'):
        m = next((re.fullmatch(r'rating([1-5])', c) for c in e.get('class', []) if re.fullmatch(r'rating([1-5])', c)), None)
        if m:
            vals.add(int(m.group(1)))
    if not vals:
        return {'found': True, 'stars': None, 'note': 'Отзыв есть, но оценку разобрать не удалось (разметка другая).'}
    if len(vals) > 1:
        return {'found': True, 'stars': None, 'note': 'Оценка в разметке читается по-разному (' + ', '.join(map(str, sorted(vals))) + '), не записываю.'}
    return {'found': True, 'stars': vals.pop(), 'note': ''}


def rv_read_stars(b):
    """Один запрос страницы заказа: прочитать оценку отзыва и записать в review_stars (источник «сайт»).
    Покупатель может поменять оценку, поэтому перечитывание обновляет запись, пока награда не выдана. Ничего не отправляет."""
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'review-read')
        if o['status'] != 'confirmed':
            conf_refuse(oid, 'review-read', 'Оценку можно читать только у подтверждённого заказа.')
        if o.get('reward_at'):
            conf_refuse(oid, 'review-read', 'Награда по заказу уже выдана, оценку не перечитываю.')
        buyer = str(o.get('buyer') or '')
    _, _, html = site_request(f'/orders/{oid}/', ACC['key'])
    res = rv_parse_review(html, oid, buyer)
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'review-read')
        if o.get('reward_at'):
            conf_refuse(oid, 'review-read', 'Награда по заказу уже выдана, оценку менять нельзя.')
        old = o.get('review_stars')
        if res['stars'] is not None:
            o['review_stars'], o['review_stars_src'] = res['stars'], 'site'
            conf_save(d)
        conf_log(oid, 'review-read', (f'оценка прочитана с сайта: {res["stars"]} из 5' + (f' (было {old})' if old not in (None, res['stars']) else ''))
                 if res['stars'] is not None else 'оценка не прочитана: ' + res['note'], ok=res['stars'] is not None or not res['found'])
    return {'id': oid, 'found': res['found'], 'stars': res['stars'], 'note': res['note']}


# ---------- поиск подтверждённых заказов по коду страницы заказа ----------
# Страница /orders/ID/: в заголовке (h1) у закрытого заказа стоит метка «Закрыт», у оплаченного метки нет; блок «Закрыт» даёт время;
# в чате заказа есть уведомление «Покупатель X подтвердил…» или «Администратор X подтвердил…» (берём только то, где номер заказа наш).
RV_SCAN_MAX = 40            # страниц заказов за одно нажатие
RV_SCAN_DAYS = 14           # неотслеживаемые закрытые заказы берём, если оплачены не раньше N дней назад
FP_STATUS = {'закрыт': 'closed', 'возврат': 'refund', 'возвращены': 'refund'}


def fp_when(text, now):
    """«сегодня в 7:57 (9 часов назад)», «10 ноября в 15:14 (4 дня назад)», «вчера в 9:05» -> datetime или None."""
    m = re.match(r'\s*(сегодня|вчера|(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?)\s+в\s+(\d{1,2}):(\d{2})', (text or '').lower())
    if not m:
        return None
    try:
        if m.group(1) in ('сегодня', 'вчера'):
            day = now.date() - datetime.timedelta(days=1 if m.group(1) == 'вчера' else 0)
            return datetime.datetime(day.year, day.month, day.day, int(m.group(5)), int(m.group(6)))
        if m.group(3) not in MONTHS:
            return None
        y = int(m.group(4)) if m.group(4) else now.year
        t = datetime.datetime(y, MONTHS[m.group(3)], int(m.group(2)), int(m.group(5)), int(m.group(6)))
        return t.replace(year=y - 1) if (t > now and not m.group(4)) else t
    except ValueError:
        return None


def conf_parse_order_page(html, oid, now=None):
    """Состояние заказа по коду его страницы. Ничего не угадывает: чего не нашли, то None.
    Возвращает {'ok', 'status': paid|closed|refund|None, 'closed_at': datetime|None, 'by': 'покупатель'|'администратор'|None, 'by_name', 'why'}."""
    now = now or datetime.datetime.now()
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('h1.page-header')
    if h1 is None or oid.upper() not in h1.get_text(' ').upper():
        return {'ok': False, 'status': None, 'closed_at': None, 'by': None, 'by_name': '', 'why': 'на странице нет заголовка этого заказа (разметка другая или чужая страница)'}
    sp = h1.find('span')
    label = sp.get_text(' ', strip=True).casefold() if sp else ''
    closed_at, has_closed_block = None, False
    for h5 in soup.select('.param-item h5'):
        if h5.get_text(strip=True).casefold() == 'закрыт':
            has_closed_block = True
            st = h5.find_next(['strong', 'div'])
            closed_at = fp_when(st.get_text(' ', strip=True) if st else '', now)
            break
    if label:
        status = FP_STATUS.get(label) or next((v for k, v in FP_STATUS.items() if label.startswith(k)), None)
    else:
        status = None if has_closed_block else 'paid'
    by, by_name, refund_notice = None, '', False
    for t in soup.select('.chat-msg-text'):
        txt = re.sub(r'\s+', ' ', t.get_text(' ', strip=True))
        mr = re.search(r'вернул\w*\s+деньги\s+покупателю.*?заказ\w*\s+#(\w+)', txt, re.I)
        if mr and mr.group(1).upper() == oid.upper():
            refund_notice = True                  # «Продавец X вернул деньги покупателю Y по заказу #N»
        m = re.match(r'(Покупатель|Администратор)\s+(.+?)\s+подтвердил успешное выполнение\s+заказа\s+#(\w+)', txt)
        if m and m.group(3).upper() == oid.upper():
            by, by_name = m.group(1).lower(), m.group(2)
    if refund_notice:
        status = 'refund'                        # уведомление о возврате в чате важнее метки в заголовке
    return {'ok': True, 'status': status, 'closed_at': closed_at, 'by': by, 'by_name': by_name,
            'why': '' if status else f'метка статуса «{label or "—"}» не распознана'}


def conf_apply_probe(o, p, now):
    """Применяет разбор страницы к записи заказа. Возвращает 'confirmed'|'corrected'|'reverted'|'refunded'|'' (изменений нет)."""
    o['page_checked_at'] = conf_iso(now)
    if not p['ok'] or p['status'] is None:
        return ''
    oid, res = o['id'], ''
    if p['status'] == 'closed':
        who = (p['by'] or 'кто подтвердил, в чате не найдено') + ' (страница заказа)'
        at = conf_iso(p['closed_at'] or now)
        if o['status'] != 'confirmed':
            o['status'], o['confirmed_at'], o['confirmed_by'] = 'confirmed', at, who
            res = 'confirmed'
            conf_log(oid, 'confirm', f'по странице заказа «Закрыт» {at}: {who}' + ('; тикет уже отправлен: сообщите поддержке' if o.get('ticket_sent_at') else ''))
        elif (o.get('confirmed_by') or '') != who or (p['closed_at'] and o.get('confirmed_at') != at):
            old = o.get('confirmed_at')
            o['confirmed_at'], o['confirmed_by'] = at, who
            res = 'corrected'
            conf_log(oid, 'confirm', f'уточнено по странице заказа: закрыт {at} (было {old}), {who}')
        o['confirm_kind'] = p['by'] or ''
    elif p['status'] == 'paid' and o['status'] == 'confirmed':
        o['status'] = 'reminded' if o.get('reminder_at') else ('delivered' if o.get('delivered_at') else 'paid')
        o['confirmed_at'], o['confirmed_by'], o['confirm_kind'] = None, '', ''
        res = 'reverted'
        conf_log(oid, 'confirm', f'подтверждение снято: на странице заказа нет метки «Закрыт», заказ остаётся «{CONF_STATUS_RU[o["status"]]}»')
    elif p['status'] == 'refund' and o['status'] != 'refunded':
        o['status'] = 'refunded'
        res = 'refunded'
        conf_log(oid, 'refund', 'по странице заказа: возврат')
    return res


def rv_verify_page(d, o, oid, action, prefix):
    """Перед отправкой по подтверждённому заказу: один запрос страницы заказа и разбор по её коду (метка в заголовке и
    уведомления в чате заказа). Возврат или снятое подтверждение сразу попадают в учёт, и отправка отказывает.
    Если страницу разобрать не удалось, ничего не отправляем."""
    if o['status'] != 'confirmed':
        return                                  # другие статусы отсекают обычные проверки
    now = datetime.datetime.now().replace(microsecond=0)
    _, _, ohtml = site_request(f'/orders/{oid}/', ACC['key'])
    p = conf_parse_order_page(ohtml, oid, now)
    conf_apply_probe(o, p, now)
    conf_save(d)
    if not p['ok'] or p['status'] is None:
        conf_refuse(oid, action, f'{prefix}: страница заказа не разобрана ({p["why"]}), состояние заказа по коду страницы не подтверждено')


def rv_scan(b):
    """Находит подтверждённые заказы по коду страницы заказа (до RV_SCAN_MAX страниц за раз, по одному запросу с паузой).
    Ничего не отправляет покупателям. Заодно читает оценку отзыва с той же страницы, если она там есть."""
    now = datetime.datetime.now().replace(microsecond=0)
    pg = b.get('pages', 1) if isinstance(b, dict) else 1
    rows, _first, _used = orders_pages(now, pg if isinstance(pg, int) and 1 <= pg <= MAX_ORDER_PAGES else 1)
    if not rows or not any(r['has_status'] for r in rows):
        raise SiteStop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет.')
    page = {r['id'].upper(): r for r in rows if r['id']}
    with CONF_LOCK:
        d = conf_load()
        todo = []                                   # (приоритет, номер)
        for oid, o in d['orders'].items():
            if o['status'] == 'refunded':
                continue
            r = page.get(oid)
            checked = (o.get('page_checked_at') and 'страниц' in (o.get('confirmed_by') or '')) or False
            if o['status'] == 'confirmed':
                if not checked:
                    todo.append((0, oid))           # подтверждён без проверки по странице: проверяем первым
            elif r and r['status'] in ('closed', 'refund'):
                todo.append((1, oid))               # в списке закрыт, у нас нет: смотрим страницу
        for oid, r in page.items():
            if oid in d['orders'] or r['status'] != 'closed' or not r['buyer']:
                continue
            if r['ts'] is None or (now - r['ts']).days > RV_SCAN_DAYS:
                continue
            o = conf_new(oid, r['ts'], r['title'], r['price'] if r['price'] is not None else '', r['buyer'])
            o['untracked_added'] = True
            d['orders'][oid] = o
            conf_log(oid, 'add', 'найден на странице заказов со статусом «Закрыт» (раздел «Отзывы», поиск подтверждённых)')
            todo.append((2, oid))
        conf_save(d)
    todo.sort()
    batch, left = [oid for _p, oid in todo[:RV_SCAN_MAX]], max(0, len(todo) - RV_SCAN_MAX)
    cnt = {'checked': 0, 'confirmed': 0, 'corrected': 0, 'reverted': 0, 'refunded': 0, 'unclear': 0, 'stars': 0}
    err = None
    for oid in batch:
        try:
            _, _, ohtml = site_request(f'/orders/{oid}/', ACC['key'])
        except SiteStop as e:
            err = e
            break
        p = conf_parse_order_page(ohtml, oid, now)
        with CONF_LOCK:
            d = conf_load()
            o = d['orders'].get(oid)
            if o is None:
                continue
            res = conf_apply_probe(o, p, now)
            cnt['checked'] += 1
            if res:
                cnt[res] += 1
            elif not p['ok'] or p['status'] is None:
                cnt['unclear'] += 1
                conf_log(oid, 'confirm', 'страница заказа не разобрана: ' + p['why'], ok=False)
            if o['status'] == 'confirmed' and not o.get('reward_at'):
                rv = rv_parse_review(ohtml, oid, str(o.get('buyer') or ''))
                if rv['stars'] is not None and o.get('review_stars') != rv['stars']:
                    o['review_stars'], o['review_stars_src'] = rv['stars'], 'site'
                    cnt['stars'] += 1
                    conf_log(oid, 'review-read', f'оценка прочитана со страницы заказа при поиске: {rv["stars"]} из 5')
            conf_save(d)
    conf_log('', 'scan', f'поиск подтверждённых по страницам заказов: проверено {cnt["checked"]}, новых подтверждённых {cnt["confirmed"]}, '
             f'уточнено {cnt["corrected"]}, снято подтверждение {cnt["reverted"]}, возвратов {cnt["refunded"]}, не разобрано {cnt["unclear"]}'
             + (f'; осталось проверить {left}' if left else '') + ('; остановлено: ' + str(err)[:150] if err else ''))
    if err:
        raise err
    cnt['left'] = left
    return cnt


def rv_reward_send(b):
    """Выдача награды: одно сообщение покупателю. Только если награда обещана, оценка записана и равна нужной, награда ещё не выдавалась."""
    oid = conf_id(b.get('id'))
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'review-reward')
        rv_verify_page(d, o, oid, 'review-reward', 'награда не выдана')
        cfg = rv_load()
        why = rv_reward_blockers(o, cfg)
        if why:
            conf_refuse(oid, 'review-reward', 'награда не выдана: ' + '; '.join(why))
        snap, unreq = rv_reward_snap(o, cfg)
        key = snap['match'].casefold()
        rule = next((r for r in cfg['lots'] if r['key'].casefold() == key), None)
        if not rule or not rule['reward']['enabled']:
            conf_refuse(oid, 'review-reward', 'награда не выдана: правило на этот лот удалено или награда в нём выключена.')
        stock, items = rv_stock_load(), []
        if snap['type'] == 'stock':
            have = stock.get(key, [])
            if len(have) < snap['units']:
                conf_refuse(oid, 'review-reward', f'награда не выдана: в списке осталось {len(have)} шт., нужно {snap["units"]}. Добавьте строки в список правила.')
            items = have[:snap['units']]
            reward_text = '\n'.join(items)
        else:
            reward_text = rule['reward']['endless_text']
            if not reward_text:
                conf_refuse(oid, 'review-reward', 'награда не выдана: у бесконечной награды пустой текст.')
        text = re.sub(r'\{(\w+)\}', lambda m: {'order': '#' + oid, 'stars': str(snap['stars']), 'reward': reward_text}.get(m.group(1), m.group(0)),
                      rule['reward']['thanks'])
        if len(text) > MAX_CHAT_TEXT:
            conf_refuse(oid, 'review-reward', f'награда не выдана: готовый текст длиннее {MAX_CHAT_TEXT} символов.')
        node = rv_node(o)
        if not node:
            conf_refuse(oid, 'review-reward', 'Нет ID вашего аккаунта или покупателя: войдите на вкладке «Аккаунт».')
        res = chat_send(node, text)
        if res['error_site']:
            conf_log(oid, 'review-reward', f'сайт вернул ошибку, награда НЕ отмечена выданной, список не тронут: {res["error_site"]}', ok=False)
            return {'id': oid, 'sent': False, 'error_site': res['error_site'], 'note': res['note']}
        left = None
        if items:
            stock[key] = stock[key][len(items):]
            left = len(stock[key])
            write_json_atomic(REVIEW_STOCK, {'lots': stock})
        o['reward_at'] = conf_iso(datetime.datetime.now().replace(microsecond=0))
        o['review_reward'] = snap
        ucost = float(rule['reward'].get('unit_cost') or 0)
        o['reward_units'], o['reward_unit_cost'] = len(items), ucost
        o['reward_cost'] = round(len(items) * ucost, 2)      # цена на момент выдачи: смена цены позже историю не меняет
        conf_save(d)
        conf_log(oid, 'review-reward', ('(отзыв без просьбы) ' if unreq else '') + f'награда выдана: тип {"штучный" if snap["type"] == "stock" else "бесконечный"}, '
                 f'штук {len(items) or "—"}, оценка {snap["stars"]} из 5' + (f', осталось в списке {left}' if left is not None else '')
                 + ' (коды в журнал не пишутся). Ответ сайта не толкуется: проверьте сообщение в диалоге')
    return {'id': oid, 'sent': True, 'error_site': '', 'note': res['note']}


def rv_inspect_order(b):
    """Диагностика: открывает ОДНУ страницу заказа и сохраняет только блоки с классами review/rating/star (без чата заказа),
    чтобы по ним сделать автоматическое чтение оценки. Ничего не отправляет и не меняет."""
    oid = conf_id(b.get('id'))
    _, _, html = site_request(f'/orders/{oid}/', ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    pat, chosen, parts, names = r'review|rating|star', set(), [], set()
    for e in soup.find_all(True):
        cls = e.get('class', [])
        if not re.search(pat, ' '.join(cls), re.I) or any(id(p) in chosen for p in e.parents):
            continue
        chosen.add(id(e))
        parts.append(str(e)[:3000])
    for e in soup.find_all(True):
        for c in e.get('class', []):
            if re.search(pat, c, re.I):
                names.add(c)
    if not parts:
        raise SiteStop('На странице заказа блок отзыва не найден: отзыва ещё нет или разметка другая. Классы страницы (без текста): '
                       + class_names(soup, ('order', 'review', 'rating', 'tc-')) + '. Пришлите мне этот список.')
    os.makedirs(PAGES_OWN, exist_ok=True)
    path = os.path.join(PAGES_OWN, f'order_review_{oid}.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(redact('\n<!-- ---- -->\n'.join(parts)))
    conf_log(oid, 'review-inspect', f'сохранены блоки отзыва со страницы заказа: {os.path.basename(path)} (блоков {len(parts)}, чат не сохраняется)')
    return {'path': path, 'blocks': len(parts), 'classes': sorted(names)[:60]}


ROUTES_REVIEW = {'GET': {'/api/review/list': rv_list},
                 'POST': {'/api/review/settings': conf_call(rv_save),
                          '/api/review/skip': conf_call(rv_skip), '/api/review/stars': conf_call(rv_stars),
                          '/api/review/read-stars': need_login(lambda b: guarded(lambda: rv_read_stars(b))),
                          '/api/review/scan': need_login(lambda b: guarded(lambda: rv_scan(b))),
                          '/api/review/stock': conf_call(rv_stock_set),
                          '/api/review/send': need_login(lambda b: guarded(lambda: rv_send(b))),
                          '/api/review/reward-send': need_login(lambda b: guarded(lambda: rv_reward_send(b))),
                          '/api/review/inspect-order': need_login(lambda b: guarded(lambda: rv_inspect_order(b)))}}


# ===== 8г. Автопилот: фоновые проверки и автоотправка (версия 1.2) =========================================
# Работает, пока программа открыта и вы вошли в аккаунт (golden_key.txt подхватывается сам). Раз в every_min минут
# делает цикл; тяжёлые шаги идут реже (AP_EVERY_MIN). Всё идёт через те же функции, что и кнопки на вкладках:
# их проверки на сервере (страница заказа, лимиты, «один раз на заказ», остаток промокодов) не обходятся.
# Шаги цикла:
#   ЧТЕНИЕ (всегда, пока автопилот включён): заказы и учёт (remind_scan) -> проверка чатов -> поиск подтверждённых
#     и оценок отзывов (rv_scan) -> чтение оценки у заказов, ждущих награды -> статистика (stats_sync).
#   ОТПРАВКА (у каждого вида свой выключатель, по умолчанию ВЫКЛЮЧЕНЫ: сначала автопилот только показывает,
#     сколько сообщений готово; включаете один раз): напоминания покупателям, просьбы об отзыве, награды.
#   ТИКЕТ: текст готовится сам (tickets/ + плашка наверху), но в поддержку НЕ отправляется: адреса и поля формы
#     support.funpay.com не проверены, а в тексте стоит утверждение «услуга оказана», которое программа проверить не может.
# Страховки: не больше max_sends сообщений за цикл, пауза 20–60 с между сообщениями, просьбы и «ничьи» награды только по
# заказам не старше max_age_days; при ошибке сайта на отправке ВСЕ отправки встают на паузу до кнопки «Снять паузу»;
# при блокировке/капче сессия блокируется (guarded) и ничего не повторяется. Журнал: autopilot_log.csv (без текстов и кодов).
AP_CFG = P('autopilot_settings.json')
AP_LOG = P('autopilot_log.csv')
AP_REMIND_TEXT = ('Здравствуйте! Заказ {order} оплачен. Если всё получили и всё в порядке, '
                  'пожалуйста, подтвердите выполнение заказа. Спасибо!')
AP_DEFAULT = {'enabled': True, 'every_min': 20, 'remind': False, 'review_request': False, 'reward': False,
              'ticket_prepare': True, 'max_sends': 10, 'max_age_days': 7, 'remind_text': AP_REMIND_TEXT,
              'refund': False, 'refund_below': 4, 'refund_max_price': 50, 'raise': False}
AP_EVERY_MIN = {'chat': 120, 'rv_scan': 60, 'stats': 180, 'stars': 60}     # как часто тяжёлые шаги, минут
AP_STARS_WINDOW_DAYS, AP_STARS_MAX = 14, 10
AP_NUMS = (('every_min', 5, 1440), ('max_sends', 0, 1000), ('max_age_days', 1, 60), ('refund_below', 2, 5), ('refund_max_price', 0, 1000000))
AP_NO_LIMIT = 10 ** 9                    # max_sends = 0 означает «без ограничения числа сообщений за цикл»
AP_RETRY_WAIT = (30, 120, 300)           # автоповторы при сбое (нет связи, ответ 5xx), секунд; блокировки/капчи не повторяются
AP_STARS_HARD = 100                      # оценок за цикл (читаются порциями, каждый заказ не чаще раза в час)
AP_REFUND_MAX, AP_REFUND_DAYS = 3, 14      # возвратов за цикл; возврат только по заказам, подтверждённым не раньше N дней назад
AP = {'paused_until': None, 'pause_n': 0, 'running': False, 'started': '', 'ended': '', 'steps': [], 'ready': {}, 'sent': {}, 'paused': '', 'next': '',
      'last_run': {}, 'stars_try': {}, 'force': False}
AP_RUN_LOCK = threading.Lock()


def ap_read():
    raw, cfg = read_json(AP_CFG, {}), dict(AP_DEFAULT)
    for k in ('enabled', 'remind', 'review_request', 'reward', 'ticket_prepare', 'refund', 'raise'):
        if isinstance(raw.get(k), bool):
            cfg[k] = raw[k]
    for k, lo, hi in AP_NUMS:
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            cfg[k] = v
    t = raw.get('remind_text')
    if isinstance(t, str) and t.strip() and len(t.strip()) <= MAX_REMIND_TEXT:
        cfg['remind_text'] = t.strip()
    return cfg


def ap_log(step, text, ok=True):
    try:
        new = not os.path.exists(AP_LOG)
        with open(AP_LOG, 'a', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, delimiter=';')
            if new:
                w.writerow(['время', 'шаг', 'результат', 'ок'])
            w.writerow([datetime.datetime.now().isoformat(timespec='seconds'), step, text[:300], 'да' if ok else 'нет'])
    except OSError:
        pass


def ap_log_tail(n=40):
    try:
        with open(AP_LOG, encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f, delimiter=';'))
    except OSError:
        return []
    return [{'time': r.get('время', ''), 'step': r.get('шаг', ''), 'text': r.get('результат', ''), 'ok': r.get('ок') == 'да'}
            for r in rows[-n:][::-1]]


def ap_pause(reason, auto=True):
    """Пауза отправок после ошибки сайта. По умолчанию снимается сама (через 30, 60, 90 минут); после трёх подряд
    остаётся до кнопки «Снять паузу». Для возвратов (деньги) всегда только вручную."""
    if auto:
        AP['pause_n'] += 1
    if auto and AP['pause_n'] <= 3:
        until = datetime.datetime.now() + datetime.timedelta(minutes=30 * AP['pause_n'])
        AP['paused_until'] = until
        reason += f' Отправки возобновятся сами в {until.strftime("%H:%M")}.'
    else:
        AP['paused_until'] = None
        reason += ' Нужна проверка: нажмите «Снять паузу».'
    AP['paused'] = reason
    ap_log('пауза отправок', reason, ok=False)


def ap_transient(err):
    return bool(re.search(r'Нет связи|Неожиданный ответ HTTP 5\d\d|HTTP 408|Timeout|ConnectionError|URLError|RemoteDisconnected|IncompleteRead|SSLError', err))


def ap_until_done(name, fn, note=None, left_of=None, max_passes=30):
    """Шаг до конца: при сбое повторяет сам (AP_RETRY_WAIT), если осталась недочитанная часть, добирает её следующим проходом.
    Блокировка, капча и перенаправление не повторяются (сессию блокирует guarded). Если за проход ничего не убавилось
    дважды подряд или проходов слишком много, остаток добирается в следующем цикле, тоже сам."""
    fails, passes, prev, stalled = 0, 0, None, 0
    while True:
        ok, res = ap_step(name, fn, note)
        if not ok:
            err = str(res.get('error', ''))
            if ACC['locked'] or not ap_transient(err) or fails >= len(AP_RETRY_WAIT):
                return False, res
            w = AP_RETRY_WAIT[fails]
            fails += 1
            AP['steps'].append({'name': name, 'ok': True, 'text': f'сбой, автоповтор {fails} из {len(AP_RETRY_WAIT)} через {w} с'})
            time.sleep(w)
            continue
        fails = 0
        left = left_of(res) if left_of else 0
        if not left:
            return True, res
        passes += 1
        stalled = stalled + 1 if (prev is not None and left >= prev) else 0
        prev = left
        if passes >= max_passes or stalled >= 2:
            AP['steps'].append({'name': name, 'ok': True, 'text': f'осталось {left}, доберу в следующем цикле автоматически'})
            return True, res
        AP['steps'].append({'name': name, 'ok': True, 'text': f'осталось {left}, дочитываю'})


def ap_due(name, minutes):
    last = AP['last_run'].get(name)
    return last is None or (datetime.datetime.now() - last).total_seconds() >= minutes * 60


def ap_step(name, fn, note=None):
    """Один шаг через guarded. Возвращает (ок, результат). Итог пишется в AP['steps'] и в журнал."""
    code, res = guarded(fn)
    ok = code == 200
    text = note(res) if (ok and note) else ('готово' if ok else str(res.get('error', 'ошибка'))[:200])
    AP['steps'].append({'name': name, 'ok': ok, 'text': text})
    ap_log(name, text, ok)
    return ok, res


def ap_age_ok(o, cfg, unrequested_only=False):
    c = conf_dt(o.get('confirmed_at'))
    return c is None or (datetime.datetime.now() - c).days <= cfg['max_age_days']


# ---------- автовозврат при низкой оценке ----------
# Возврат = деньги уходят покупателю, отменить нельзя. Поэтому: выключатель refund по умолчанию выключен; оценка берётся только
# с сайта (не вручную) и перечитывается прямо перед возвратом; сумма заказа не больше refund_max_price (0 = без ограничения;
# нет суммы при ограничении = не возвращаем); по заказу одна попытка (refund_tried_at), повторно программа не пробует;
# не больше AP_REFUND_MAX за цикл. После запроса страница заказа читается снова: успех = на ней видно возврат; иначе
# отправки встают на паузу. Адрес /orders/refund и поля id, csrf_token написаны по памяти и НЕ проверены на живом сайте.
def ap_price(o):
    try:
        return float(re.sub(r'[^0-9.,]', '', str(o.get('price', ''))).replace(',', '.'))
    except ValueError:
        return None


def ap_refund_candidates(d, cfg):
    out, now = [], datetime.datetime.now()
    for oid, o in d['orders'].items():
        if o['status'] != 'confirmed' or o.get('refund_tried_at') or o.get('reward_at'):
            continue
        st = o.get('review_stars')
        if st is None or o.get('review_stars_src') != 'site' or st >= cfg['refund_below']:
            continue
        c = conf_dt(o.get('confirmed_at'))
        if c and (now - c).days > AP_REFUND_DAYS:
            continue
        lim, pr = cfg['refund_max_price'], ap_price(o)
        if lim > 0 and (pr is None or pr > lim):
            continue
        out.append(oid)
    return out


def ap_refund_one(oid, cfg):
    with CONF_LOCK:
        d = conf_load()
        o = conf_get(d, oid, 'refund-auto')
        now = datetime.datetime.now().replace(microsecond=0)
        if o['status'] != 'confirmed' or o.get('refund_tried_at'):
            conf_refuse(oid, 'refund-auto', 'возврат не сделан: заказ не «подтверждён» или попытка уже была')
        page = f'/orders/{oid}/'
        _, _, html = site_request(page, ACC['key'])
        p = conf_parse_order_page(html, oid, now)
        conf_apply_probe(o, p, now)
        if not p['ok'] or p['status'] != 'closed':
            conf_save(d)
            conf_refuse(oid, 'refund-auto', 'возврат не сделан: по странице заказа он не «Закрыт» (' + (p['why'] or str(p['status'])) + ')')
        rv = rv_parse_review(html, oid, str(o.get('buyer') or ''))
        if rv['stars'] is None:
            conf_save(d)
            conf_refuse(oid, 'refund-auto', 'возврат не сделан: оценка на странице не прочитана (' + rv['note'] + ')')
        o['review_stars'], o['review_stars_src'] = rv['stars'], 'site'
        lim, pr = cfg['refund_max_price'], ap_price(o)
        if rv['stars'] >= cfg['refund_below']:
            conf_save(d)
            conf_refuse(oid, 'refund-auto', f'возврат не нужен: оценка теперь {rv["stars"]}')
        if lim > 0 and (pr is None or pr > lim):
            conf_save(d)
            conf_refuse(oid, 'refund-auto', f'возврат не сделан: сумма {pr} больше лимита {lim} или неизвестна')
        tok = app_data(html).get('csrf-token')
        if not tok:
            conf_save(d)
            conf_refuse(oid, 'refund-auto', 'возврат не сделан: не нашёл csrf-токен')
        o['refund_tried_at'] = conf_iso(now)
        conf_save(d)                                     # попытка записана ДО запроса: двойного возврата не будет
        conf_log(oid, 'refund-auto', f'отправляю возврат: оценка {rv["stars"]} < {cfg["refund_below"]}, сумма {pr}')
        site_request('/orders/refund', ACC['key'], referer=page, data={'id': oid, 'csrf_token': tok})
        _, _, html2 = site_request(page, ACC['key'])
        p2 = conf_parse_order_page(html2, oid, now)
        if p2['ok'] and p2['status'] == 'refund':
            conf_apply_probe(o, p2, now)
            o['refund_at'], o['refund_reason'] = conf_iso(now), f'оценка {rv["stars"]} из 5'
            conf_save(d)
            conf_log(oid, 'refund-auto', f'возврат выполнен и виден на странице заказа (оценка {rv["stars"]}, сумма {pr})')
            return {'id': oid, 'sent': True, 'error_site': ''}
        conf_save(d)
        conf_log(oid, 'refund-auto', 'запрос возврата отправлен, но страница заказа возврат НЕ показывает: проверьте заказ на сайте', ok=False)
        return {'id': oid, 'sent': False, 'error_site': 'после запроса возврата страница заказа его не показывает'}



def ap_send_loop(kind, items, send, cfg):
    """items: [(ключ, функция без аргументов -> (код, тело))]. Возвращает число отправленных."""
    sent, cap = 0, cfg['max_sends'] or AP_NO_LIMIT
    for key, call in items:
        if sent >= cap or AP['paused'] or ACC['locked']:
            break
        if sent:
            time.sleep(random.uniform(20, 60))
        code, res = call()
        for w in AP_RETRY_WAIT[:2]:                    # сбой связи: две повторные попытки по этому же сообщению
            if code == 409 and not ACC['locked'] and ap_transient(str(res.get('error', ''))):
                ap_log(kind, f'сбой связи по {key}, повтор через {w} с', ok=False)
                time.sleep(w)
                code, res = call()
        if code == 200 and not res.get('error_site') and res.get('sent', True):
            sent += 1
            ap_log(kind, f'отправлено: {key}')
        elif code == 400 or (code == 409 and not ACC['locked'] and 'Ничего не отправлено' in str(res.get('error', ''))):
            ap_log(kind, f'пропущено {key}: {str(res.get("error", ""))[:200]}', ok=False)    # отказ по правилам, не авария
        elif code == 409 and ap_transient(str(res.get('error', ''))):
            ap_log(kind, 'нет связи с сайтом, остаток отправится в следующем цикле автоматически', ok=False)
            break
        else:
            why = res.get('error_site') or res.get('error') or 'ответ сайта не распознан'
            ap_pause(f'{kind}: {str(why)[:200]}. Все автоотправки остановлены.', auto=(kind != 'возврат'))
            break
    if sent:
        AP['pause_n'] = 0
    AP['sent'][kind] = AP['sent'].get(kind, 0) + sent
    return sent


AP_RAISE_NEXT = {}        # раздел -> когда можно снова (по ответу сайта «ждать»); в памяти, после перезапуска один пробный запрос


def ap_raise_step():
    """Поднимает разделы, у которых вышло время ожидания. Один запрос поднимает все ваши разделы игры (окно с галочками)."""
    now = datetime.datetime.now()
    ok, res = ap_step('Лоты аккаунта', load_offers, lambda r: f'лотов {len(r["rows"])}')
    if not ok:
        return
    nodes = []
    for r in res['rows']:
        if r['node'] and r['node'] not in nodes:
            nodes.append(r['node'])
    done, waits = 0, []
    for n in nodes:
        until = AP_RAISE_NEXT.get(n)
        if until and now < until:
            waits.append(until)
            continue
        time.sleep(random.uniform(3, 8))
        ok, r = ap_step(f'Поднятие раздела {n}', lambda n=n: raise_node(n), lambda r: r['msg'][:150])
        if not ok:
            if ACC['locked']:
                return
            AP_RAISE_NEXT[n] = now + datetime.timedelta(hours=1)    # ошибка: не чаще раза в час, ничего не повторяем
            continue
        until = now + datetime.timedelta(seconds=r['wait'] if r.get('wait') else 4 * 3600 + 60)
        for x in r.get('raised') or [n]:
            AP_RAISE_NEXT[str(x)] = until
        done += 1
    AP['ready']['raise'] = done


def ap_cycle():
    cfg = ap_read()
    AP['steps'], AP['ready'], AP['started'] = [], {}, datetime.datetime.now().isoformat(timespec='seconds')
    now = datetime.datetime.now()
    if AP['paused'] and AP['paused_until'] and now >= AP['paused_until']:
        AP['paused'], AP['paused_until'] = '', None
        ap_log('пауза отправок', 'снята автоматически, отправки возобновлены')
    if not network_ok():
        AP['steps'].append({'name': 'сеть', 'ok': False, 'text': 'нет сети, цикл пропущен (повтор в следующем цикле)'})
        return
    if not ACC['key'] and not ACC['locked'] and (ENV_KEY or os.path.exists(KEYFILE)):
        key = ENV_KEY
        if not key:
            try:
                with open(KEYFILE, encoding='utf-8') as f:
                    key = f.read().strip()
            except OSError:
                key = ''
        if key and re.fullmatch(r'[A-Za-z0-9_.=%-]+', key) and len(key) <= 200:
            ap_step('Вход по golden_key.txt', lambda: acc_login(key, False))
    if not ACC['key'] or ACC['locked']:
        AP['steps'].append({'name': 'вход', 'ok': False, 'text': 'сессия заблокирована сайтом' if ACC['locked']
                            else 'не выполнен вход: войдите на вкладке «Аккаунт» или положите golden_key.txt'})
        return
    # ---- чтение ----
    full = ap_due('orders_full', 60)                     # раз в час список заказов читается до конца (все страницы)
    pages = MAX_ORDER_PAGES if full else 1
    ok, _ = ap_until_done('Заказы и учёт', lambda: remind_scan(cfg['max_sends'] or AP_NO_LIMIT, pages),
                          lambda r: f'страниц {pages if full else 1}, заказов {r["counts"]["on_page"]}, оплачено {r["counts"]["paid"]}, покупателей для напоминания {len(REMIND["groups"])}')
    if ok and full:
        AP['last_run']['orders_full'] = now
    AP['ready']['remind'] = len(REMIND['groups']) if ok else 0
    if ACC['locked']:
        return
    if ap_due('chat', AP_EVERY_MIN['chat']):
        ok, _ = ap_until_done('Проверка чатов', lambda: conf_chat_check({'template': cfg['remind_text']}),
                              lambda r: f'покупателей {r["buyers"]}: подходят {r["ok"]}, не подходят {r["bad"]}',
                              left_of=lambda r: r.get('left', 0))
        if ok:
            AP['last_run']['chat'] = now
    if ACC['locked']:
        return
    if ap_due('rv_scan', AP_EVERY_MIN['rv_scan']):
        first_pass = [True]

        def scan_pass():
            p, first_pass[0] = (pages if first_pass[0] else 1), False
            return rv_scan({'pages': p})
        ok, _ = ap_until_done('Подтверждённые заказы и оценки', scan_pass,
                              lambda r: f'проверено {r["checked"]}, новых подтверждённых {r["confirmed"]}, оценок прочитано {r["stars"]}',
                              left_of=lambda r: r.get('left', 0))
        if ok:
            AP['last_run']['rv_scan'] = now
    if ACC['locked']:
        return
    # ---- оценки у заказов, ждущих награды ----
    rcfg = rv_load()
    d = conf_load()
    want = []
    for oid, o in d['orders'].items():
        if o['status'] != 'confirmed' or o.get('reward_at'):
            continue
        snap, unreq = rv_reward_snap(o, rcfg)
        if not snap or o.get('review_stars') == snap['stars']:
            continue
        ref = conf_dt(o.get('review_at')) or conf_dt(o.get('confirmed_at'))
        if ref and (now - ref).days > AP_STARS_WINDOW_DAYS:
            continue
        if unreq and not ap_age_ok(o, cfg):
            continue
        t = AP['stars_try'].get(oid)
        if t and (now - t).total_seconds() < AP_EVERY_MIN['stars'] * 60:
            continue
        want.append(oid)
    if cfg['refund']:                    # без награды оценка тоже нужна: читаем у подтверждённых заказов без оценки (реже)
        for oid, o in d['orders'].items():
            if o['status'] != 'confirmed' or o.get('reward_at') or o.get('refund_tried_at') or o.get('review_stars') is not None or oid in want:
                continue
            c = conf_dt(o.get('confirmed_at'))
            t = AP['stars_try'].get(oid)
            if (c and (now - c).days > AP_REFUND_DAYS) or (t and (now - t).total_seconds() < 180 * 60):
                continue
            want.append(oid)
    if want:
        got = 0
        done = 0
        for oid in want[:AP_STARS_HARD]:
            AP['stars_try'][oid] = now
            code, res = guarded(lambda oid=oid: rv_read_stars({'id': oid}))
            for w in AP_RETRY_WAIT[:2]:                     # сбой связи: повторяем этот же заказ
                if code == 409 and not ACC['locked'] and ap_transient(str(res.get('error', ''))):
                    time.sleep(w)
                    code, res = guarded(lambda oid=oid: rv_read_stars({'id': oid}))
            if code == 200:
                done += 1
                if res.get('stars') is not None:
                    got += 1
            elif code == 400:
                done += 1
            else:
                AP['stars_try'].pop(oid, None)             # не дочитан: попробуем в следующем цикле
                break
        AP['steps'].append({'name': 'Оценки для наград', 'ok': True, 'text': f'проверено заказов {done} из {len(want)}, оценок найдено {got}'
                            + ('' if done >= len(want) else '; остальные в следующем цикле')})
        ap_log('Оценки для наград', f'проверено {done} из {len(want)}, найдено {got}')
    if ACC['locked']:
        return
    # ---- что готово к отправке ----
    d, rcfg = conf_load(), rv_load()
    last = rv_last_by_buyer(d)
    req_ids, rew_ids = [], []
    for oid, o in sorted(d['orders'].items(), key=lambda kv: kv[1].get('confirmed_at') or ''):
        if o['status'] != 'confirmed':
            continue
        if not rv_blockers(o, rcfg, now, last) and ap_age_ok(o, cfg):
            req_ids.append(oid)
        snap, unreq = rv_reward_snap(o, rcfg)
        if snap and not rv_reward_blockers(o, rcfg) and (not unreq or ap_age_ok(o, cfg)):
            rew_ids.append(oid)
    AP['ready']['review_request'], AP['ready']['reward'] = len(req_ids), len(rew_ids)
    ref_ids = ap_refund_candidates(d, cfg)
    AP['ready']['refund'] = len(ref_ids)
    # ---- отправка (только включённое и только если нет паузы) ----
    if AP['paused']:
        AP['steps'].append({'name': 'Отправки', 'ok': False, 'text': 'на паузе: ' + AP['paused']})
    else:
        if cfg['refund'] and ref_ids:
            rc = dict(cfg, max_sends=min(cfg['max_sends'] or AP_NO_LIMIT, AP_REFUND_MAX))
            n = ap_send_loop('возврат', [(o, (lambda o=o: guarded(lambda: ap_refund_one(o, cfg)))) for o in ref_ids], None, rc)
            AP['steps'].append({'name': 'Возвраты', 'ok': not AP['paused'], 'text': f'выполнено {n} из {len(ref_ids)} готовых (оценка ниже {cfg["refund_below"]})'})
            if n:
                d, rcfg = conf_load(), rv_load()
                last = rv_last_by_buyer(d)
                req_ids = [o for o in req_ids if d['orders'][o]['status'] == 'confirmed']
                rew_ids = [o for o in rew_ids if d['orders'][o]['status'] == 'confirmed']
        if cfg['remind'] and REMIND['groups']:
            buyers = list(REMIND['groups'])
            n = ap_send_loop('напоминание', [(b, (lambda b=b: guarded(lambda: remind_send_one(b, cfg['remind_text'])))) for b in buyers], None, cfg)
            AP['steps'].append({'name': 'Напоминания', 'ok': not AP['paused'], 'text': f'отправлено {n} из {len(buyers)} готовых'})
        if cfg['review_request'] and req_ids and not AP['paused'] and not ACC['locked']:
            n = ap_send_loop('просьба об отзыве', [(o, (lambda o=o: guarded(lambda: rv_send({'id': o})))) for o in req_ids], None, cfg)
            AP['steps'].append({'name': 'Просьбы об отзыве', 'ok': not AP['paused'], 'text': f'отправлено {n} из {len(req_ids)} готовых'})
        if cfg['reward'] and rew_ids and not AP['paused'] and not ACC['locked']:
            n = ap_send_loop('награда', [(o, (lambda o=o: guarded(lambda: rv_reward_send({'id': o})))) for o in rew_ids], None, cfg)
            AP['steps'].append({'name': 'Награды', 'ok': not AP['paused'], 'text': f'выдано {n} из {len(rew_ids)} готовых'})
        if not (cfg['remind'] or cfg['review_request'] or cfg['reward'] or cfg['refund']):
            AP['steps'].append({'name': 'Отправки', 'ok': True, 'text': 'выключены: готово к отправке: напоминаний '
                                f'{AP["ready"]["remind"]}, просьб {AP["ready"]["review_request"]}, наград {AP["ready"]["reward"]}, возвратов {AP["ready"]["refund"]}'})
    # ---- тикет: только текст ----
    if cfg['ticket_prepare']:
        try:
            res = conf_ticket({})
            if res['ready']:
                AP['steps'].append({'name': 'Тикет', 'ok': True, 'text': f'текст подготовлен: {os.path.basename(res["file"])}, заказов {len(res["ready"])}. В поддержку не отправлен'})
                ap_log('Тикет', f'текст подготовлен, заказов {len(res["ready"])}')
        except Exception as e:
            ap_log('Тикет', f'{type(e).__name__}: {e}', ok=False)
    # ---- поднятие разделов ----
    if cfg['raise'] and not ACC['locked']:
        try:
            ap_raise_step()
        except Exception as e:
            ap_log('Поднятие', f'{type(e).__name__}: {e}', ok=False)
    # ---- статистика ----
    if ap_due('stats', AP_EVERY_MIN['stats']) and not ACC['locked']:
        ok, _ = ap_step('Статистика', lambda: stats_sync(1))
        if ok:
            AP['last_run']['stats'] = now


def ap_run_once():
    if not AP_RUN_LOCK.acquire(blocking=False):
        return False
    AP['running'] = True
    try:
        ap_cycle()
    except Exception as e:
        traceback.print_exc()
        AP['steps'].append({'name': 'ошибка цикла', 'ok': False, 'text': f'{type(e).__name__}: {e}'})
        ap_log('цикл', f'{type(e).__name__}: {e}', ok=False)
    finally:
        AP['running'] = False
        AP['ended'] = datetime.datetime.now().isoformat(timespec='seconds')
        AP_RUN_LOCK.release()
    return True


def ap_loop():
    time.sleep(float(os.environ.get('MARKET_TEST_AP_DELAY', '45')))
    nxt = datetime.datetime.now()
    while True:
        try:
            cfg = ap_read()
            if AP['force'] or (cfg['enabled'] and datetime.datetime.now() >= nxt):
                AP['force'] = False
                ap_run_once()
                nxt = datetime.datetime.now() + datetime.timedelta(minutes=cfg['every_min'])
                AP['next'] = nxt.isoformat(timespec='seconds') if cfg['enabled'] else ''
        except Exception:
            traceback.print_exc()
        time.sleep(5)


def ap_attention():
    """Что требует вашего действия (показывается плашкой на всех вкладках)."""
    out = []
    if AP['paused']:
        out.append({'kind': 'pause', 'text': 'Автоотправка на паузе: ' + AP['paused']})
    if ACC['locked']:
        out.append({'kind': 'lock', 'text': 'Сайт заблокировал сессию (блокировка или проверка). Автопилот остановлен до перезапуска.'})
    try:
        d = conf_load()
        n = sum(1 for o in d['orders'].values() if o.get('ticket_at') and not o.get('ticket_sent_at') and o['status'] not in CONF_DONE)
        if n:
            out.append({'kind': 'ticket', 'text': f'Готов тикет в поддержку по заказам: {n}. Отправьте его вручную (файлы в папке tickets) и отметьте на вкладке «Подтверждения».'})
        rcfg, stock = rv_load(), rv_stock_load()
        for r in rcfg['lots']:
            rw = r['reward']
            if rw['enabled'] and rw['type'] == 'stock' and len(stock.get(r['key'].casefold(), [])) < max(rw['units'], 1) * 3:
                out.append({'kind': 'stock', 'text': f'Заканчиваются промокоды для награды «{r["key"]}»: осталось {len(stock.get(r["key"].casefold(), []))}.'})
    except Exception:
        pass
    return out


def ap_status(_q=None):
    cfg = ap_read()
    return 200, {'cfg': cfg, 'running': AP['running'], 'started': AP['started'], 'ended': AP['ended'], 'next': AP['next'],
                 'steps': AP['steps'], 'ready': AP['ready'], 'sent': AP['sent'], 'paused': AP['paused'], 'locked': ACC['locked'],
                 'logged': bool(ACC['key']), 'attention': ap_attention(), 'log': ap_log_tail()}


def ap_settings(b):
    cfg = ap_read()
    for k in ('enabled', 'remind', 'review_request', 'reward', 'ticket_prepare', 'refund', 'raise'):
        if k in b:
            if not isinstance(b[k], bool):
                return 400, {'error': f'Поле {k}: нужно да/нет.'}
            cfg[k] = b[k]
    for k, lo, hi in AP_NUMS:
        if k in b:
            v = b[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                return 400, {'error': f'Поле {k}: число от {lo} до {hi}.'}
            cfg[k] = v
    if 'remind_text' in b:
        t = str(b['remind_text']).strip()
        if not t or len(t) > MAX_REMIND_TEXT:
            return 400, {'error': f'Текст напоминания: от 1 до {MAX_REMIND_TEXT} символов.'}
        cfg['remind_text'] = t
    write_json_atomic(AP_CFG, cfg)
    ap_log('настройки', 'изменены: ' + ', '.join(k for k in b if k != 'remind_text') + (', remind_text' if 'remind_text' in b else ''))
    return 200, {'ok': True}


def ap_run_now(_b):
    if AP['running']:
        return 409, {'error': 'Цикл уже идёт.'}
    AP['force'] = True
    return 200, {'ok': True}


def ap_resume(_b):
    AP['paused'] = ''
    ap_log('пауза отправок', 'снята пользователем')
    return 200, {'ok': True}


ROUTES_AUTOPILOT = {'GET': {'/api/autopilot/status': ap_status},
                    'POST': {'/api/autopilot/settings': ap_settings, '/api/autopilot/run': ap_run_now,
                             '/api/autopilot/resume': ap_resume}}


# ===== 9. Статистика ===================================================================================
# Ваши продажи, прибыльные и слабые лоты, позиция по цене, кандидаты на повышение цены, баланс.
# Откуда данные:
#   заказы:  /orders/trade (кнопка «Обновить заказы», по запросу на страницу списка, с паузами); копятся в
#            orders_cache.json: номер, статус, цена, название, время. Покупателей и переписку не хранит.
#   рынок:   последняя сохранённая страница категории (api_prices), новых запросов нет.
#   затраты: себестоимость каждого лота и комиссию вводит пользователь (lot_costs.json): сайт её не знает.
# Прибыль = подтверждённая выручка − комиссия − себестоимость на каждый подтверждённый заказ: это оценка. «Выручка» только по
# заказам «Закрыт»; «Оплачен» показан отдельно как ожидающий; «Возврат» не в выручке. Дата заказа = дата оплаты.
MAX_ORDER_PAGES = 20
MIN_ORDERS_7D = 3              # сколько заказов за 7 дней считается «высокой активностью»
RAISE_MAX = 1.25               # подсказка не выше +25% к текущей цене


def key40(title):
    t = re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', title or '')
    return re.sub(r'\s+', ' ', t).strip().casefold()[:40]


def order_ts(o):
    try:
        return datetime.datetime.fromisoformat(o['ts']) if o.get('ts') else None
    except ValueError:
        return None


def stats_sync(pages):
    key, now = ACC['key'], datetime.datetime.now()
    cache = read_json(ORDERS_CACHE, {'orders': {}})
    orders = cache.setdefault('orders', {})
    _, _, html = site_request('/orders/trade', key)
    used, got, new, seen_cont, val = 1, 0, 0, set(), ''
    while True:
        soup = BeautifulSoup(html, 'html.parser')
        rows = [r for r in order_items(soup, now) if r['status'] and r['id']]
        if used == 1 and not rows:
            raise SiteStop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет. Классы на странице '
                           '(без содержимого заказов): ' + class_names(soup, ('tc-', 'order')) + '. Пришлите мне этот список.')
        for r in rows:
            got += 1
            rec = {'id': r['id'], 'status': r['status'], 'price': r['price'], 'cur': r['cur'], 'title': r['title'],
                   'ts': r['ts'].isoformat(timespec='minutes') if r['ts'] else None}
            old = orders.get(r['id'])
            if not old:
                new += 1
            elif not rec['ts']:
                rec['ts'] = old.get('ts')
            orders[r['id']] = rec
        cont = soup.find('input', attrs={'name': 'continue'})
        val = cont.get('value') if cont else ''
        if used >= pages or not rows or not val or val in seen_cont:
            break
        seen_cont.add(val)
        _, _, html = site_request('/orders/trade', key, data={'continue': val}, referer='/orders/trade')
        used += 1
    cache['updated'] = now.isoformat(timespec='seconds')
    write_json_atomic(ORDERS_CACHE, cache)
    return {'pages': used, 'got': got, 'new': new, 'total': len(orders), 'more': bool(val) and used >= pages}


def stats_profile():
    _, _, html = site_request('/', ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    bal = ''
    for sel in ('.badge-balance', '.user-link-balance', '.balance'):
        e = soup.select_one(sel)
        if e and e.get_text(strip=True):
            bal = e.get_text(' ', strip=True)
            break
    return {'balance': bal, 'note': '' if bal else 'Баланс на главной странице не нашёл: разметка другая.'}


def stat_titlemap(lmap):
    """Название -> ID лота (после слияний) для заказов, у которых детали ещё не загружены. Неоднозначные названия не берём."""
    owners = collections.defaultdict(set)
    for r in sv1_lot_rows():
        for k in title_keys(r['title']):
            owners[k].add(lot_resolve(r['id'], lmap))
    return {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}


def stat_group(o, det, lmap, tmap=None):
    """Ключ лота для старой статистики: ID лота после слияний (по деталям заказа, а если их нет, по названию заказа
    среди известных лотов), иначе ключ по названию."""
    lid = str((det.get(o.get('id')) or {}).get('lot') or '')
    if not lid and tmap:
        lid = match_title(tmap, o.get('title', '')) or ''
    lid = lot_resolve(lid, lmap)
    return ('L' + lid) if lid else ('T' + key40(o.get('title', '')))


def stats_report(days):
    cache = read_json(ORDERS_CACHE, {'orders': {}})
    cfg = read_json(LOT_COSTS, {'fee': 0, 'costs': {}})
    fee = float(cfg.get('fee') or 0)
    costs = cfg.get('costs', {})
    now = datetime.datetime.now()
    since = now - datetime.timedelta(days=days) if days else None
    allo = [o for o in cache.get('orders', {}).values() if o.get('cur') == '₽' and o.get('price') is not None]
    per = [o for o in allo if order_ts(o) and (since is None or order_ts(o) >= since)]
    tot = {'closed': 0, 'paid': 0, 'refund': 0, 'rev': 0.0, 'pending': 0.0, 'refund_sum': 0.0}
    lots = {}
    w7 = now - datetime.timedelta(days=7)
    det = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {})
    lmap = lot_map()
    tmap = stat_titlemap(lmap)
    for o in per:
        tot[o['status']] += 1
        k = stat_group(o, det, lmap, tmap)
        g = lots.setdefault(k, {'key': k, 'title': '', '_t': None, '_keys': set(), 'closed': 0,
                                'paid': 0, 'refund': 0, 'rev': 0.0, 'pending': 0.0, 'n7': 0})
        if g['_t'] is None or order_ts(o) > g['_t']:               # название строки: по самому свежему заказу лота
            g['_t'] = order_ts(o)
            g['title'] = re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', o['title'])
        g['_keys'].add(key40(o['title']))
        g[o['status']] += 1
        if o['status'] == 'closed':
            tot['rev'] += o['price']
            g['rev'] += o['price']
        elif o['status'] == 'paid':
            tot['pending'] += o['price']
            g['pending'] += o['price']
        else:
            tot['refund_sum'] += o['price']
        if order_ts(o) >= w7 and o['status'] != 'refund':
            g['n7'] += 1
    rows = []
    cid = merged_costs(read_json(LOT_COSTS_ID, {}).get('costs', {}), lmap)
    for g in lots.values():
        c = costs.get(key40(g['title']))                            # себестоимость, введённая в этой таблице, по названию
        for kk in sorted(g['_keys']):
            if c in (None, '') and kk in costs:
                c = costs[kk]
        if c in (None, '') and g['key'].startswith('L'):
            c = cid.get(g['key'][1:])                               # или себестоимость по ID лота (из «Статистика v1»)
        g.pop('_t', None)
        g.pop('_keys', None)
        g['lot_id'] = g['key'][1:] if g['key'].startswith('L') else ''
        g['cost'] = c
        g['profit'] = round(g['rev'] * (1 - fee / 100) - float(c) * g['closed'], 2) if c not in (None, '') else None
        rows.append(g)
    have_cost = any(r['profit'] is not None for r in rows)
    rows.sort(key=lambda r: -(r['profit'] if (have_cost and r['profit'] is not None) else (r['rev'] if not have_cost else -1e18)))
    lead = {r['key'] for r in rows[:3] if r['closed']}
    for r in rows:
        tags = []
        if r['key'] in lead:
            tags.append('лидер')
        if r['profit'] is not None and r['profit'] <= 0 and r['closed']:
            tags.append('убыточный')
        if r['refund'] >= 2 and r['refund'] >= r['closed']:
            tags.append('много возвратов')
        r['tags'] = ', '.join(tags)
        r['rev'], r['pending'] = round(r['rev']), round(r['pending'])
    daily = []
    for i in range(13, -1, -1):
        d = (now - datetime.timedelta(days=i)).date()
        sel = [o for o in allo if order_ts(o) and order_ts(o).date() == d and o['status'] == 'closed']
        daily.append({'date': d.isoformat()[5:], 'n': len(sel), 'rev': round(sum(o['price'] for o in sel))})
    nodate = sum(1 for o in cache.get('orders', {}).values() if not o.get('ts'))
    return {'updated': cache.get('updated', ''), 'orders_total': len(cache.get('orders', {})), 'nodate': nodate,
            'fee': fee, 'days': days, 'tot': {k: (round(v) if isinstance(v, float) else v) for k, v in tot.items()},
            'lots': rows, 'daily': daily, 'have_cost': have_cost}


def stats_position():
    d = api_prices('')
    lots = d.get('lots') or []
    if not lots:
        return {'rows': [], 'note': d.get('note') or 'В расчёте цен нет ни одного лота: отметьте лоты на экране «Отметки».'}
    nick = ACC['me']['nick']
    mine = [l for l in lots if l['seller'] == nick]
    if not mine:
        return {'rows': [], 'note': f'Ваших лотов среди скриптов в расчёте нет: ник «{nick}» на странице {d.get("date") or ""} не найден '
                                    '(лоты не в категории, не прошли правила или не отмечены).'}
    prices = [l['price'] for l in lots]
    med = statistics.median(prices)
    now = datetime.datetime.now()
    cnt7, cnt30 = {}, {}
    det, lmap = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {}), lot_map()
    tmap = stat_titlemap(lmap)
    for o in read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {}).values():
        t = order_ts(o)
        if not t or o.get('status') == 'refund':
            continue
        k = stat_group(o, det, lmap, tmap)
        if t >= now - datetime.timedelta(days=30):
            cnt30[k] = cnt30.get(k, 0) + 1
        if t >= now - datetime.timedelta(days=7):
            cnt7[k] = cnt7.get(k, 0) + 1
    rows = []
    for l in sorted(mine, key=lambda x: x['price']):
        k1, k2 = 'L' + lot_resolve(str(l['id']), lmap), 'T' + key40(l['title'])    # заказы лежат в одной из двух корзин
        n7, n30 = cnt7.get(k1, 0) + cnt7.get(k2, 0), cnt30.get(k1, 0) + cnt30.get(k2, 0)
        rank = 1 + sum(1 for p in prices if p < l['price'])
        sug = None
        if n7 >= MIN_ORDERS_7D and l['price'] <= med:
            sug = round(min(max(med, l['price']), l['price'] * RAISE_MAX))
            if sug <= l['price']:
                sug = None
        rows.append({'title': l['title'], 'price': l['price'], 'rank': rank, 'of': len(prices), 'median': round(med),
                     'n7': n7, 'n30': n30, 'suggest': sug})
    return {'rows': rows, 'date': d.get('date') or '', 'note': ''}


def h_stat_report(b):
    days = b.get('days', 30)
    if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 3650:
        return 400, {'error': 'Неверный период'}
    return 200, stats_report(days)


def h_stat_cost(b):
    title, cost = str(b.get('title', '')), b.get('cost', '')
    k = key40(title)
    if not k:
        return 400, {'error': 'Пустое название лота'}
    cfg = read_json(LOT_COSTS, {'fee': 0, 'costs': {}})
    cfg.setdefault('costs', {})
    if cost in ('', None):
        cfg['costs'].pop(k, None)
    else:
        try:
            v = float(str(cost).replace(',', '.'))
        except ValueError:
            return 400, {'error': 'Себестоимость должна быть числом'}
        if not 0 <= v <= 10 ** 7:
            return 400, {'error': 'Себестоимость вне допустимых пределов'}
        cfg['costs'][k] = v
    write_json_atomic(LOT_COSTS, cfg)
    return 200, {'ok': True}


def h_stat_fee(b):
    try:
        v = float(str(b.get('fee', '')).replace(',', '.'))
    except ValueError:
        return 400, {'error': 'Комиссия должна быть числом'}
    if not 0 <= v <= 50:
        return 400, {'error': 'Комиссия от 0 до 50 %'}
    cfg = read_json(LOT_COSTS, {'fee': 0, 'costs': {}})
    cfg['fee'] = v
    write_json_atomic(LOT_COSTS, cfg)
    return 200, {'ok': True}


def h_stat_sync(b):
    pages = b.get('pages', 3)
    if not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= MAX_ORDER_PAGES:
        return 400, {'error': f'Страниц от 1 до {MAX_ORDER_PAGES}'}
    return guarded(lambda: stats_sync(pages))


ROUTES_STATS = {'GET': {}, 'POST': {'/api/stat/report': h_stat_report, '/api/stat/cost': h_stat_cost, '/api/stat/fee': h_stat_fee,
                                    '/api/stat/profile': need_login(lambda b: guarded(stats_profile)),
                                    '/api/stat/position': need_login(lambda b: guarded(stats_position)),
                                    '/api/stat/sync': need_login(h_stat_sync)}}



# ===== 9б. Статистика v1: награды за отзывы, расходы, метрики по ID лота, подсказки, отчёт ===============
# Факт = взято из заказов или введено вами. Оценка = расчёт или правило. Покупатели в файлах не хранятся.
# Связка заказ -> лот: ссылка на лот на странице /orders/НОМЕР/ (по памяти, НЕ проверена; при несовпадении программа
# сохраняет страницу без токенов и ников и останавливается). Звёзды: разбор rv_parse_review (раздел 8в) и review_stars
# из confirm_orders.json. Награды, выданные в разделе 8в, берутся из confirm_orders.json (reward_cost). Здесь наград сами не выдаём.
SV1_SET = P('stats_settings.json')
REWARDS_LOG = P('rewards_log.json')
EXPENSES_LOG = P('expenses_log.json')
ORDER_DETAILS = P('order_details.json')   # заказ -> {lot, stars, t}; без покупателей
LOT_COSTS_ID = P('lot_costs_id.json')     # себестоимость по ID лота
REPORTS = P('reports')
EXPENSE_CATS = ('подписка', 'хостинг', 'поднятие', 'другое')
SV1_DEF = {'reward_units': 2, 'unit_cost': 0.25, 'window_days': 14, 'min_units': 5, 'min_reviews': 10,
           'scale_profit_order': 3.0, 'scale_orders_7d': 5, 'max_refund_pct': 10, 'raise_orders_7d': 3,
           'raise_max_pct': 25, 'lower_orders_30d': 2, 'lower_above_median_pct': 15}
SV1_LIM = {'reward_units': (1, 50), 'unit_cost': (0, 1000), 'window_days': (3, 90), 'min_units': (1, 1000),
           'min_reviews': (1, 1000), 'scale_profit_order': (0, 100000), 'scale_orders_7d': (1, 1000),
           'max_refund_pct': (0, 100), 'raise_orders_7d': (1, 1000), 'raise_max_pct': (1, 200),
           'lower_orders_30d': (0, 1000), 'lower_above_median_pct': (0, 500)}
SV1_INT = {'reward_units', 'window_days', 'min_units', 'min_reviews', 'scale_orders_7d', 'raise_orders_7d', 'lower_orders_30d'}
SV1_LABELS = {'reward_units': 'Единиц награды за отзыв (почт)', 'unit_cost': 'Цена единицы награды, ₽',
              'window_days': 'N: окно «до/после» акции, дней', 'min_units': 'M: мин. единиц в окне',
              'min_reviews': 'R: мин. отзывов для «убрать акцию»', 'scale_profit_order': 'Масштабировать: прибыль на заказ от, ₽',
              'scale_orders_7d': 'Масштабировать: заказов за 7 дн. от', 'max_refund_pct': 'Масштабировать: возвратов не больше, %',
              'raise_orders_7d': 'Поднять цену: заказов за 7 дн. от', 'raise_max_pct': 'Поднять цену: не больше +%',
              'lower_orders_30d': 'Понизить цену: заказов за 30 дн. не больше',
              'lower_above_median_pct': 'Понизить цену: цена выше медианы рынка на, %'}


def _isodate(v):
    try:
        datetime.date.fromisoformat(str(v))
        return True
    except ValueError:
        return False


def _dt(s):
    try:
        return datetime.datetime.fromisoformat(str(s)) if s else None
    except ValueError:
        return None


def sv1_settings():
    raw, s = read_json(SV1_SET, {}), dict(SV1_DEF)
    for k, (lo, hi) in SV1_LIM.items():
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            s[k] = v
    pr = raw.get('promo', {})
    s['promo'] = {str(k): v for k, v in pr.items() if is_id(k, 12) and _isodate(v)} if isinstance(pr, dict) else {}
    return s


def clean_title(t):
    return re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', t or '').strip()


def qty_of(title):
    m = re.search(r'(\d+)\s*шт', title or '', re.I)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 100000 else 1


def unit_cost_of(lid, title, cid, legacy):
    c = cid.get(lid) if lid else None
    if c is None:
        c = legacy.get(key40(title))
    try:
        return None if c in (None, '') else float(c)
    except (TypeError, ValueError):
        return None


# ---- страница заказа: ID лота и звёзды ----
def conf_orders():
    try:
        return conf_load().get('orders', {})
    except Exception:
        return {}


def norm_title(t):
    return re.sub(r'[\W_]+', '', str(t or '')).casefold()     # только буквы и цифры: эмодзи, пробелы и знаки не мешают


def match_title(title_map, desc):
    """ID лота по описанию: точное совпадение, иначе единственное название, начинающееся с описания (или наоборот)."""
    d = norm_title(desc)
    if not d or not title_map:
        return None
    if d in title_map:
        return title_map[d]
    if len(d) >= 12:
        ids = {v for k, v in title_map.items() if len(k) >= 12 and (k.startswith(d) or d.startswith(k))}
        if len(ids) == 1:
            return next(iter(ids))
    return None


def title_keys(title):
    """Ключи сопоставления лота: полное название и без хвоста «, Без подписки» (в описании заказа хвоста нет)."""
    keys = {norm_title(title)}
    if ',' in title:
        keys.add(norm_title(title.rsplit(',', 1)[0]))
    return keys


def syn_lot_id(desc):
    """Псевдо-ID лота, которого сейчас нет в профиле (снят, закончился, переименован): 9 + 10 цифр от описания.
    Настоящие ID FunPay короче, поэтому не пересекаются. Когда лот вернётся в профиль, привязка заменится на настоящую."""
    import zlib
    return '9' + str(zlib.crc32(norm_title(desc).encode('utf-8'))).zfill(10)


def order_desc(soup):
    """Краткое описание заказа со страницы (на странице заказа ссылки на лот нет, есть только раздел и описание)."""
    for p in soup.select('.param-item'):
        h = p.find('h5')
        if h is not None and h.get_text(strip=True).casefold() == 'краткое описание':
            d = p.find(['div', 'strong'])
            return re.sub(r'\s+', ' ', (d or p).get_text(' ', strip=True)).strip() if d else ''
    return ''


def parse_order_page(html, oid='', buyer='', title_map=None):
    """ID лота: ссылка /lots/offer?id= (если есть), иначе по краткому описанию совпадение с вашими лотами (title_map: описание -> ID).
    Звёзды: проверенный разбор rv_parse_review (раздел 8в)."""
    soup = BeautifulSoup(html, 'html.parser')
    lot = None
    for a in soup.find_all('a', href=True):
        m = re.search(r'/lots/offer\?id=(\d+)', a['href'])
        if m:
            lot = m.group(1)
            break
    if lot is None and title_map:
        lot = match_title(title_map, order_desc(soup))
    stars = rv_parse_review(html, oid, buyer)['stars'] if oid else None
    return lot, stars, order_desc(soup)


def save_order_diag(oid, html):
    soup = BeautifulSoup(html, 'html.parser')
    for e in soup.select('.media-user, .chat, .user-link'):
        e.decompose()
    for p in soup.select('.param-item'):                  # «Оплаченный товар» (логины, пароли, ключи) в диагностику не попадает
        h = p.find('h5')
        if h is not None and 'оплаченный товар' in h.get_text(strip=True).casefold():
            p.decompose()
    os.makedirs(PAGES_OWN, exist_ok=True)
    out = os.path.join(PAGES_OWN, f'order_{oid}.htm')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(redact(str(soup)))
    return out, class_names(soup, ('order', 'param', 'review', 'rating'))


def sv1_details(limit):
    key, now = ACC['key'], datetime.datetime.now()
    cache = read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {})
    if not cache:
        raise UserError('Кэш заказов пуст: сначала нажмите «Загрузить заказы».')
    store = read_json(ORDER_DETAILS, {'orders': {}})
    det = store.setdefault('orders', {})
    new = [k for k, o in cache.items() if o.get('status') in ('closed', 'paid', 'refund')
           and (k not in det or (not det[k].get('lot') and det[k].get('v') != 3))]   # без лота: один повтор после улучшенного сопоставления
    new.sort(key=lambda k: str(cache[k].get('ts') or ''), reverse=True)
    stale = []                                     # закрытые заказы без отзыва: отзыв мог появиться позже
    for k, d in det.items():
        o, t = cache.get(k), _dt(d.get('t'))
        if o and o.get('status') == 'closed' and d.get('lot') and d.get('stars') is None and t \
                and (now - t).total_seconds() > 86400:
            ot = order_ts(o)
            if ot and (now - ot).days < 30:
                stale.append(k)
    queue = (new + stale)[:limit]
    title_map = {}
    if queue or any(d.get('desc') and (not d.get('lot') or d.get('syn')) for d in det.values()):
        try:
            owners = collections.defaultdict(set)
            for r in load_offers()['rows']:
                for k in title_keys(r['title']):
                    owners[k].add(r['id'])
            title_map = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}   # одинаковые названия не сопоставляем
        except SiteStop:
            raise
        except Exception:
            title_map = {}
    done = linked = with_stars = 0
    rematched = 0
    syn_n = 0
    for k, d in det.items():                       # уже сохранённое описание: привязываем без запроса к сайту
        if d.get('desc') and (not d.get('lot') or d.get('syn')):
            lid = match_title(title_map, d['desc']) if title_map else None
            if lid:
                d['lot'], d['syn'], rematched = lid, False, rematched + 1
            elif not d.get('lot') and len(norm_title(d['desc'])) >= 8:
                d['lot'], d['syn'], syn_n = syn_lot_id(d['desc']), True, syn_n + 1
    try:
        for oid in queue:
            if not re.fullmatch(r'[A-Za-z0-9]{1,20}', oid):
                continue
            _, _, html = site_request(f'/orders/{oid}/', key)
            lot, stars, desc = parse_order_page(html, oid, str(conf_orders().get(oid, {}).get('buyer') or ''), title_map)
            has_desc = bool(desc)
            if not has_desc and lot is None and not any(v.get('lot') for v in det.values()):
                out, cls = save_order_diag(oid, html)
                raise SiteStop(f'На странице заказа {oid} нет ни ссылки на лот, ни блока «Краткое описание»: разметка другая. Дальше не иду. '
                               f'Страница сохранена: {out} (токены, пользователи и оплаченный товар вырезаны). '
                               f'Классы на странице: {cls}. Пришлите мне файл.')
            syn = False
            if not lot and len(norm_title(desc)) >= 8:
                lot, syn = syn_lot_id(desc), True
                syn_n += 1
            det[oid] = {'lot': lot, 'syn': syn, 'stars': stars, 'v': 3, 'desc': desc[:200], 't': datetime.datetime.now().isoformat(timespec='seconds')}
            done += 1
            linked += 1 if lot else 0
            with_stars += 1 if stars else 0
    finally:
        write_json_atomic(ORDER_DETAILS, store)
    return {'done': done, 'linked': linked + rematched, 'with_stars': with_stars, 'left': max(0, len(new) + len(stale) - len(queue)), 'diag': (f'Привязано по названию к лотам профиля: {rematched}; без лота в профиле получили условный номер: {syn_n}.' if syn_n or rematched else ''), 'syn': syn_n}


# ---- сбор данных ----
LOT_MERGES = P('lot_merges.json')       # {"map": {старый ID лота: ID лота, с которым объединён}}; правится в меню «Лоты и объединение»


def lot_map():
    raw = read_json(LOT_MERGES, {}).get('map', {})
    return {str(k): str(v) for k, v in (raw.items() if isinstance(raw, dict) else []) if is_id(k, 12) and is_id(v, 12)}


def lot_resolve(lid, m=None):
    """ID лота после объединений (цепочки допускаются, циклы отсекаются)."""
    m = lot_map() if m is None else m
    lid, seen = str(lid or ''), set()
    while lid in m and lid not in seen:
        seen.add(lid)
        lid = m[lid]
    return lid


def promo_for(lid, promo, m):
    """Дата акции лота; если акция стояла на старом ID, который объединён с этим лотом, берётся самая ранняя."""
    if lid in promo:
        return promo[lid]
    dates = [v for k, v in promo.items() if lot_resolve(k, m) == lid]
    return min(dates) if dates else None


def merged_costs(cid, m):
    """Себестоимость по ID с учётом слияний: своя у оставляемого лота важнее, иначе берётся от объединённого старого."""
    out = {k: v for k, v in cid.items() if lot_resolve(k, m) == k}
    for k, v in cid.items():
        r = lot_resolve(k, m)
        if r != k and r not in out:
            out[r] = v
    return out


def sv1_collect():
    cache = read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {})
    det = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {})
    conf = conf_orders()
    lmap = lot_map()
    out = []
    for oid, o in cache.items():
        if o.get('cur') != '₽' or o.get('price') is None or o.get('status') not in ('closed', 'paid', 'refund'):
            continue
        t = order_ts(o)
        if not t:
            continue
        d = det.get(oid, {})
        stars = d.get('stars') or (conf.get(oid) or {}).get('review_stars')
        out.append({'id': oid, 'status': o['status'], 'price': float(o['price']), 'title': o.get('title', ''), 'ts': t,
                    'lot': lot_resolve(d.get('lot') or '', lmap), 'stars': stars, 'has_det': oid in det or stars is not None,
                    'qty': qty_of(o.get('title', ''))})
    return out


def sv1_rewards():
    """Награды: ручной журнал + выданные кнопкой раздела 8в (confirm_orders.json: reward_at, reward_cost). Дублей по заказу нет."""
    manual = read_json(REWARDS_LOG, {}).get('items', [])
    det = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {})
    lmap = lot_map()
    seen = {str(r.get('order')) for r in manual}
    out = [dict(r, src='вручную') for r in manual]
    for oid, o in conf_orders().items():
        if not o.get('reward_at') or oid in seen:
            continue
        units = int(o.get('reward_units') or 0)
        why = ''
        cost = o.get('reward_cost')
        if cost is None:
            cost = units * float(o.get('reward_unit_cost') or 0)
        if not float(cost or 0) and units > 0:           # выдано при цене 0: считаем по текущей цене штуки в правиле (оценка)
            mk = str((o.get('review_reward') or {}).get('match') or o.get('review_key') or '').casefold()
            rule = next((r for r in rv_load()['lots'] if r['key'].casefold() == mk), None)
            price = float(rule['reward'].get('unit_cost') or 0) if rule else 0.0
            cost = units * price
            why = f'правило «{mk[:30]}» не найдено' if rule is None else ('в правиле цена 0' if not price else '')
        out.append({'order': oid, 'lot': lot_resolve((det.get(oid) or {}).get('lot') or '', lmap), 'stars': o.get('review_stars') or 0,
                    'units': units, 'cost': round(float(cost), 2), 'date': str(o['reward_at'])[:10], 'src': 'программа',
                    'why': why, 'endless': (o.get('review_reward') or {}).get('type') == 'endless' or (units == 0 and not why)})
    return out


def sv1_expenses():
    return read_json(EXPENSES_LOG, {}).get('items', [])


def sv1_promo(lid, since_s, orders, rewards, st, fee, unit, now):
    """Окупаемость акции по формуле «Бизнесс»: Д = Е_после − Е_до, Б = Д × П, З = сумма наград, Р = Б − З."""
    N, M = st['window_days'], st['min_units']
    s0 = datetime.datetime.fromisoformat(since_s + 'T00:00:00')
    a0, a1 = s0 - datetime.timedelta(days=N), s0 + datetime.timedelta(days=N)
    mine = [o for o in orders if o['lot'] == lid and o['status'] != 'refund']
    eb = sum(o['qty'] for o in mine if a0 <= o['ts'] < s0)
    ea = sum(o['qty'] for o in mine if s0 <= o['ts'] < a1)
    res = {'since': since_s, 'N': N, 'E_before': eb, 'E_after': ea, 'verdict': '', 'why': '', 'remove': False}
    if now < a1:
        res.update(verdict='мало данных', why=f'окно после включения акции закончится {a1:%d.%m.%Y}')
        return res
    if unit is None:
        res.update(verdict='нет себестоимости', why='введите себестоимость лота')
        return res
    win = [o for o in mine if a0 <= o['ts'] < a1]
    units = sum(o['qty'] for o in win)
    if not units:
        res.update(verdict='мало данных', why='нет заказов в окне')
        return res
    pu = sum(o['price'] for o in win) / units
    P = pu * (1 - fee / 100) - unit
    if P <= 0:
        res.update(verdict='П ≤ 0', why=f'прибыль с единицы до наград {P:.2f} ₽: расчёт невозможен')
        return res
    rw = [r for r in rewards if r.get('lot') == lid and since_s <= str(r.get('date')) < a1.date().isoformat()]
    Z = sum(float(r.get('cost') or 0) for r in rw)
    H = st['reward_units'] * st['unit_cost']
    D = ea - eb
    R = D * P - Z
    revs = sum(1 for o in orders if o['lot'] == lid and o['status'] == 'closed' and o['stars'] and s0 <= o['ts'] < a1)
    res.update(P=round(P, 2), H=round(H, 2), O=len(rw), Z=round(Z, 2), D=D, B=round(D * P, 2), R=round(R, 2),
               T=round(H / P, 3), reviews_after=revs)
    if eb < M or ea < M:
        res.update(verdict='мало данных', why=f'единиц до {eb}, после {ea}, нужно не меньше {M} в каждом окне')
    else:
        res['verdict'] = 'окупается' if R >= 0 else 'не окупается'
        res['remove'] = R < 0 and revs >= st['min_reviews']
    return res


def sv1_market():
    try:
        d = api_prices('')
        lots = d.get('lots') or []
    except Exception:
        lots = []
    prices = [l['price'] for l in lots]
    return ({l['id']: l for l in lots}, statistics.median(prices) if prices else None, len(prices))


def sv1_report(days):
    now, st = datetime.datetime.now(), sv1_settings()
    cfg = read_json(LOT_COSTS, {'fee': 0, 'costs': {}})
    fee, legacy = float(cfg.get('fee') or 0), cfg.get('costs', {})
    lmap = lot_map()
    cid = merged_costs(read_json(LOT_COSTS_ID, {}).get('costs', {}), lmap)
    orders, rewards, expenses = sv1_collect(), sv1_rewards(), sv1_expenses()
    since = now - datetime.timedelta(days=days)
    sd = since.date().isoformat()
    L = {}

    def lot(lid):
        return L.setdefault(lid, {'id': lid, 'title': '', '_t': None, 'closed': 0, 'paid': 0, 'refund': 0, 'units': 0,
                                  'rev': 0.0, 'refund_sum': 0.0, 'reviews': 0, 'five': 0, 'closed_det': 0, 'rw_n': 0, 'rw_cost': 0.0})
    for o in orders:
        if o['ts'] < since:
            continue
        g = lot(o['lot'])
        if not g['_t'] or o['ts'] > g['_t']:
            g['_t'], g['title'] = o['ts'], clean_title(o['title'])
        g[o['status']] += 1
        if o['status'] == 'closed':
            g['units'] += o['qty']
            g['rev'] += o['price']
            if o['has_det']:
                g['closed_det'] += 1
            if o['stars']:
                g['reviews'] += 1
                g['five'] += 1 if o['stars'] == 5 else 0
        elif o['status'] == 'refund':
            g['refund_sum'] += o['price']
    for r in rewards:
        if str(r.get('date')) >= sd:
            g = lot(str(r.get('lot') or ''))
            g['rw_n'] += 1
            g['rw_cost'] += float(r.get('cost') or 0)
    mk, med, mn = sv1_market()
    rows, tips, tot = [], [], {'rev': 0.0, 'comm': 0.0, 'cost': 0.0, 'rw': 0.0, 'refund_sum': 0.0, 'refund_n': 0, 'closed': 0}
    no_cost = 0
    for lid, g in L.items():
        if not g['title']:
            g['title'] = '(лот без заказов за период)'
        raw_title = g['title']
        if not lid:
            g['title'] = 'Заказы без ID лота (детали не загружены): ' + g['title']
        unit = unit_cost_of(lid, raw_title, cid, legacy)
        comm = g['rev'] * fee / 100
        cost = unit * g['units'] if unit is not None else None
        allo = g['closed'] + g['paid'] + g['refund']
        if g['closed'] and unit is None:
            no_cost += 1
        profit = (g['rev'] - comm - (cost or 0) - g['rw_cost']) if (unit is not None or not g['closed']) else None
        row = dict(g, title=g['title'], comm=round(comm, 2), cost=None if cost is None else round(cost, 2),
                   unit_cost=unit, profit=None if profit is None else round(profit, 2),
                   profit_order=round(profit / g['closed'], 2) if profit is not None and g['closed'] else None,
                   refund_share=round(g['refund'] / allo, 4) if allo else None,
                   conv=round(g['reviews'] / g['closed_det'], 4) if g['closed_det'] else None,
                   five_share=round(g['five'] / g['reviews'], 4) if g['reviews'] else None,
                   cost_review=round(g['rw_cost'] / g['reviews'], 2) if g['reviews'] else None,
                   promo=None, rev=round(g['rev'], 2), rw_cost=round(g['rw_cost'], 2), refund_sum=round(g['refund_sum'], 2))
        row.pop('_t', None)
        for k, v in (('rev', g['rev']), ('comm', comm), ('cost', cost or 0), ('rw', g['rw_cost']), ('refund_sum', g['refund_sum'])):
            tot[k] += v
        tot['refund_n'] += g['refund']
        tot['closed'] += g['closed']
        if lid:
            since_s = promo_for(lid, st['promo'], lmap)
            pv = sv1_promo(lid, since_s, orders, rewards, st, fee, unit, now) if since_s else None
            row['promo'] = pv or {'since': ''}
            mine = [o for o in orders if o['lot'] == lid and o['status'] != 'refund']
            n7 = sum(1 for o in mine if o['ts'] >= now - datetime.timedelta(days=7))
            n30 = sum(1 for o in mine if o['ts'] >= now - datetime.timedelta(days=30))
            m = mk.get(lid)
            price = m['price'] if m else None
            rs = None if row['refund_share'] is None else row['refund_share'] * 100
            if row['profit_order'] is not None and row['profit_order'] >= st['scale_profit_order'] \
                    and n7 >= st['scale_orders_7d'] and (rs is None or rs <= st['max_refund_pct']):
                tips.append({'lot': lid, 'title': g['title'], 'action': 'масштабировать',
                             'basis': f'прибыль на заказ {row["profit_order"]} ₽ (порог {st["scale_profit_order"]}), заказов за 7 дн. {n7} '
                                      f'(порог {st["scale_orders_7d"]}), возвратов {0 if rs is None else round(rs, 1)} % (порог {st["max_refund_pct"]} %)'})
            if price is not None and med is not None:
                if price <= med and n7 >= st['raise_orders_7d']:
                    sug = round(min(med, price * (1 + st['raise_max_pct'] / 100)))
                    if sug > price:
                        tips.append({'lot': lid, 'title': g['title'], 'action': 'поднять цену',
                                     'basis': f'цена {price:g} ₽ не выше медианы рынка {med:g} ₽ ({mn} лотов), заказов за 7 дн. {n7} '
                                              f'(порог {st["raise_orders_7d"]}); ориентир до {sug} ₽ (не больше +{st["raise_max_pct"]} %)'})
                if price > med * (1 + st['lower_above_median_pct'] / 100) and n30 <= st['lower_orders_30d']:
                    tips.append({'lot': lid, 'title': g['title'], 'action': 'понизить цену',
                                 'basis': f'цена {price:g} ₽ выше медианы {med:g} ₽ больше чем на {st["lower_above_median_pct"]} %, '
                                          f'заказов за 30 дн. {n30} (порог {st["lower_orders_30d"]}); ориентир {round(med)} ₽'})
            if pv and pv.get('remove'):
                tips.append({'lot': lid, 'title': g['title'], 'action': 'убрать акцию',
                             'basis': f'Р = {pv["R"]} ₽ (прирост единиц {pv["D"]} × П {pv["P"]} − затраты на награды {pv["Z"]}), '
                                      f'отзывов в окне {pv["reviews_after"]} (порог {st["min_reviews"]}), единиц до/после {pv["E_before"]}/{pv["E_after"]}, '
                                      f'безубыточность {pv["T"]} доп. ед. на отзыв'})
        rows.append(row)
    rows.sort(key=lambda r: -(r['profit'] if r['profit'] is not None else -1e18))
    other = [e for e in expenses if str(e.get('date')) >= sd]
    by_cat = {c: round(sum(float(e['amount']) for e in other if e.get('category') == c), 2) for c in EXPENSE_CATS}
    other_sum = sum(by_cat.values())
    net = tot['rev'] - tot['comm'] - tot['cost'] - tot['rw'] - other_sum
    nolot = sum(1 for o in orders if o['ts'] >= since and not o['lot'])
    warn = []
    if no_cost:
        warn.append(f'Себестоимость не задана у лотов с закрытыми заказами: {no_cost}. В итоге они учтены как 0 ₽, прибыль завышена.')
    if nolot:
        warn.append(f'Заказов за период без ID лота: {nolot}. Нажмите «Загрузить детали заказов».')
    zr = [r for r in rewards if r.get('src') == 'программа' and not float(r.get('cost') or 0) and str(r.get('date')) >= sd]
    zr_end = [r for r in zr if r.get('endless')]
    zr = [r for r in zr if not r.get('endless')]
    if zr_end:
        warn.append(f'Наград типа «бесконечная» (ссылка или текст, штук нет): {len(zr_end)} (' + ', '.join('#' + r['order'] for r in zr_end[:5])
                    + '). Их стоимость программа не считает: если награда вам чего-то стоила, внесите сумму в «Прочие расходы».')
    if zr:
        det_txt = '; '.join(f"#{r['order']}: {r.get('units')} шт., {r.get('why') or 'цена 0'}" for r in zr[:5])
        warn.append(f'Наград, выданных кнопкой раздела «Просьба об отзыве», с нулевой стоимостью: {len(zr)} ({det_txt}). Впишите цену 1 шт. в правило награды, иначе расходы на награды занижены. [программа v{VERSION}]')
    if not rows:
        warn.append('За период заказов нет (или кэш заказов пуст: нажмите «Загрузить заказы» выше).')
    return {'days': days, 'fee': fee, 'updated': read_json(ORDERS_CACHE, {}).get('updated', ''), 'settings': st,
            'tot': {'rev': round(tot['rev'], 2), 'comm': round(tot['comm'], 2), 'cost': round(tot['cost'], 2),
                    'rw': round(tot['rw'], 2), 'other': round(other_sum, 2), 'by_cat': by_cat, 'net': round(net, 2),
                    'refund_sum': round(tot['refund_sum'], 2), 'refund_n': tot['refund_n'], 'closed': tot['closed']},
            'lots': rows, 'tips': tips, 'warnings': warn, 'market_median': med}


# ---- награды и расходы ----
def sv1_pending(st):
    cache = read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {})
    det = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {})
    done = {str(r.get('order')) for r in sv1_rewards()}
    conf = conf_orders()
    lmap = lot_map()
    out = []
    for oid, o in cache.items():
        d = det.get(oid)
        stars = (d or {}).get('stars') or (conf.get(oid) or {}).get('review_stars')
        if not d or not d.get('lot') or stars != 5 or o.get('status') != 'closed' or oid in done:
            continue
        since = promo_for(lot_resolve(d.get('lot') or '', lmap), st['promo'], lmap)
        t = order_ts(o)
        if not since or (t and t.date().isoformat() < since):
            continue
        out.append({'order': oid, 'lot': d['lot'], 'title': clean_title(o.get('title', ''))[:80],
                    'date': t.date().isoformat() if t else ''})
    out.sort(key=lambda r: r['date'], reverse=True)
    return out[:100]


def h_sv1_rewards(b):
    st = sv1_settings()
    return 200, {'items': sv1_rewards()[-100:][::-1], 'pending': sv1_pending(st), 'settings': st,
                 'total': round(sum(float(r.get('cost') or 0) for r in sv1_rewards()), 2)}


def h_sv1_reward_add(b):
    oid, st = str(b.get('order', '')).strip().lstrip('#'), sv1_settings()
    if not re.fullmatch(r'[A-Za-z0-9]{1,20}', oid):
        return 400, {'error': 'Неверный номер заказа'}
    stars, units = b.get('stars'), b.get('units', st['reward_units'])
    try:
        stars, units = int(stars), int(units)
    except (TypeError, ValueError):
        return 400, {'error': 'Звёзды и число единиц должны быть числами'}
    if not 1 <= stars <= 5 or not 1 <= units <= 50:
        return 400, {'error': 'Звёзд от 1 до 5, единиц от 1 до 50'}
    cache = read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {})
    d = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {}).get(oid)
    if oid not in cache:
        return 400, {'error': 'Заказа нет в кэше. Нажмите «Загрузить заказы».'}
    if not d or not d.get('lot'):
        return 400, {'error': 'У заказа нет ID лота. Нажмите «Загрузить детали заказов».'}
    store = read_json(REWARDS_LOG, {'items': []})
    items = store.setdefault('items', [])
    if any(str(r.get('order')) == oid for r in sv1_rewards()):
        return 400, {'error': 'Награда по этому заказу уже записана'}
    items.append({'order': oid, 'lot': lot_resolve(d['lot']), 'stars': stars, 'units': units,
                  'cost': round(units * st['unit_cost'], 2), 'date': datetime.date.today().isoformat()})
    write_json_atomic(REWARDS_LOG, store)
    return 200, {'ok': True}


def h_sv1_expense_add(b):
    date, cat, comment = str(b.get('date', '')), b.get('category'), str(b.get('comment', ''))[:200]
    if not _isodate(date) or cat not in EXPENSE_CATS:
        return 400, {'error': 'Неверная дата или категория'}
    try:
        amount = float(str(b.get('amount', '')).replace(',', '.'))
    except ValueError:
        return 400, {'error': 'Сумма должна быть числом'}
    if not 0 < amount <= 10 ** 7:
        return 400, {'error': 'Сумма вне допустимых пределов'}
    store = read_json(EXPENSES_LOG, {'items': []})
    store.setdefault('items', []).append({'date': date, 'category': cat, 'amount': round(amount, 2), 'comment': comment})
    write_json_atomic(EXPENSES_LOG, store)
    return 200, {'ok': True}


def h_sv1_expenses(b):
    items = sorted(sv1_expenses(), key=lambda e: str(e.get('date')), reverse=True)[:200]
    return 200, {'items': items, 'cats': list(EXPENSE_CATS), 'today': datetime.date.today().isoformat()}


# ---- настройки, акции, себестоимость по ID ----
def h_sv1_settings_get(b):
    return 200, {'settings': sv1_settings(), 'labels': SV1_LABELS, 'order': list(SV1_LIM)}


def h_sv1_settings_set(b):
    vals, st = b.get('values'), sv1_settings()
    if not isinstance(vals, dict):
        return 400, {'error': 'Непонятный запрос'}
    for k, v in vals.items():
        if k not in SV1_LIM:
            continue
        try:
            x = float(str(v).replace(',', '.'))
        except ValueError:
            return 400, {'error': f'«{SV1_LABELS[k]}»: нужно число'}
        lo, hi = SV1_LIM[k]
        if not lo <= x <= hi:
            return 400, {'error': f'«{SV1_LABELS[k]}»: от {lo} до {hi}'}
        st[k] = int(round(x)) if k in SV1_INT else x
    write_json_atomic(SV1_SET, st)
    return 200, {'ok': True}


def h_sv1_promo(b):
    lid, since = str(b.get('lot', '')), str(b.get('since', ''))
    if not is_id(lid, 12) or (since and not _isodate(since)):
        return 400, {'error': 'Неверный ID лота или дата'}
    st = sv1_settings()
    if since:
        st['promo'][lid] = since
    else:
        st['promo'].pop(lid, None)
    write_json_atomic(SV1_SET, st)
    return 200, {'ok': True}


def h_sv1_cost(b):
    lid, cost = str(b.get('lot', '')), b.get('cost', '')
    if not is_id(lid, 12):
        return 400, {'error': 'Неверный ID лота'}
    cfg = read_json(LOT_COSTS_ID, {'costs': {}})
    cfg.setdefault('costs', {})
    if cost in ('', None):
        cfg['costs'].pop(lid, None)
    else:
        try:
            v = float(str(cost).replace(',', '.'))
        except ValueError:
            return 400, {'error': 'Себестоимость должна быть числом'}
        if not 0 <= v <= 10 ** 7:
            return 400, {'error': 'Себестоимость вне допустимых пределов'}
        cfg['costs'][lid] = v
    write_json_atomic(LOT_COSTS_ID, cfg)
    return 200, {'ok': True}


# ---- отчёт руководителю ----
def _pc(v):
    return '—' if v is None else f'{v * 100:.1f} %'


def sv1_export(days):
    r = sv1_report(days)
    day = datetime.date.today().isoformat()
    os.makedirs(REPORTS, exist_ok=True)
    base = os.path.join(REPORTS, f'stat_{day}_{days}d')
    cols = ['лот_id', 'название', 'заказов закрыто (факт)', 'заказов оплачено, ждут (факт)', 'возвратов, шт (факт)',
            'выручка ₽ (факт)', 'возвраты ₽ (факт)', 'расходы на награды ₽ (факт)', 'наград выдано, шт (факт)',
            'отзывов со звёздами (факт)', 'себестоимость за ед. ₽ (ввод)', 'комиссия ₽ (оценка)', 'себестоимость ₽ (оценка)',
            'прибыль после всех расходов ₽ (оценка)', 'прибыль на заказ ₽ (оценка)', 'доля возвратов (оценка)',
            'конверсия в отзыв (оценка)', 'доля 5 звёзд (оценка)', 'стоимость отзыва ₽ (оценка)', 'акция с (ввод)',
            'акция: вердикт (оценка)', 'акция: Р ₽ (оценка)']
    rows = []
    for x in r['lots']:
        pv = x.get('promo') or {}
        rows.append({'лот_id': x['id'] or '(нет ID)', 'название': x['title'], 'заказов закрыто (факт)': x['closed'],
                     'заказов оплачено, ждут (факт)': x['paid'], 'возвратов, шт (факт)': x['refund'],
                     'выручка ₽ (факт)': x['rev'], 'возвраты ₽ (факт)': x['refund_sum'],
                     'расходы на награды ₽ (факт)': x['rw_cost'], 'наград выдано, шт (факт)': x['rw_n'],
                     'отзывов со звёздами (факт)': x['reviews'], 'себестоимость за ед. ₽ (ввод)': x['unit_cost'],
                     'комиссия ₽ (оценка)': x['comm'], 'себестоимость ₽ (оценка)': x['cost'],
                     'прибыль после всех расходов ₽ (оценка)': x['profit'], 'прибыль на заказ ₽ (оценка)': x['profit_order'],
                     'доля возвратов (оценка)': x['refund_share'], 'конверсия в отзыв (оценка)': x['conv'],
                     'доля 5 звёзд (оценка)': x['five_share'], 'стоимость отзыва ₽ (оценка)': x['cost_review'],
                     'акция с (ввод)': pv.get('since', ''), 'акция: вердикт (оценка)': pv.get('verdict', ''),
                     'акция: Р ₽ (оценка)': pv.get('R', '')})
    write_csv(base + '.csv', cols, rows)
    t, s = r['tot'], r['settings']
    L = [f'ОТЧЁТ ПО МАГАЗИНУ за {days} дн., сформирован {day}. Заказы обновлены: {r["updated"] or "не загружались"}.', '',
         'ПО ФАКТУ (из заказов и вашего ввода):',
         f'  Выручка (только «Закрыт»): {t["rev"]} ₽, закрытых заказов {t["closed"]}',
         f'  Возвраты отдельно (в выручку не входят): {t["refund_n"]} шт., {t["refund_sum"]} ₽',
         f'  РАСХОДЫ НА НАГРАДЫ ЗА ОТЗЫВЫ (отдельно): {t["rw"]} ₽',
         '  Прочие расходы (ваш ввод): ' + ', '.join(f'{k} {v} ₽' for k, v in t['by_cat'].items()) + f'; всего {t["other"]} ₽',
         f'  Комиссия FunPay, введённая вами: {r["fee"]} %', '',
         'МОЯ ОЦЕНКА (расчёт и правила, не гарантия):',
         f'  Комиссия {t["comm"]} ₽; себестоимость {t["cost"]} ₽; награды {t["rw"]} ₽; прочие {t["other"]} ₽',
         f'  Чистая прибыль после ВСЕХ расходов: {t["net"]} ₽', '']
    if r['warnings']:
        L += ['ОГРАНИЧЕНИЯ ДАННЫХ:'] + ['  - ' + w for w in r['warnings']] + ['']
    L.append('ЛОТЫ (оценка прибыли; награды включены):')
    for x in r['lots'][:15]:
        L.append(f'  [{x["id"] or "нет ID"}] {x["title"][:50]}: заказов {x["closed"]}, выручка {x["rev"]} ₽, '
                 f'награды {x["rw_cost"]} ₽, прибыль {x["profit"] if x["profit"] is not None else "нет себестоимости"} ₽, '
                 f'на заказ {x["profit_order"] if x["profit_order"] is not None else "—"} ₽, '
                 f'отзывов {x["reviews"]}, конверсия {_pc(x["conv"])}, доля 5★ {_pc(x["five_share"])}')
    L += ['', 'ПОДСКАЗКИ (все = оценка; рост заказов может быть из-за цены, поднятия или сезона, а не акции):']
    L += [f'  - {x["action"].upper()} [{x["lot"]}] {x["title"][:40]}: {x["basis"]}' for x in r['tips']] or ['  нет']
    L += ['', f'Пороги: окно {s["window_days"]} дн., мин. единиц {s["min_units"]}, мин. отзывов {s["min_reviews"]}, '
              f'награда {s["reward_units"]} × {s["unit_cost"]} ₽.']
    text = '\n'.join(L)
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    return 200, {'csv': base + '.csv', 'txt': base + '.txt', 'text': text}


def h_sv1_report(b):
    days = b.get('days', 30)
    if days not in (7, 30, 90):
        return 400, {'error': 'Период: 7, 30 или 90 дней'}
    return 200, sv1_report(days)


def h_sv1_export(b):
    days = b.get('days', 30)
    if days not in (7, 30, 90):
        return 400, {'error': 'Период: 7, 30 или 90 дней'}
    try:
        return sv1_export(days)
    except OSError as e:
        return 500, {'error': f'не удалось записать отчёт в папку reports: {e}'}


def sv1_lot_rows():
    """Все лоты, которые программа знает по заказам (ID -> название, число заказов, последний заказ)."""
    det = read_json(ORDER_DETAILS, {'orders': {}}).get('orders', {})
    cache = read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {})
    m = lot_map()
    L = {}
    for oid, d in det.items():
        lid = str(d.get('lot') or '')
        if not lid:
            continue
        o = cache.get(oid) or {}
        t = order_ts(o) if o else None
        g = L.setdefault(lid, {'id': lid, 'title': '', 'orders': 0, 'last': None, 'syn': len(lid) >= 11})
        g['orders'] += 1
        title = (d.get('desc') or clean_title(o.get('title', '')) or '').strip()
        if t and (g['last'] is None or t > g['last']):
            g['last'] = t
            if title:
                g['title'] = title
        elif not g['title'] and title:
            g['title'] = title
    rows = []
    for g in L.values():
        rows.append({'id': g['id'], 'title': g['title'][:200] or '(название не прочитано)', 'orders': g['orders'],
                     'last': g['last'].strftime('%Y-%m-%d') if g['last'] else '', 'syn': g['syn'],
                     'into': m.get(g['id'], ''), 'src': 'заказы', 'in_profile': False})
    return rows


def h_sv1_lots(b):
    rows = sv1_lot_rows()
    rows.sort(key=lambda r: r['last'], reverse=True)
    return 200, {'lots': rows}


def h_lots_merge_list(b):
    """Список для вкладки «Слияние лотов»: лоты из заказов и, если просили и есть вход, лоты с профиля аккаунта."""
    rows, err = sv1_lot_rows(), ''
    by = {r['id']: r for r in rows}
    m = lot_map()
    if b.get('offers') is True:
        if not ACC['key']:
            err = 'Лоты аккаунта не добавлены: сначала войдите на вкладке «Аккаунт».'
        else:
            code, res = guarded(load_offers)
            if code != 200:
                err = 'Лоты аккаунта не загружены: ' + str(res.get('error', 'ошибка'))
            else:
                for r in res['rows']:
                    lid, title = str(r['id']), str(r['title']).strip()[:200]
                    if lid in by:
                        by[lid]['in_profile'] = True
                        continue
                    row = {'id': lid, 'title': title or '(без названия)', 'orders': 0, 'last': '', 'syn': False,
                           'into': m.get(lid, ''), 'src': 'профиль', 'in_profile': True}
                    rows.append(row)
                    by[lid] = row
    rows.sort(key=lambda r: (r['last'] or '', r['orders']), reverse=True)
    return 200, {'lots': rows, 'offers_error': err}


def rv_follow_merge(old_title, new_title):
    """Правила наград/текстов находят лот по фрагменту названия. После переименования новое название под правило не
    подходит, поэтому при слиянии фрагмент нового названия добавляется в то же правило. Возвращает пояснение."""
    old_t, new_t = str(old_title or '').strip(), str(new_title or '').strip()
    if not old_t or not new_t:
        return 'Названия лотов неизвестны, правила наград и текстов не менялись.'
    with CONF_LOCK:
        raw = read_json(REVIEW_CFG, {})
        rules = raw.get('lots') if isinstance(raw.get('lots'), list) else []

        def owner(t):
            low = t.casefold()
            for i, r in enumerate(rules):
                if isinstance(r, dict) and any(x.casefold() in low for x in rv_matches(r)):
                    return i
            return None
        io, inn = owner(old_t), owner(new_t)
        if io is None:
            return 'У старого лота нет правила награды или своего текста: правила не менялись.'
        if inn == io:
            return f'Новое название уже подходит под то же правило {io + 1}: менять ничего не нужно.'
        if inn is not None:
            return (f'ВНИМАНИЕ: новое название уже подходит под правило {inn + 1}, а старое под правило {io + 1}. '
                    'Правила не менялись: объедините их вручную на вкладке «Отзывы».')
        ms = rv_matches(rules[io])
        if len(ms) >= RV_MAX_MATCHES:
            return f'ВНИМАНИЕ: в правиле {io + 1} уже {RV_MAX_MATCHES} лотов, фрагмент нового названия не добавлен.'
        frag = new_t[:40].strip()
        ms.append(frag)
        rules[io]['matches'], rules[io]['match'] = ms, ms[0]
        write_json_atomic(REVIEW_CFG, raw)
        conf_log(None, 'review-settings', f'при слиянии лотов в правило {io + 1} добавлен фрагмент нового названия')
        return f'В правило {io + 1} добавлен фрагмент нового названия: «{frag}». Список промокодов и награда остались общими.'


def h_sv1_lot_merge(b):
    """Объединяет один или несколько старых лотов (froms, либо один from) в новый лот to."""
    to = str(b.get('to', ''))
    raw = b.get('froms') if isinstance(b.get('froms'), list) else [b.get('from', '')]
    froms = []
    for x in raw:
        x = str(x)
        if not is_id(x, 12):
            return 400, {'error': 'Неверный ID лота'}
        if x not in froms:
            froms.append(x)
    if not froms or len(froms) > 100 or not is_id(to, 12):
        return 400, {'error': 'Выберите старые лоты (до 100) и новый лот.'}
    m = lot_map()
    rt = lot_resolve(to, m)
    todo = []
    for x in froms:
        ra = lot_resolve(x, m)
        if ra == rt or ra in [r for _x, r in todo]:
            continue                                        # уже объединён с этим лотом или повтор
        todo.append((x, ra))
    if not todo:
        return 400, {'error': 'Эти лоты уже объединены с выбранным (или это один и тот же лот).'}
    known = {r['id']: r['title'] for r in sv1_lot_rows()}
    titles = b.get('from_titles') if isinstance(b.get('from_titles'), dict) else {}
    new_t = known.get(to) or str(b.get('to_title', ''))[:200]
    cid = read_json(LOT_COSTS_ID, {})
    costs, cost_changed, notes = cid.setdefault('costs', {}), False, []
    for x, ra in todo:
        m[ra] = rt
        if ra in costs and rt not in costs:                 # себестоимость: если у оставляемого лота её нет, берём от старого
            costs[rt], cost_changed = costs[ra], True
        old_t = known.get(x) or str(titles.get(x, ''))[:200]
        try:
            notes.append(rv_follow_merge(old_t, new_t))
        except Exception as e:
            notes.append(f'Правила наград не обновлены ({type(e).__name__}: {e}).')
    write_json_atomic(LOT_MERGES, {'map': m})
    if cost_changed:
        write_json_atomic(LOT_COSTS_ID, cid)
    uniq = list(dict.fromkeys(notes))
    note = f'Объединено лотов: {len(todo)}. ' + ' '.join(uniq)
    conf_log(None, 'lot-merge', f'лоты {", ".join(x for x, _r in todo)} объединены с {to}')
    return 200, {'ok': True, 'merged': len(todo), 'note': note}


def h_sv1_lot_unmerge(b):
    a = str(b.get('from', ''))
    m = lot_map()
    if a not in m:
        return 400, {'error': 'Этот лот ни с чем не объединён.'}
    m.pop(a)
    write_json_atomic(LOT_MERGES, {'map': m})
    return 200, {'ok': True}


def h_sv1_details(b):
    n = b.get('limit', 20)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 50:
        return 400, {'error': 'За раз от 1 до 50 заказов'}
    return guarded(lambda: sv1_details(n))


ROUTES_STATV1 = {'GET': {}, 'POST': {
    '/api/stat/v1/report': h_sv1_report, '/api/stat/v1/export': h_sv1_export,
    '/api/stat/v1/settings_get': h_sv1_settings_get, '/api/stat/v1/settings_set': h_sv1_settings_set,
    '/api/stat/v1/promo': h_sv1_promo, '/api/stat/v1/cost': h_sv1_cost,
    '/api/stat/v1/rewards': h_sv1_rewards, '/api/stat/v1/reward_add': h_sv1_reward_add,
    '/api/stat/v1/expenses': h_sv1_expenses, '/api/stat/v1/expense_add': h_sv1_expense_add,
    '/api/stat/v1/lots': h_sv1_lots, '/api/lots/merge_list': h_lots_merge_list, '/api/lots/merge': h_sv1_lot_merge, '/api/stat/v1/lot_merge': h_sv1_lot_merge, '/api/stat/v1/lot_unmerge': h_sv1_lot_unmerge,
    '/api/stat/v1/details': need_login(h_sv1_details)}}


# ===== 10. HTTP-сервер и таблица маршрутов =============================================================
# Слушает только 127.0.0.1. Страницу (ui.html) отдаёт с политикой CSP: браузер не даст ей грузить ничего снаружи
# (ни скрипты, ни шрифты, ни картинки), а fetch разрешён только на свой адрес. Каждая вкладка = один блок ROUTES_*
# в своём разделе; здесь они склеиваются. Обработчик: функция(body_или_query: dict) -> (HTTP-код, dict).
ROUTES = {'GET': {}, 'POST': {}}
for _routes in (ROUTES_DETECTOR, ROUTES_ACCOUNT, ROUTES_CHAT, ROUTES_REMIND, ROUTES_CONFIRM, ROUTES_REVIEW, ROUTES_AUTOPILOT, ROUTES_STATS, ROUTES_STATV1):
    for _method in ('GET', 'POST'):
        ROUTES[_method].update(_routes[_method])


class Server(ThreadingHTTPServer):
    allow_reuse_address = False         # на Windows иначе можно занять уже занятый порт
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'FunPayDetector/' + VERSION

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        """Облако: вход по логину и паролю (HTTP Basic, пароль из переменной APP_PASSWORD), с задержкой при ошибках."""
        if not CLOUD:
            return True
        user = os.environ.get('APP_USER', 'admin')
        pw = os.environ.get('APP_PASSWORD', '')
        try:
            raw = base64.b64decode((self.headers.get('Authorization') or '')[6:]).decode('utf-8')
            u, _, p = raw.partition(':')
            ok = hmac.compare_digest(u.encode(), user.encode()) & hmac.compare_digest(p.encode(), pw.encode())
        except Exception:
            ok = False
        if not ok:
            time.sleep(1.5)
            body = 'Нужен логин и пароль'.encode('utf-8')
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="FunPay Detector", charset="UTF-8"')
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        return ok

    def _local_ok(self):
        if CLOUD:                       # адрес любой (домен Railway), доступ защищён паролем; Origin должен совпадать с Host
            origin = self.headers.get('Origin')
            return origin is None or urlparse(origin).netloc == self.headers.get('Host', '')
        port = self.server.server_address[1]
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host', '') not in allowed:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin in {f'http://{h}' for h in allowed}

    def do_GET(self):
        if not self._auth_ok():
            return
        if not self._local_ok():
            return self._send(403, {'error': 'Недопустимый адрес'})
        u = urlparse(self.path)
        if u.path == '/':
            try:
                with open(UI_FILE, 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            except OSError:
                return self._send(500, {'error': 'Рядом с app.py не найден ui.html.'})
        fn = ROUTES['GET'].get(u.path)
        if not fn:
            return self._send(404, {'error': 'Нет такой страницы'})
        try:
            return self._send(*fn({k: v[0] for k, v in parse_qs(u.query).items()}))
        except Exception as e:                      # ошибку показываем в окне, а не молча
            traceback.print_exc()
            return self._send(500, {'error': f'Не удалось прочитать данные: {type(e).__name__}: {e}'})

    def do_POST(self):
        if not self._auth_ok():
            return
        if not self._local_ok():
            return self._send(403, {'error': 'Недопустимый адрес'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(min(n, 200000)) or b'{}')
        except ValueError:
            return self._send(400, {'error': 'Непонятный запрос'})
        if not isinstance(body, dict):
            return self._send(400, {'error': 'Непонятный запрос'})
        path = urlparse(self.path).path
        if path == '/api/quit' and CLOUD:
            return self._send(403, {'error': 'В облаке программу выключить с экрана нельзя.'})
        if path == '/api/quit':
            self._send(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        fn = ROUTES['POST'].get(path)
        if not fn:
            return self._send(404, {'error': 'Нет такого действия'})
        try:
            return self._send(*fn(body))
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {'error': f'{type(e).__name__}: {e}'})


def make_server():
    last = None
    for port in PORTS + [0]:                        # 0 = любой свободный порт, выберет система
        try:
            return Server((HOST, port), Handler)
        except OSError as e:
            last = e
    raise last


# ===== 11. Точка входа =================================================================================
def cmd_serve():
    if not os.path.exists(UI_FILE):
        print('Рядом с app.py не найден ui.html. Положите его в ту же папку.')
        return 1
    try:
        srv = make_server()
    except OSError as e:
        print(f'Не удалось занять ни один порт на этом компьютере: {e}')
        print('Закройте другие копии программы и запустите снова.')
        return 1
    port = srv.server_address[1]
    url = f'http://{HOST}:{port}/'
    if CLOUD:
        print(f'Облачный режим: порт {port}, данные в {DATA_DIR}, ключ из переменной: {"да" if ENV_KEY else "нет"}')
        if len(os.environ.get('APP_PASSWORD', '')) < 12:
            print('ВНИМАНИЕ: пароль короче 12 символов, задайте длиннее.')
    print(f'FunPay Detector {VERSION} запущен: {url}')
    if port != PORTS[0]:
        print(f'(порт {PORTS[0]} был занят, взят свободный {port})')
    if not CLOUD:
        print('Страница открыта только на этом компьютере. Не закрывайте это окно, пока работаете.')
        print('Выключить: кнопка «Выключить программу» на странице, или закройте это окно.')
    if not CLOUD and not os.environ.get('MARKET_SHELL_NO_BROWSER'):
        if not webbrowser.open(url):
            print(f'Браузер сам не открылся. Откройте вручную адрес: {url}')
    c = auto_read()
    print('Автоснимок: ' + (f"включён, пауза {c['пауза_часов']} ч, первая проверка через {int(AUTO_FIRST_DELAY)} с" if c['включено'] else 'выключен') + '. Настройки на экране «Данные».')
    threading.Thread(target=auto_loop, daemon=True).start()   # вход по ключу из переменной делает цикл автопилота
    threading.Thread(target=ap_loop, daemon=True).start()
    print('Автопилот: ' + ('включён' if ap_read()['enabled'] else 'выключен') + ', первый цикл через 45 с. Отправки сообщений включаются отдельно на вкладке «Автопилот».')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    print('Программа выключена.')
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == 'fetch':
        return cmd_fetch(argv[1:])
    if argv and argv[0] == 'parse':
        return cmd_parse(argv[1:])
    if argv and argv[0] == 'serve':
        argv = argv[1:]
    return cmd_serve()


if __name__ == '__main__':
    sys.exit(main())
