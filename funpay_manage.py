# -*- coding: utf-8 -*-
"""Менеджер своих лотов FunPay, версия 2: чтение + правка одного лота за запуск (с подтверждением).

Команды:
  python funpay_manage.py list                      показать ваши лоты (id, раздел, название, цена, количество)
  python funpay_manage.py inspect --node N --offer ID   сохранить форму редактирования лота и показать её поля
  python funpay_manage.py edit --node N --offer ID --set price=600 [--set amount=5 ...]
        показывает «было → стало» и НИЧЕГО не отправляет. Чтобы отправить, добавьте --apply:
        тогда скрипт спросит подтверждение (нужно ввести «да»). Один лот за запуск.
        Имена полей: price, amount, auto (автовыдача: 1 или 0), title, desc, active,
        либо точное имя поля из вывода inspect. Неизвестные поля скрипт отвергает.
  python funpay_manage.py inspect-trade --node N   сохранить страницу раздела, найти кнопку «поднять» (для версии 2.1)

Данные входа: cookie golden_key. Берётся из переменной окружения FUNPAY_GOLDEN_KEY или из файла
golden_key.txt рядом со скриптом. В консоль и в логи ключ не выводится. Никому его не отправляйте:
он даёт полный доступ к аккаунту. Файл golden_key.txt не копируйте, не пересылайте и не выкладывайте.

Ограничения (сделаны намеренно):
  не больше 4 запросов за запуск (правка лота = 3), паузы между ними, один повтор только при обрыве сети;
  при капче, 403, 429, редиректе на вход скрипт останавливается и ничего не повторяет и не обходит;
  страницы чатов и заказов скрипт не открывает и переписку не читает и не хранит;
  отправка только после --apply и вашего «да»; в логе пишутся имена изменённых полей, значения не пишутся;
  в сохранённых HTML вырезаны csrf-токен и данные приложения.
Адреса /users/ID/ и /lots/offerEdit написаны по памяти и НЕ проверены на живом сайте.
Если что-то не нашлось, скрипт скажет об этом, а не будет угадывать.

Только Python 3 и beautifulsoup4 (как в parse_category.py).
"""
import argparse, csv, datetime, gzip, json, os, random, re, sys, time
import urllib.error, urllib.parse, urllib.request
from urllib.parse import urlparse
from bs4 import BeautifulSoup

BASE = 'https://funpay.com'
USER_AGENT = os.environ.get('FUNPAY_USER_AGENT', 'MarketDetector/1.0 (own account, read-only)')
MAX_REQUESTS = 4
PACE = (8, 15)          # пауза между запросами, секунд (окно ставит свою)
BLOCK = {401, 403, 407, 429, 451, 503} | set(range(520, 530))
CAPTCHA = r'captcha|cf-chl|just a moment|attention required|ddos-guard|проверка браузера|вы не робот'
HERE = os.path.dirname(os.path.abspath(__file__))
sent = 0


class Stop(Exception):
    pass


def load_key():
    key = os.environ.get('FUNPAY_GOLDEN_KEY', '').strip()
    path = os.path.join(HERE, 'golden_key.txt')
    if not key and os.path.exists(path):
        key = open(path, encoding='utf-8').read().strip()
    if not key:
        sys.exit('Нет golden_key. Положите его в golden_key.txt рядом со скриптом или в FUNPAY_GOLDEN_KEY.')
    return key


def log(path, status):
    f = os.path.join(HERE, 'manage_log.csv')
    new = not os.path.exists(f)
    with open(f, 'a', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh, delimiter=';')
        if new:
            w.writerow(['время', 'путь', 'статус'])
        w.writerow([datetime.datetime.now().isoformat(timespec='seconds'), path, status])


JAR = {}


def request(path, key, data=None, referer=None):
    """GET, а при data POST. Шлёт golden_key и сессионную cookie PHPSESSID (если сайт её выдал).
    Возвращает (статус, итоговый путь, текст)."""
    global sent
    if sent >= MAX_REQUESTS:
        raise Stop('Лимит запросов за запуск исчерпан.')
    if sent:
        time.sleep(random.uniform(*PACE))
    sent += 1
    cookie = '; '.join([f'golden_key={key}'] + [f'{k}={v}' for k, v in JAR.items()])
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,application/json;q=0.9',
               'Accept-Language': 'ru-RU,ru;q=0.9', 'Accept-Encoding': 'gzip', 'Cookie': cookie}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode('utf-8')
        headers.update({'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest', 'Origin': BASE, 'Referer': BASE + (referer or '/')})
    req = urllib.request.Request(BASE + path, data=body, headers=headers)
    opener = urllib.request.build_opener()
    try:
        try:
            r = opener.open(req, timeout=30)
            status, final, hdr = r.status, r.geturl(), r.headers
        except urllib.error.HTTPError as e:
            r, status, final, hdr = e, e.code, e.geturl(), e.headers
        raw = r.read(20 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise Stop(f'Нет связи с сайтом: {type(e).__name__}. Повторите позже сами, скрипт запрос не повторяет.')
    if hdr.get('Content-Encoding', '').lower() == 'gzip':
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    for c in hdr.get_all('Set-Cookie') or []:
        m = re.match(r'\s*(PHPSESSID)=([^;]*)', c)
        if m:
            JAR[m.group(1)] = m.group(2)
    log(('POST ' if data is not None else '') + path, status)
    text = raw.decode('utf-8', 'replace')
    if status in BLOCK:
        raise Stop(f'Сайт ответил HTTP {status}: похоже на блокировку или защиту. Ничего не повторяю.')
    if status != 200:
        raise Stop(f'Неожиданный ответ HTTP {status}. Ответ: {redact(text)[:300]}')
    if re.search(CAPTCHA, text[:300000], re.I) and 'data-app-data' not in text[:5000]:
        raise Stop('Сайт показывает капчу или проверку. Скрипт её не обходит.')
    if data is None and urlparse(final).path.rstrip('/') != urlparse(path).path.rstrip('/'):
        raise Stop(f'Сайт перенаправил на {final}: вероятно, ключ недействителен или нужен вход.')
    return status, final, text


def get(path, key):
    return request(path, key)


def app_data(html):
    soup = BeautifulSoup(html, 'html.parser')
    raw = soup.body.get('data-app-data') if soup.body else None
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def redact(html):
    html = re.sub(r'data-app-data="[^"]*"', 'data-app-data="[вырезано]"', html)
    html = re.sub(r"data-app-data='[^']*'", "data-app-data='[вырезано]'", html)
    html = re.sub(r'(csrf[-_]token["\']?\s*[:=]\s*["\'])[^"\']+', r'\1[вырезано]', html, flags=re.I)
    return html


def cmd_list(a, key):
    _, _, home = get('/', key)
    uid = a.user_id or app_data(home).get('userId')
    if not uid:
        raise Stop('Не нашёл ваш ID на главной (поле userId). Запустите с --user-id ВАШ_ID (число из адреса вашего профиля).')
    _, _, prof = get(f'/users/{uid}/', key)
    soup = BeautifulSoup(prof, 'html.parser')
    rows = []
    for block in soup.select('div.offer'):
        title = block.select_one('.offer-list-title a')
        href = title.get('href', '') if title else ''
        node = (re.search(r'/lots/(\d+)/', href) or [None, ''])[1]
        section = title.get_text(' ', strip=True) if title else '?'
        for it in block.select('a.tc-item'):
            t = it.select_one('.tc-desc-text')
            p = it.select_one('.tc-price')
            am = it.select_one('.tc-amount')
            rows.append({'id': it.get('href', '').split('id=')[-1], 'раздел': section, 'node': node,
                         'название': t.get_text(' ', strip=True) if t else '',
                         'цена': p.get_text(' ', strip=True) if p else '',
                         'количество': am.get_text(strip=True) if am else ''})
    if not rows:
        raise Stop('На странице профиля лоты не найдены: разметка другая или лотов нет. Сохраните страницу вручную и пришлите мне.')
    out = os.path.join(HERE, 'my_offers.csv')
    with open(out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, list(rows[0]), delimiter=';')
        w.writeheader()
        w.writerows(rows)
    print(f'Ваших лотов найдено: {len(rows)}. Записано в {out}')
    for r in rows:
        print(f"  {r['id']:>9}  node {r['node']:>5}  {r['цена']:>10}  кол-во {r['количество']:>5}  {r['название'][:60]}")


def cmd_inspect(a, key):
    if not (a.node and a.offer):
        sys.exit('Нужны --node (номер раздела) и --offer (ID лота) из my_offers.csv.')
    _, _, html = get(f'/lots/offerEdit?node={a.node}&offer={a.offer}', key)
    os.makedirs(os.path.join(HERE, 'pages_own'), exist_ok=True)
    out = os.path.join(HERE, 'pages_own', f'offerEdit_{a.offer}.htm')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(redact(html))
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', class_=re.compile('offer|edit', re.I)) or soup.find('form')
    if not form:
        raise Stop(f'Форма редактирования не найдена. Страница сохранена: {out}. Пришлите её мне (ключ и токен вырезаны).')
    print(f'Страница сохранена: {out}\nПоля формы (значения, похожие на секреты, скрыты):')
    for el in form.find_all(['input', 'textarea', 'select']):
        name = el.get('name')
        if not name:
            continue
        typ = el.get('type') or el.name
        val = el.get('value', '') if el.name == 'input' else el.get_text(strip=True)
        if el.name == 'select':
            sel = el.find('option', selected=True)
            val = sel.get('value', '') if sel else ''
        if re.search(r'csrf|secret|token', name, re.I):
            val = '[скрыто]'
        if typ in ('checkbox', 'radio'):
            val = 'отмечено' if el.has_attr('checked') else 'не отмечено'
        print(f'  {name:<28} {typ:<9} {str(val)[:50]!r}')
    print(f'Форма отправляется на: {form.get("action", "(не указано)")}  метод: {form.get("method", "?")}')


ALIASES = {'price': r'^price$', 'amount': r'^amount$', 'auto': r'auto_?deliver', 'title': r'summary',
           'desc': r'desc', 'active': r'^active$'}
SECRET = r'secret|csrf|token'


def form_fields(form):
    """Поля формы как их увидел бы браузер: (значения, неотмеченные галочки, имена галочек)."""
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


def resolve(name, names):
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
    sys.exit(f'СТОП: поля «{name}» нет в форме лота (или оно неоднозначно). Поля формы: ' + ', '.join(sorted(names)))


def apply_sets(fields, boxes, cbs, sets):
    """Возвращает (новые значения, список изменений [(поле, было, стало)]). Ничего не отправляет."""
    new, changes = dict(fields), []
    names = set(fields) | set(boxes)
    for item in sets:
        if '=' not in item:
            sys.exit(f'СТОП: «{item}» не похоже на поле=значение.')
        name, val = item.split('=', 1)
        real = resolve(name.strip(), names)
        if real in cbs:
            on = val.strip().lower() in ('1', 'on', 'да', 'true', 'yes')
            old = 'отмечено' if real in fields else 'не отмечено'
            if on:
                new[real] = fields.get(real) or boxes.get(real, 'on')
            else:
                new.pop(real, None)
            changes.append((real, old, 'отмечено' if on else 'не отмечено'))
        else:
            if real == 'price' or real == 'amount':
                try:
                    float(val.replace(',', '.'))
                except ValueError:
                    sys.exit(f'СТОП: для {real} нужно число, а не «{val}».')
                val = val.replace(',', '.')
            changes.append((real, fields.get(real, ''), val))
            new[real] = val
    return new, [c for c in changes if c[1] != c[2]]


def mask(name, v):
    return '[скрыто]' if re.search(SECRET, name, re.I) else (v if len(v) <= 70 else v[:67] + '...')


def submit_form(key, form, html, new, page, changes):
    """Отправляет форму лота. Вызывать только после подтверждения пользователя. Возвращает (статус, ответ)."""
    action = form.get('action') or '/lots/offerSave'
    if not action.startswith('/'):
        action = urlparse(action).path or '/lots/offerSave'
    new = dict(new)
    if not any(re.search(r'csrf', n, re.I) for n in new):
        tok = app_data(html).get('csrf-token')
        if not tok:
            raise Stop('Не нашёл csrf-токен, отправка невозможна. Ничего не отправлено.')
        new['csrf_token'] = tok
    status, final, resp = request(action, key, data=new, referer=page)
    log('изменены поля: ' + ','.join(c[0] for c in changes), status)
    return status, redact(resp)[:400]


def cmd_edit(a, key):
    if not (a.node and a.offer):
        sys.exit('Нужны --node и --offer (из my_offers.csv) и хотя бы один --set поле=значение.')
    if not a.set:
        sys.exit('Нужен хотя бы один --set, например --set price=600.')
    page = f'/lots/offerEdit?node={a.node}&offer={a.offer}'
    _, _, html = request(page, key)
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', class_=re.compile('offer|edit', re.I)) or soup.find('form')
    if not form:
        raise Stop('Форма редактирования не найдена, ничего не отправляю. Запустите inspect и пришлите вывод.')
    fields, boxes, cbs = form_fields(form)
    new, changes = apply_sets(fields, boxes, cbs, a.set)
    if not changes:
        print('Изменений нет: указанные значения уже стоят в лоте. Ничего не отправляю.')
        return
    print(f'Лот {a.offer} (раздел {a.node}). Было → стало:')
    for n, old, nw in changes:
        print(f'  {n}: {mask(n, str(old))!r} → {mask(n, str(nw))!r}')
    if not a.apply:
        print('\nЭто предпросмотр, ничего не отправлено. Чтобы применить, повторите команду с --apply.')
        return
    if input('Применить эти изменения на FunPay? Введите «да»: ').strip().lower() != 'да':
        print('Отменено, ничего не отправлено.')
        return
    status, resp = submit_form(key, form, html, new, page, changes)
    print(f'Ответ сайта (HTTP {status}): {resp}')
    print('Проверьте результат на сайте или командой inspect. Ответ сайта скрипт не трактует: успех подтверждаете вы.')


def cmd_inspect_trade(a, key):
    if not a.node:
        sys.exit('Нужен --node (номер раздела из my_offers.csv).')
    _, _, html = get(f'/lots/{a.node}/trade', key)
    os.makedirs(os.path.join(HERE, 'pages_own'), exist_ok=True)
    out = os.path.join(HERE, 'pages_own', f'trade_{a.node}.htm')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(redact(html))
    soup = BeautifulSoup(html, 'html.parser')
    hits = [el for el in soup.find_all(['a', 'button']) if re.search(r'подн|raise', el.get_text(' ') + ' '.join(el.get('class', [])), re.I)]
    print(f'Страница сохранена: {out}')
    if not hits:
        print('Кнопка «поднять» не найдена в разметке. Пришлите сохранённый файл.')
    for el in hits[:5]:
        print(f'  <{el.name}> «{el.get_text(" ", strip=True)[:40]}» атрибуты: {dict((k, v) for k, v in el.attrs.items() if k != "style")}')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='FunPay: чтение своих лотов (версия 1, ничего не меняет).')
    ap.add_argument('command', choices=['list', 'inspect', 'edit', 'inspect-trade'])
    ap.add_argument('--user-id', default='')
    ap.add_argument('--node', default='')
    ap.add_argument('--offer', default='')
    ap.add_argument('--set', action='append', default=[], help='поле=значение (можно несколько раз)')
    ap.add_argument('--apply', action='store_true', help='реально отправить правку (после вашего «да»)')
    a = ap.parse_args()
    key = load_key()
    try:
        {'list': cmd_list, 'inspect': cmd_inspect, 'edit': cmd_edit, 'inspect-trade': cmd_inspect_trade}[a.command](a, key)
    except Stop as s:
        print(f'\nСТОП: {s}')
        print('Скрипт ничего не обходит. Решение принимает пользователь; сообщите «Бизнесс».')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
