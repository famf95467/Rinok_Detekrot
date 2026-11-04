# -*- coding: utf-8 -*-
"""Детектор рынка, этап 2 (версия 3.1: валюта в отчёте, счёт отметок, список лотов без отметки).
Читает ЛОКАЛЬНУЮ сохранённую страницу категории FunPay. В интернет не ходит.
Берёт только публичные данные лотов. Продажи и выручку не считает.

Запуск:  python parse_category.py страница.htm --date ГГГГ-ММ-ДД --out папка
Ручные отметки неподтверждённых лотов хранятся в marks.csv по ID лота (значения: скрипт, ниша, нет).
Один раз можно внести отметки по номерам строк из lots_unconfirmed.csv (колонка №):
  --set-script 1,2,7-11  --set-niche 33:611  --set-no 3-6  --expect-unconfirmed 36
Число после двоеточия это цена лота; если цена в этой строке другая, скрипт остановится и ничего не запишет.
Файлы на выходе:
  lots_kept.csv         оставшиеся лоты (по правилу и по ручной отметке)
  lots_unconfirmed.csv  лоты со сроком 7 дней, у которых по названию не ясно, скрипт ли это (с вашими отметками)
  lots_dropped.csv      всё отброшенное с причиной
  price_summary.csv     срезы цен по числу отзывов продавца, вариант A (все) и вариант B (без отмеченных «ниша»)
"""
import argparse, csv, os, re, statistics, sys, collections
from bs4 import BeautifulSoup

# ---- Правила фильтра (можно править здесь) ----
GAME_OK = 'gta 5'            # метка игры на FunPay; 'samp' отбрасываем
TYPE_OK = 'прочее'           # скрипты лежат в «Прочее»
CURRENCY_OK = '₽'
SAMP_WORDS = r'samp|crmp|самп|крмп'
CHEAT_WORDS = r'dlc|rage|leet|1337|просвет|wallhack|скелет|прицел|наведен|стрельба|\besp\b|\baim'
SCRIPT_WORDS = (r'скрипт|script|ahk|афк|afk|макрос|автомат|авто-?(порт|бег|перекуп|скупк|рыбалк|строй)|'
                r'включил и забыл|работает сам|свёрнут|свернут|помощник')
# Срок в названии: число + «дн/day/д/d», недели, месяцы, «навсегда», «на сутки»
NUM_DAYS = r'(?<!\d)(\d{1,3})\s*(?:дн|день|day|д\b|d\b)'
NUM_WEEKS = r'(?<!\d)(\d{1,2})\s*недел'
NUM_MONTHS = r'(?<!\d)(\d{1,2})\s*месяц'
FOREVER = r'навсегда|forever|пожизнен'
BUCKETS = [('до 50', 0, 49), ('50–500', 50, 500), ('больше 500', 501, 10 ** 9)]
STEPS = ['игра не GTA 5', 'тип не «Прочее»', 'в названии SAMP/CRMP', 'срок не указан', 'другой срок',
         'несколько сроков', 'не скрипт-автоматизация', 'не подтверждён', 'цена не в рублях', 'нет цены']
MARK_VALUES = ('скрипт', 'ниша', 'нет')


def has(p, t):
    return re.search(p, t, re.I) is not None


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
    soup = BeautifulSoup(open(path, encoding='utf-8', errors='replace').read(), 'html.parser')
    lots = []
    for a in soup.select('a.tc-item'):          # только блоки лотов; остальное на странице игнорируем
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
    """Возвращает (срок, причина_отброса или None). Порядок проверок = порядок воронки."""
    t = l['название']
    if l['игра'] != GAME_OK:
        return '', 'игра не GTA 5 (SAMP)'
    if l['тип'] != TYPE_OK:
        return '', 'тип не «Прочее»: ' + l['тип']
    if has(SAMP_WORDS, t):
        return '', 'в названии SAMP/CRMP'
    terms = find_terms(t)
    if not terms:
        return '', 'срок не указан в названии'
    if 7 not in terms:
        return '', 'другой срок: ' + ', '.join(sorted((term_label(x) for x in terms), key=lambda s: (len(s), s)))
    if len(terms) > 1:
        return '', 'несколько сроков в названии'
    if has(CHEAT_WORDS, t):
        return '7 дней', 'не скрипт-автоматизация (DLC/ESP/наведение)'
    if not has(SCRIPT_WORDS, t):
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


def write_csv(path, cols, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, cols, delimiter=';', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def read_marks(path):
    marks = {}
    if path and os.path.exists(path):
        with open(path, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f, delimiter=';'):
                if r.get('id') and r.get('отметка') in MARK_VALUES:
                    marks[r['id']] = r['отметка']
    return marks


def parse_rows(spec, label):
    """'1,2,7-11,33:611' -> {номер: цена или None}."""
    out = {}
    for tok in [t.strip() for t in (spec or '').split(',') if t.strip()]:
        price = None
        if ':' in tok:
            tok, p = tok.split(':', 1)
            price = float(p.replace(',', '.'))
        try:
            if '-' in tok:
                a, b = tok.split('-', 1)
                for n in range(int(a), int(b) + 1):
                    out[n] = price
            else:
                out[int(tok)] = price
        except ValueError:
            sys.exit(f'ОШИБКА: не понял «{tok}» в {label}. Ожидаю номера вида 1,2,7-11 или 33:611.')
    return out


def apply_set_args(args, unconfirmed, marks):
    """Переносит отметки по номерам строк в marks (ничего не пишет на диск, пока всё не проверено)."""
    groups = {'скрипт': parse_rows(args.set_script, '--set-script'),
              'ниша': parse_rows(args.set_niche, '--set-niche'),
              'нет': parse_rows(args.set_no, '--set-no')}
    if not any(groups.values()):
        return False
    if args.expect_unconfirmed is not None and args.expect_unconfirmed != len(unconfirmed):
        sys.exit(f'СТОП: ожидали {args.expect_unconfirmed} неподтверждённых лотов, а в этом запуске {len(unconfirmed)}. '
                 'Номера строк относятся к другому файлу, отметки не записаны.')
    seen = {}
    for mark, rows in groups.items():
        for n, price in rows.items():
            if not 1 <= n <= len(unconfirmed):
                sys.exit(f'СТОП: строки №{n} нет, в списке {len(unconfirmed)} лотов. Отметки не записаны.')
            if n in seen:
                sys.exit(f'СТОП: строка №{n} отмечена дважды ({seen[n]} и {mark}). Отметки не записаны.')
            seen[n] = mark
            lot = unconfirmed[n - 1]
            if price is not None and abs(lot['цена_руб'] - price) > 1.0:
                sys.exit(f'СТОП: в строке №{n} цена {lot["цена_руб"]} ₽ ({lot["продавец"]}, {lot["название"][:40]}), '
                         f'а вы указали {price}. Номера относятся к другому файлу, отметки не записаны.')
    for n, mark in seen.items():
        marks[unconfirmed[n - 1]['id']] = mark
    print(f'Внесены отметки по номерам: {len(seen)}')
    return True


def save_marks(path, marks, by_id):
    rows = [{'id': i, 'отметка': m, 'название': by_id[i]['название'][:80] if i in by_id else ''}
            for i, m in sorted(marks.items())]
    write_csv(path, ['id', 'отметка', 'название'], rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('page')
    ap.add_argument('--date', default='не указана', help='дата сохранения страницы, ГГГГ-ММ-ДД')
    ap.add_argument('--out', default='.')
    ap.add_argument('--marks', default='marks.csv', help='файл ручных отметок по ID лота')
    ap.add_argument('--set-script', default='')
    ap.add_argument('--set-niche', default='')
    ap.add_argument('--set-no', default='')
    ap.add_argument('--expect-unconfirmed', type=int, default=None)
    a = ap.parse_args()
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

    kept, dropped = [], []
    for l in lots:
        term, reason = classify(l)
        if reason is None and l['валюта'] != CURRENCY_OK:
            reason = f'цена не в рублях ({l["валюта"] or "нет значка"})'
        if reason is None and l['цена_руб'] is None:
            reason = 'нет цены'
        l['срок'] = term
        l['дата_страницы'] = a.date
        l['источник'] = 'правило'
        l['ниша'] = ''
        if reason:
            l['причина_отброса'] = reason
            dropped.append(l)
        else:
            kept.append(l)
    by_auto = collections.Counter(x['причина_отброса'] for x in dropped)   # воронка до ручных отметок
    unconfirmed = [l for l in dropped if l['причина_отброса'].startswith('не подтверждён')]
    unconfirmed.sort(key=lambda x: x['цена_руб'])      # порядок строк = порядок номеров № (устойчивая сортировка)
    for n, l in enumerate(unconfirmed, 1):
        l['№'] = n
    add_dup_flags(unconfirmed)

    marks = read_marks(a.marks)
    if apply_set_args(a, unconfirmed, marks):
        save_marks(a.marks, marks, {l['id']: l for l in unconfirmed})
    promoted, rejected = [], []
    for l in unconfirmed:
        m = marks.get(l['id'], '')
        l['отметка'] = m
        if m in ('скрипт', 'ниша'):
            promoted.append(l)
        elif m == 'нет':
            rejected.append(l)
    promoted_ids = {l['id'] for l in promoted}
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
    kept_a = kept
    kept_b = [l for l in kept if not l['ниша']]
    summary = build_summary('A: все лоты', kept_a)
    if len(kept_b) != len(kept_a):
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
        print(f'Отметок в marks.csv без лота в этом списке: {stale} (лот снят или изменился).')
    if marked_script or rejected:
        print('Отмеченные лоты (проверьте номера, цены и названия):')
        for l in unconfirmed:
            if l['отметка']:
                print(f"  №{l['№']:>2} {l['отметка']:<7} {l['цена_руб']:>8} {l['валюта'] or '?'}  {l['продавец'][:14]:<14} {l['название'][:55]}")
    if unmarked:
        print('БЕЗ ОТМЕТКИ (разметьте по номеру: --set-script / --set-no и --expect-unconfirmed '
              f'{len(unconfirmed)}):')
        for l in unmarked:
            print(f"  №{l['№']:>2}  {l['цена_руб']:>8} {l['валюта'] or '?'}  {l['продавец'][:14]:<14} {l['название'][:55]}")
    print(f'ОСТАЛОСЬ: {len(kept)}  (проверка: {len(kept)} + {len(dropped)} = {len(kept) + len(dropped)} из {len(lots)})')
    if not kept and set(units) != {CURRENCY_OK}:
        print('Итог пустой из-за валюты: нужна страница с ценами в рублях.')
    d_lots = sum(1 for l in kept if l['дубль'] == 'да')
    d_groups = len({l['группа_дубля'] for l in kept if l['дубль'] == 'да'})
    print(f'Дубли «название + цена» у разных продавцов: {d_lots} лотов в {d_groups} группах')
    variants = [('A: все лоты', kept_a)] + ([('B: без лотов «ниша»', kept_b)] if len(kept_b) != len(kept_a) else [])
    for name, part in variants:
        print(f'Срезы цен, ₽, вариант {name} ({len(part)} лотов), дата страницы {a.date}:')
        for r in [x for x in summary if x['вариант'] == name]:
            print(f"  {r['срез']:<14} {r['показатель']:<38} продавцов {r['продавцов']:>2}  n={r['лотов_или_цен']:>2}  "
                  f"мин {r['мин']}  Q1 {r['Q1']}  мед {r['медиана']}  Q3 {r['Q3']}  макс {r['макс']}  {r['примечание']}")


if __name__ == '__main__':
    main()
