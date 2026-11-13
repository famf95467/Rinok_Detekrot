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
   9. Статистика                                            (бывш. stats_tab.py)
  10. HTTP-сервер и таблица маршрутов
  11. Точка входа: serve (по умолчанию) | fetch | parse

Запуск: «Запустить.bat» или `python app.py`. Нужны только Python 3 и beautifulsoup4.
"""
import argparse, base64, collections, csv, datetime, gzip, hashlib, json, os, random, re, secrets, shutil, socket
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
VERSION = '1.0'
HERE = os.path.dirname(os.path.abspath(__file__))


def P(*parts):
    return os.path.join(HERE, *parts)


# Данные лежат рядом с программой (имена файлов не менялись при объединении: старые данные подхватываются).
UI_FILE = P('ui.html')
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

HOST = '127.0.0.1'
PORTS = list(range(8765, 8786))         # сначала эти порты; если все заняты: любой свободный
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
}


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
    due = last + datetime.timedelta(hours=cfg['пауза_часов']) if last else None
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
    if remember:
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
    # как второй запрос браузера: game_id, node_id и node_ids[] (так же шлёт Cardinal)
    _, _, text = site_request('/lots/raise', ACC['key'],
                              data=[('game_id', str(game)), ('node_id', str(node_id)), ('node_ids[]', str(node_id))], referer=page)
    msg, modal, err = '', False, None
    try:
        j = json.loads(text)
        msg = strip_tags(j.get('msg') or '')
        err, modal = j.get('error'), bool(j.get('modal'))
        if j.get('wait'):
            msg += f" (ждать примерно {int(j['wait']) // 60} мин, до {j.get('unlock_at', '?')} UTC)"
        if modal:
            msg += ' ' + strip_tags(j['modal'])
    except (ValueError, AttributeError):
        msg = redact(text)[:300]
    return {'node': node, 'msg': re.sub(r'\s+', ' ', msg).strip()[:400], 'modal': modal, 'error': err}


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
            'keyfile': os.path.exists(KEYFILE), 'locked': ACC['locked']}


def need_login(fn):
    def wrapper(b):
        if not ACC['key']:
            return 409, {'error': 'Сначала войдите.'}
        return fn(b)
    return wrapper


def h_login(b):
    key = ''
    if b.get('use_file'):
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
    out, author, mine = [], '', False
    for it in items:
        a = it.select_one('.chat-msg-author-link')
        if a:
            author = a.get_text(' ', strip=True)
            mine = f'/users/{uid}/' in a.get('href', '')
        t = it.select_one('.chat-msg-text')
        if not t:
            continue
        d = it.select_one('.chat-msg-date')
        out.append({'author': author, 'mine': mine, 'time': (d.get('title') or d.get_text(strip=True)) if d else '',
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


def remind_scan():
    _, _, html = site_request('/orders/trade', ACC['key'])
    soup = BeautifulSoup(html, 'html.parser')
    now = datetime.datetime.now()
    rows = order_items(soup, now)
    if not rows or not any(r['has_status'] for r in rows):
        raise SiteStop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет. '
                       'Классы на странице (без содержимого заказов): ' + class_names(soup, ('tc-', 'order'))
                       + '. Пришлите мне этот список.')
    try:
        conf_sync(rows, now)                    # раздел 8б: учёт заказов (строка добавлена этапом 1)
    except Exception:
        traceback.print_exc()
    log = remind_log_read()
    cnt = {'on_page': len(rows), 'paid': 0, 'young': 0, 'no_date': 0, 'no_buyer': 0}
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
        elif n_ok >= MAX_PER_RUN:
            g['ok'], g['reason'] = False, f'лимит {MAX_PER_RUN} за раз, повторите позже'
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
            o['chat_ok'] = False
            conf_log(oid, 'chat-ok', 'отметка «чат проверен» снята')
        else:
            if o['status'] in CONF_DONE:
                conf_refuse(oid, 'chat-ok', f'Заказ уже закрыт ({CONF_STATUS_RU[o["status"]]}), отметка не нужна.')
            o['chat_ok'] = True
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
    return 200, {'hours': CONF_HOURS, 'orders': rows, 'log': conf_log_tail(one if one else None, 100),
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
                           '/api/confirm/sync': need_login(h_conf_sync)}}


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
    for o in per:
        tot[o['status']] += 1
        k = key40(o['title'])
        g = lots.setdefault(k, {'key': k, 'title': re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', o['title']), 'closed': 0,
                                'paid': 0, 'refund': 0, 'rev': 0.0, 'pending': 0.0, 'n7': 0})
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
    for g in lots.values():
        c = costs.get(g['key'])
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
    for o in read_json(ORDERS_CACHE, {'orders': {}}).get('orders', {}).values():
        t = order_ts(o)
        if not t or o.get('status') == 'refund':
            continue
        k = key40(o['title'])
        if t >= now - datetime.timedelta(days=30):
            cnt30[k] = cnt30.get(k, 0) + 1
        if t >= now - datetime.timedelta(days=7):
            cnt7[k] = cnt7.get(k, 0) + 1
    rows = []
    for l in sorted(mine, key=lambda x: x['price']):
        k = key40(l['title'])
        n7, n30 = cnt7.get(k, 0), cnt30.get(k, 0)
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



# ===== 10. HTTP-сервер и таблица маршрутов =============================================================
# Слушает только 127.0.0.1. Страницу (ui.html) отдаёт с политикой CSP: браузер не даст ей грузить ничего снаружи
# (ни скрипты, ни шрифты, ни картинки), а fetch разрешён только на свой адрес. Каждая вкладка = один блок ROUTES_*
# в своём разделе; здесь они склеиваются. Обработчик: функция(body_или_query: dict) -> (HTTP-код, dict).
ROUTES = {'GET': {}, 'POST': {}}
for _routes in (ROUTES_DETECTOR, ROUTES_ACCOUNT, ROUTES_CHAT, ROUTES_REMIND, ROUTES_CONFIRM, ROUTES_STATS):
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

    def _local_ok(self):
        port = self.server.server_address[1]
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host', '') not in allowed:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin in {f'http://{h}' for h in allowed}

    def do_GET(self):
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
    print(f'FunPay Detector {VERSION} запущен: {url}')
    if port != PORTS[0]:
        print(f'(порт {PORTS[0]} был занят, взят свободный {port})')
    print('Страница открыта только на этом компьютере. Не закрывайте это окно, пока работаете.')
    print('Выключить: кнопка «Выключить программу» на странице, или закройте это окно.')
    if not os.environ.get('MARKET_SHELL_NO_BROWSER'):
        if not webbrowser.open(url):
            print(f'Браузер сам не открылся. Откройте вручную адрес: {url}')
    c = auto_read()
    print('Автоснимок: ' + (f"включён, пауза {c['пауза_часов']} ч, первая проверка через {int(AUTO_FIRST_DELAY)} с" if c['включено'] else 'выключен') + '. Настройки на экране «Данные».')
    threading.Thread(target=auto_loop, daemon=True).start()
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
