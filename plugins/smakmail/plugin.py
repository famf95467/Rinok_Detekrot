# -*- coding: utf-8 -*-
"""Плагин «Почты SmakMail»: выдача адреса почты покупателю и пересылка magic-link из письма (версия 1.2).

Поток: заказ оплачен -> покупателю в чат уходит адрес свободной почты и инструкция -> покупатель вводит адрес на сайте
платформы и пишет команду !ссылка -> плагин ждёт письмо по IMAP и отправляет ссылку в чат заказа.
Плагин ничего не покупает у SmakMail: ящики (адрес:пароль) вы загружаете сами. API SmakMail нужен только чтобы понять,
пуст ли ящик (свободный ящик = в нём нет писем).

Безопасность (сделано намеренно):
  - плагин по умолчанию ВЫКЛЮЧЕН; автовыдача адреса и автовыдача ссылки включаются отдельными галочками, тоже выключены;
  - работает только с заказами по лотам, которые вы отметили в настройках (пока ни один не выбран, не делает ничего);
  - заказы, найденные при первом запуске или после долгого простоя, не трогает (их можно взять вручную кнопкой);
  - на заказ один адрес и не больше N ссылок; журнал отправки пишется ДО отправки, при неясном исходе повтора нет;
  - пароли ящиков, токен SmakMail и ссылки не пишутся ни в журнал, ни в ответы API, ни в оповещения, ни в orders.json;
    ссылка живёт только в памяти до отправки в чат;
  - данные лежат в plugins_data/smakmail/ (в резервные копии не входят).
Версия 1.2: у каждого лота своё правило. Пул почт (отдельный список ящиков) и профиль текстов (инструкция, команда,
шаблон ссылки) назначаются лоту отдельно. Лотам можно назначить один и тот же пул: тогда они делят общий список почт.
Пул «main» это прежний mailboxes.txt, «стандартный» профиль это прежние тексты из настроек: без новых назначений всё работает как в 1.1.
Файлы в папке данных: mailboxes.txt (СЕКРЕТ: адрес:пароль; для других пулов mailboxes_<имя>.txt и pool_state_<имя>.json), smak_token.txt (СЕКРЕТ), pool_state.json, orders.json, settings.json,
lots_cache.json (список ваших лотов), clean_state.json, log.csv.
"""
import datetime, hashlib, json, os, re, threading, time

from mailbox_pool import Pool, PoolError, check_mailbox, EMPTY, HAS_MAIL, BAD, UNKNOWN
import magic_link_auto
from magic_link_auto import AuthError, LinkTimeout, MagicLinkError, wait_for_magic_link

PLUGIN = {'id': 'smakmail', 'name': 'Почты SmakMail', 'tab': 'Почты', 'version': '1.2',
          'description': 'Выдаёт покупателю адрес почты из вашего пула и присылает в чат ссылку для входа из письма.'}

DEFAULTS = {
    'lots': [],                    # названия выбранных лотов (список из вашего аккаунта); пусто = плагин ничего не делает
    'auto_send': False,            # сам отправлять адрес покупателю
    'auto_link': False,            # сам ждать письмо и отправлять ссылку, когда покупатель написал «готово»
    'ready_cmd': '!ссылка',        # команда покупателя (можно несколько через запятую); сообщение должно НАЧИНАТЬСЯ с неё
    'max_age_hours': 24,           # заказы старше не берутся
    'max_links': 3,                # попыток получить ссылку на заказ
    'link_timeout': 300,           # сколько секунд ждать письмо
    'link_interval': 20,           # пауза между проверками ящика (не меньше 15)
    'link_pattern': magic_link_auto.DEFAULT_PATTERN,
    'max_per_tick': 3,             # адресов за одну минутную проверку
    'ready_poll_min': 2,           # как часто смотреть чат заказа, который ждёт «готово»
    'wait_hours': 6,               # сколько ждать «готово», потом заказ помечается просроченным
    'pool_low': 5,                 # предупреждать, когда непроверенных и свободных ящиков не больше
    'address_text': ('Почта закреплена за вашим заказом #{order}.\nТовар: {item}\nПочта: {email}\n'
                     'Введите эту почту на сайте платформы и запросите письмо с подтверждением. '
                     'Когда запросите, напишите здесь команду {cmd}, и я пришлю ссылку из письма.'),
    'link_text': 'Ваша ссылка для входа: {link}\nОна одноразовая и действует недолго: откройте её сразу.',
    'nolink_text': ('Письмо пока не пришло. Проверьте, что почта введена без ошибок, запросите письмо ещё раз '
                    'и снова напишите {cmd}.'),
    'pools': ['main'],             # имена пулов почт; main = прежний mailboxes.txt
    'profiles': {},                # имя профиля -> {поле: значение} (только поля, отличающиеся от стандартных)
    'lot_rules': {},               # название лота (в нижнем регистре) -> {'pool': имя, 'profile': имя или ''}
}
PROFILE_KEYS = ('address_text', 'link_text', 'nolink_text', 'ready_cmd', 'link_pattern')
POOL_NAME_RE = re.compile(r'[\w-]{1,24}')
MAX_POOLS, MAX_PROFILES = 20, 20
TEXT_VARS = {'address_text': ('order', 'email', 'cmd', 'item'), 'link_text': ('order', 'link'), 'nolink_text': ('order', 'cmd')}
OLD_TEXTS = {    # прежние стандартные тексты (с «готово»): если они так и стоят в настройках, заменяются новыми
    'address_text': ('Здравствуйте! По заказу #{order} ваша почта: {email}\n'
                     'Введите этот адрес на сайте платформы, где нужен вход. Когда введёте, напишите здесь «готово», '
                     'и я пришлю ссылку из письма.'),
    'nolink_text': ('Письмо пока не пришло. Проверьте, что адрес введён без ошибок, запросите письмо ещё раз '
                    'и напишите «готово».'),
}
MB_LOCK = threading.RLock()                     # изменения mailboxes.txt
STATES = {'new': 'ждёт адреса', 'no_mailbox': 'нет свободных почт', 'sending_addr': 'адрес отправляется',
          'addr_sent': 'адрес отправлен, ждём «готово»', 'link_queue': 'в очереди на ссылку',
          'link_working': 'ждём письмо', 'link_sending': 'ссылка отправляется', 'link_send_failed': 'ссылку не удалось отправить',
          'link_sent': 'ссылка отправлена', 'link_limit': 'лимит ссылок исчерпан', 'link_lost': 'письмо прочитано, ссылка потеряна',
          'unclear': 'исход отправки неясен', 'failed': 'ошибка', 'expired': 'просрочен', 'skipped': 'пропущен (старый)'}
IMAP_BUDGET, IMAP_WINDOW = 100, 30 * 60        # лимит SmakMail: 120 новых подключений за 30 минут с одного IP; оставляем запас
ADDR_RETRIES = 3
SECRET_RE = re.compile(r'[^\s]{8,300}')

STATE_LOCK = threading.RLock()
LINK_BUSY = threading.Lock()                   # одна ожидающая ссылка за раз: иначе упрёмся в лимит подключений
PENDING_LINKS = {}                             # order_id -> ссылка (ТОЛЬКО в памяти, до отправки в чат)
IMAP_LOG = []                                  # время (monotonic) оценочных IMAP-подключений
WARNED = {}                                    # ключ предупреждения -> время

A = None                                       # api, ставится в register()


# ---------------------------------------------------------------- хранилище
def _path(name):
    return os.path.join(A.data_dir, name)


def _read(name, default):
    try:
        with open(_path(name), encoding='utf-8') as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _write(name, obj):
    p = _path(name)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def cfg():
    c = dict(DEFAULTS)
    raw = A.settings()
    for k, v in DEFAULTS.items():
        if k in raw and type(raw[k]) is type(v):
            c[k] = raw[k]
    for k, old in OLD_TEXTS.items():
        if raw.get(k) == old:
            c[k] = DEFAULTS[k]
    c['link_interval'] = max(15, c['link_interval'])
    pools = []
    for n in c['pools']:
        if isinstance(n, str) and POOL_NAME_RE.fullmatch(n) and n not in pools:
            pools.append(n)
    if 'main' in pools:
        pools.remove('main')
    c['pools'] = ['main'] + pools
    c['profiles'] = {n: {k: v for k, v in pr.items() if k in PROFILE_KEYS and isinstance(v, str)}
                     for n, pr in c['profiles'].items() if isinstance(n, str) and n and isinstance(pr, dict)}
    c['lot_rules'] = {k: v for k, v in c['lot_rules'].items() if isinstance(k, str) and isinstance(v, dict)}
    return c


def commands(c):
    return [x.strip().casefold() for x in c['ready_cmd'].split(',') if x.strip()]


def is_command(text, cmds):
    """Сообщение покупателя — команда, если его первое слово совпадает с командой (без учёта регистра)."""
    parts = str(text).strip().casefold().split()
    return bool(parts) and parts[0] in cmds


def norm_title(t):
    return re.sub(r'\s+', ' ', str(t)).strip().casefold()


def match_lot(title, lots):
    """Выбранный лот (из списка настроек), которому соответствует название заказа; None, если ни один. Точное совпадение сильнее."""
    t = norm_title(title)
    pairs = [(norm_title(x), x) for x in lots if str(x).strip()]
    for n, x in pairs:
        if t == n:
            return x
    for n, x in pairs:
        if min(len(t), len(n)) >= 15 and (n in t or t in n):
            return x
    return None


def lot_selected(title, lots_norm):
    """Название заказа совпадает с выбранным лотом: равно или одно содержит другое (короче 15 знаков не считается)."""
    t = norm_title(title)
    for l in lots_norm:
        if t == l or (min(len(t), len(l)) >= 15 and (l in t or t in l)):
            return True
    return False


def db():
    d = _read('orders.json', {})
    d.setdefault('orders', {})
    return d


def save_db(d):
    orders = d['orders']
    if len(orders) > 1500:                      # храним последние 1000 по времени обновления
        keep = sorted(orders.items(), key=lambda kv: kv[1].get('updated', ''))[-1000:]
        d['orders'] = dict(keep)
    _write('orders.json', d)


def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def upd(oid, **kw):
    with STATE_LOCK:
        d = db()
        o = d['orders'].get(oid)
        if o is None:
            return None
        o.update(kw)
        o['updated'] = now_iso()
        save_db(d)
        return o


def claim(oid, from_states, to_state, **kw):
    """Атомарно переводит заказ из одного из состояний в другое. False, если заказ уже ушёл в работу (защита от двойной отправки)."""
    with STATE_LOCK:
        d = db()
        o = d['orders'].get(oid)
        if o is None or o['state'] not in from_states:
            return False
        o.update(kw)
        o['state'], o['updated'] = to_state, now_iso()
        save_db(d)
        return True


def get(oid):
    return db()['orders'].get(oid)


def rule_for(c, lot):
    """(пул, профиль) для выбранного лота. Неизвестный пул даёт main, неизвестный профиль даёт стандартный ('')."""
    r = c['lot_rules'].get(norm_title(lot or ''), {})
    pn, pr = r.get('pool'), r.get('profile')
    return (pn if pn in c['pools'] else 'main'), (pr if pr in c['profiles'] else '')


def order_lot(o):
    return o.get('lot') or o.get('title', '')


def order_pool(o, c=None):
    """Пул заказа: тот, из которого уже выдан ящик, иначе по правилу лота."""
    if o.get('pool') and POOL_NAME_RE.fullmatch(str(o['pool'])):
        return o['pool']
    return rule_for(c or cfg(), order_lot(o))[0]


def profile_values(c, name):
    """Тексты профиля: стандартные из настроек, поверх них собственные поля профиля."""
    v = {k: c[k] for k in PROFILE_KEYS}
    v.update(c['profiles'].get(name, {}))
    return v


def order_cfg(o, c=None):
    """Настройки для заказа: общие, а тексты, команда и шаблон ссылки по профилю его лота."""
    c = dict(c or cfg())
    c.update(profile_values(c, rule_for(c, order_lot(o))[1]))
    return c


# ---------------------------------------------------------------- пул и токен
def token():
    t = os.environ.get('SMAK_API_TOKEN', '').strip()
    if t:
        return t
    try:
        with open(_path('smak_token.txt'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


POOLS = {}
POOLS_LOCK = threading.Lock()


def pool_files(name):
    if name == 'main':
        return 'mailboxes.txt', 'pool_state.json'
    return f'mailboxes_{name}.txt', f'pool_state_{name}.json'


def pool(name='main'):
    if not POOL_NAME_RE.fullmatch(str(name)):
        raise PoolError('Недопустимое имя пула.')
    with POOLS_LOCK:
        P = POOLS.get(name)
        if P is None:
            mb, st = pool_files(name)
            P = POOLS[name] = Pool(token=None, pool_file=_path(mb), state_file=_path(st))
    P._token_override = token() or None
    return P


def secret_file(name, text):
    p = _path(name)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def warn_once(key, text, hours=6):
    t = time.time()
    if t - WARNED.get(key, 0) > hours * 3600:
        WARNED[key] = t
        A.notify(text)


# ---------------------------------------------------------------- тексты
def render(template, **vals):
    out = template
    for k, v in vals.items():
        out = out.replace('{' + k + '}', str(v))
    return out


def check_text(key, text):
    t = str(text).strip()
    if not t or len(t) > 1500:
        raise_user(f'Текст «{key}»: от 1 до 1500 символов.')
    allowed = TEXT_VARS[key]
    for v in re.findall(r'\{([^{}]*)\}', t):
        if v not in allowed:
            raise_user(f'В тексте «{key}» можно использовать только ' + ', '.join('{' + a + '}' for a in allowed) + f', а есть {{{v}}}.')
    need = {'address_text': 'email', 'link_text': 'link'}.get(key)
    if need and '{' + need + '}' not in t:
        raise_user(f'В тексте «{key}» должно быть {{{need}}}: без него покупатель не получит нужное.')
    return t


def raise_user(msg):
    raise A.UserError(msg)


# ---------------------------------------------------------------- события: новые заказы
def on_orders(rows, now):
    """Из conf_sync, под замком аккаунта: только запись в файл, никаких запросов."""
    c = cfg()
    lots = [norm_title(x) for x in c['lots'] if str(x).strip()]
    if not lots:
        return
    with STATE_LOCK:
        d = db()
        sig = '|'.join(sorted(lots))
        first = 'seen_at' not in d or d.get('kw') != sig          # первый запуск или смена выбранных лотов: найденное только запоминаем
        d['kw'] = sig
        last_seen = d.get('seen_at')
        gap_long = False
        if last_seen:
            try:
                gap_long = (now - datetime.datetime.fromisoformat(last_seen)).total_seconds() > 3 * 3600
            except ValueError:
                gap_long = True
        changed = False
        for r in rows:
            oid = str(r.get('id') or '').upper()
            if not oid or oid in d['orders'] or r.get('status') != 'paid':
                continue
            title = str(r.get('title') or '')
            lot = match_lot(title, c['lots'])
            if not lot:
                continue
            ts = r.get('ts')
            too_old = ts is None or (now - ts).total_seconds() > c['max_age_hours'] * 3600
            o = {'id': oid, 'buyer': r.get('buyer') or '', 'title': title[:80], 'lot': lot[:300], 'price': r.get('price'),
                 'paid_at': ts.isoformat(timespec='minutes') if ts else '', 'found_at': now_iso(),
                 'attempts': 0, 'links_requested': 0, 'link_errors': 0, 'updated': now_iso()}
            if first or gap_long or too_old:
                o['state'], o['note'] = 'skipped', ('найден при первом запуске' if first else
                                                    'найден после долгого простоя' if gap_long else 'заказ старше лимита или время неизвестно')
            elif not o['buyer']:
                o['state'], o['note'] = 'failed', 'на странице заказов нет ID покупателя'
            else:
                o['state'], o['note'] = 'new', ''
            d['orders'][oid] = o
            changed = True
        d['seen_at'] = now_iso()
        save_db(d)
    if changed:
        A.log('новые заказы занесены в список плагина')


# ---------------------------------------------------------------- выдача адреса
def buyer_snapshot(node):
    """Сколько сообщений покупателя уже есть в диалоге (до отправки адреса)."""
    msgs = A.chat_history(node)
    buyer = [m for m in msgs if not m.get('mine')]
    return len(buyer), (hash_text(buyer[-1]['text']) if buyer else ''), len(msgs)


def hash_text(t):
    return hashlib.sha1(t.encode('utf-8')).hexdigest()[:12]


def issue_address(oid, manual=False):
    """Выдаёт адрес и отправляет его в чат. Возвращает короткий итог для журнала/кнопки."""
    o = get(oid)
    if o is None:
        raise_user('Такого заказа нет в списке плагина.')
    c = order_cfg(o)
    if not claim(oid, ('new', 'no_mailbox', 'failed', 'skipped', 'unclear') if manual else ('new', 'no_mailbox'), 'new'):
        raise_user('Заказ уже в работе или в другом состоянии: адрес не выдаю.')
    o = get(oid)
    if not o['buyer']:
        upd(oid, state='failed', note='нет ID покупателя')
        raise_user('У заказа нет ID покупателя.')
    if not token():
        upd(oid, note='не задан токен SmakMail')
        raise_user('Не задан токен SmakMail.')
    pname = order_pool(o)
    try:
        P = pool(pname)
        email = P.take_free(oid)
        purge_used()                                     # ящики, в которых уже есть письма, убираем из списка
    except PoolError as e:
        upd(oid, note='пул: ' + str(e)[:150])
        warn_once('pool_err', 'Пул почт: ' + str(e)[:200])
        raise_user('Пул почт: ' + str(e))
    if email is None:
        upd(oid, state='no_mailbox', note='свободные почты закончились')
        warn_once('pool_empty_' + pname, f'Свободные почты закончились в пуле «{pname}»: пополните его список (заказ #' + oid + ' ждёт адрес).', hours=3)
        raise_user('Свободных ящиков нет.')
    state = {'sent_journal': False}

    def send():
        node = A.buyer_node(o['buyer'])
        cnt, last, _n = buyer_snapshot(node)
        upd(oid, state='sending_addr', email=email, pool=pname, base_count=cnt, base_hash=last, note='')
        state['sent_journal'] = True                     # с этого момента исход неясен, если связь оборвётся
        return A.chat_send(node, render(c['address_text'], order=oid, email=email, cmd=commands(c)[0], item=o.get('title', '')))

    try:
        res = A.account(send)
    except Exception as e:
        if state['sent_journal']:
            upd(oid, state='unclear', note='связь оборвалась при отправке адреса: проверьте чат')
            A.log(f'заказ #{oid}: исход отправки адреса неясен ({type(e).__name__})', ok=False)
            A.notify(f'заказ #{oid}: адрес мог не дойти (сбой связи). Проверьте чат и нажмите «Выдать адрес» в разделе «Плагины», если его там нет.')
        else:
            P.release(oid)
            n = int(o.get('attempts', 0)) + 1
            upd(oid, state='new' if n < ADDR_RETRIES else 'failed', attempts=n, email='', note='не отправлено: ' + str(e)[:150])
            A.log(f'заказ #{oid}: адрес не отправлен, ящик возвращён ({str(e)[:100]})', ok=False)
        raise_user(str(e))
    if res.get('error_site'):
        P.release(oid)
        n = int(o.get('attempts', 0)) + 1
        upd(oid, state='new' if n < ADDR_RETRIES else 'failed', attempts=n, email='', note='сайт не принял сообщение: ' + res['error_site'][:120])
        A.log(f'заказ #{oid}: сайт не принял сообщение с адресом, ящик возвращён', ok=False)
        raise_user('Сайт не принял сообщение: ' + res['error_site'])
    upd(oid, state='addr_sent', addr_sent_at=now_iso(), note='')
    A.log(f'заказ #{oid}: адрес отправлен покупателю')
    return 'Адрес отправлен.'


# ---------------------------------------------------------------- «готово» от покупателя
def check_ready(oid):
    """Смотрит чат заказа: написал ли покупатель после отправки адреса команду (!ссылка). True = можно брать ссылку."""
    o = get(oid)
    c = order_cfg(o)
    node = A.buyer_node(o['buyer'])
    msgs = A.account(lambda: A.chat_history(node))
    buyer = [m for m in msgs if not m.get('mine')]
    base, bhash = int(o.get('base_count', 0)), o.get('base_hash', '')
    if len(msgs) >= 60 and bhash:                 # окно истории заполнено: счёт по числу ненадёжен, ищем последнее известное сообщение
        idx = max([i for i, m in enumerate(buyer) if hash_text(m['text']) == bhash] or [-1])
        new = buyer[idx + 1:] if idx >= 0 else []
    else:
        new = buyer[base:] if len(buyer) > base else []
    cmds = commands(c)
    return any(is_command(m['text'], cmds) for m in new)


def step_addresses(c):
    if not c['auto_send']:
        return
    d = db()
    todo = [o for o in d['orders'].values() if o['state'] in ('new', 'no_mailbox')][:c['max_per_tick']]
    for o in todo:
        try:
            issue_address(o['id'])
        except Exception as e:
            A.log(f'заказ #{o["id"]}: {str(e)[:150]}', ok=False)
            if 'Свободных ящиков нет' in str(e):
                break                              # дальше смысла нет: ящиков нет у всех


def step_ready(c):
    if not c['auto_link']:
        return
    d = db()
    nowt = datetime.datetime.now()
    for o in list(d['orders'].values()):
        if o['state'] != 'addr_sent':
            continue
        try:
            sent = datetime.datetime.fromisoformat(o.get('addr_sent_at') or o['found_at'])
        except ValueError:
            sent = nowt
        if (nowt - sent).total_seconds() > c['wait_hours'] * 3600:
            upd(o['id'], state='expired', note='покупатель не написал команду за ' + str(c['wait_hours']) + ' ч')
            continue
        last = o.get('ready_checked_at')
        if last and (nowt - datetime.datetime.fromisoformat(last)).total_seconds() < c['ready_poll_min'] * 60:
            continue
        upd(o['id'], ready_checked_at=now_iso())
        try:
            if check_ready(o['id']):
                queue_link(o['id'], c)
        except Exception as e:
            A.log(f'заказ #{o["id"]}: чат не прочитан ({str(e)[:120]})', ok=False)
            if 'блокир' in str(e).lower() or 'капч' in str(e).lower():
                return                              # сессия остановлена: остальных не трогаем


def queue_link(oid, c, manual=False):
    o = get(oid)
    if int(o.get('links_requested', 0)) >= c['max_links']:
        if claim(oid, ('addr_sent', 'link_queue'), 'link_limit', note=f'уже {c["max_links"]} попыток получить ссылку'):
            A.notify(f'заказ #{oid}: исчерпан лимит ссылок ({c["max_links"]}). Разберитесь с покупателем вручную.')
        raise_user(f'Лимит попыток получить ссылку ({c["max_links"]}) исчерпан.')
    if not claim(oid, ('addr_sent',), 'link_queue', links_requested=int(o.get('links_requested', 0)) + 1, note=''):
        raise_user('Ссылку по этому заказу можно запросить только после отправки адреса, и не дважды одновременно.')


# ---------------------------------------------------------------- ссылка
def imap_budget_ok(c):
    t = time.monotonic()
    IMAP_LOG[:] = [x for x in IMAP_LOG if t - x < IMAP_WINDOW]
    need = int(c['link_timeout'] // c['link_interval']) + 2
    return len(IMAP_LOG) + need <= IMAP_BUDGET, need


def step_links(c):
    d = db()
    ready = [o for o in d['orders'].values() if o['state'] in ('link_queue', 'link_send_failed')]
    for o in ready:
        if o['state'] == 'link_send_failed':
            retry_send(o['id'], c)
            continue
        ok, need = imap_budget_ok(c)
        if not ok:
            A.log('очередь ссылок ждёт: близок лимит IMAP-подключений SmakMail (120 за 30 минут)')
            return
        if not LINK_BUSY.acquire(blocking=False):
            return
        if not claim(o['id'], ('link_queue',), 'link_working'):
            LINK_BUSY.release()
            continue
        t = time.monotonic()
        IMAP_LOG.extend([t] * need)
        threading.Thread(target=deliver, args=(o['id'], c), daemon=True).start()
        return                                      # по одному заказу за раз


def deliver(oid, c):
    A.as_background()
    try:
        o0 = get(oid)
        cc = order_cfg(o0, c)
        P = pool(order_pool(o0, c))
        email = P.email_for_order(oid)
        password = P.password_for(email) if email else None
        if not email or not password:
            upd(oid, state='failed', note='для заказа нет ящика или пароля в mailboxes.txt')
            A.notify(f'заказ #{oid}: для ящика не найден пароль в mailboxes.txt.')
            return
        try:
            link = wait_for_magic_link(email, password, timeout=c['link_timeout'], interval=c['link_interval'], pattern=cc['link_pattern'])
        except LinkTimeout:
            upd(oid, state='addr_sent', note='письмо не пришло', ready_checked_at=now_iso(), **_new_baseline(oid))
            A.log(f'заказ #{oid}: письмо не пришло за {c["link_timeout"]} с')
            try:
                A.account(lambda: A.chat_send(A.buyer_node(get(oid)['buyer']), render(cc['nolink_text'], order=oid, cmd=commands(cc)[0])))
            except Exception as e:
                A.log(f'заказ #{oid}: сообщение «письмо не пришло» не отправлено ({str(e)[:100]})', ok=False)
            return
        except AuthError:
            upd(oid, state='failed', note='неверный пароль ящика')
            A.notify(f'заказ #{oid}: ящик не принял пароль (IMAP). Проверьте строку в mailboxes.txt.')
            return
        except MagicLinkError as e:
            n = int(get(oid).get('link_errors', 0)) + 1
            if n >= 3:
                upd(oid, state='failed', link_errors=n, note='IMAP недоступен: ' + str(e)[:100])
                A.notify(f'заказ #{oid}: не удалось связаться с почтой SmakMail три раза подряд.')
            else:
                o = get(oid)
                upd(oid, state='link_queue', link_errors=n, links_requested=max(0, int(o.get('links_requested', 1)) - 1), note='сбой IMAP, повтор')
            A.log(f'заказ #{oid}: IMAP: {str(e)[:100]}', ok=False)
            return
        PENDING_LINKS[oid] = link
        upd(oid, state='link_sending', note='')
        send_pending(oid, c)
    except Exception as e:
        A.log(f'заказ #{oid}: ошибка выдачи ссылки: {type(e).__name__}', ok=False)
        if get(oid) and get(oid)['state'] == 'link_working':
            upd(oid, state='failed', note='ошибка: ' + type(e).__name__)
    finally:
        LINK_BUSY.release()


def _new_baseline(oid):
    """После «письмо не пришло» отсчёт сообщений покупателя начинается заново: следующее «готово» должно быть новым."""
    o = get(oid)
    try:
        cnt, last, _n = A.account(lambda: buyer_snapshot(A.buyer_node(o['buyer'])))
        return {'base_count': cnt, 'base_hash': last}
    except Exception:
        return {'base_count': int(o.get('base_count', 0)), 'base_hash': o.get('base_hash', '')}


def send_pending(oid, c):
    link = PENDING_LINKS.get(oid)
    o = get(oid)
    cc = order_cfg(o, c)
    if not link:
        upd(oid, state='link_lost', note='письмо прочитано, а ссылка не сохранилась (перезапуск?): откройте ящик вручную')
        A.notify(f'заказ #{oid}: ссылка потеряна после перезапуска, письмо уже прочитано. Ящик: {o.get("email", "?")}. Откройте письмо вручную.')
        return
    try:
        res = A.account(lambda: A.chat_send(A.buyer_node(o['buyer']), render(cc['link_text'], order=oid, link=link)))
        err = res.get('error_site')
    except Exception as e:
        err = str(e)[:120]
    if err:
        n = int(o.get('send_errors', 0)) + 1
        if n >= 3:
            PENDING_LINKS.pop(oid, None)
            upd(oid, state='link_lost', send_errors=n, note='ссылку не удалось отправить три раза')
            A.notify(f'заказ #{oid}: ссылку не удалось отправить покупателю. Письмо прочитано, откройте его вручную в ящике {o.get("email", "?")}.')
        else:
            upd(oid, state='link_send_failed', send_errors=n, note='отправка ссылки не удалась, повтор')
        A.log(f'заказ #{oid}: ссылка не отправлена ({err[:100]})', ok=False)
        return
    PENDING_LINKS.pop(oid, None)
    upd(oid, state='link_sent', note='', link_sent_at=now_iso())
    A.log(f'заказ #{oid}: ссылка отправлена покупателю')


def retry_send(oid, c):
    if claim(oid, ('link_send_failed',), 'link_sending'):
        send_pending(oid, c)


# ---------------------------------------------------------------- фоновое задание
TICK_LOCK = threading.Lock()


def tick():
    if not TICK_LOCK.acquire(blocking=False):
        return
    try:
        c = cfg()
        if not c['lots']:
            return
        step_addresses(c)
        step_ready(c)
        step_links(c)
        step_pool_low(c)
        try:
            purge_used()
        except Exception as e:
            A.log(f'очистка пула не удалась ({type(e).__name__})', ok=False)
    finally:
        TICK_LOCK.release()


def pool_counts(name='main'):
    try:
        return pool(name).stats()
    except PoolError:
        return None


def used_pools(c):
    """Пулы, которые назначены выбранным лотам (main, если у лота нет своего правила)."""
    return {rule_for(c, l)[0] for l in c['lots']}


def step_pool_low(c):
    for name in sorted(used_pools(c)):
        s = pool_counts(name)
        if s is None:
            continue
        candidates = s['в файле'] - s['issued'] - s['used'] - s['bad']
        if candidates <= c['pool_low']:
            warn_once('pool_low_' + name, f'Почт в пуле «{name}» почти не осталось: кандидатов {candidates} (порог {c["pool_low"]}). Пополните его список.', hours=12)


# ---------------------------------------------------------------- панель и действия
FIELDS = [
    ('lots', 'Лоты, по которым выдавать почту', 'multi', 'Отметьте лоты. Пока не выбран ни один, плагин ничего не делает. Список берётся из вашего аккаунта кнопкой «Обновить список лотов» ниже.', None, None),
    ('auto_send', 'Сам отправлять адрес покупателю', 'bool', 'Выключено: адрес выдаёте кнопкой в таблице заказов.', None, None),
    ('auto_link', 'Сам отправлять ссылку, когда покупатель написал «готово»', 'bool', 'Выключено: ссылку берёте кнопкой в таблице заказов.', None, None),
    ('ready_cmd', 'Команда, по которой присылать ссылку', 'text', 'По умолчанию !ссылка. Можно несколько через запятую (например: !ссылка, !link). Сообщение покупателя должно начинаться с команды, регистр не важен.', None, None),
    ('max_age_hours', 'Брать заказы не старше, часов', 'int', '', 1, 168),
    ('max_links', 'Попыток получить ссылку на заказ', 'int', '', 1, 10),
    ('link_timeout', 'Ждать письмо, секунд', 'int', 'Каждые «пауза» секунд открывается новое IMAP-подключение, а их не больше 120 за 30 минут.', 60, 900),
    ('link_interval', 'Пауза между проверками ящика, секунд (не меньше 15)', 'int', '', 15, 120),
    ('link_pattern', 'Шаблон ссылки (регулярное выражение)', 'text', 'ПО УМОЛЧАНИЮ ИЩЕТ «magic-link» В АДРЕСЕ. Сверьте с реальным письмом платформы и поправьте.', None, None),
    ('max_per_tick', 'Адресов за одну минутную проверку', 'int', '', 1, 20),
    ('ready_poll_min', 'Как часто смотреть чат заказа, минут', 'int', '', 1, 30),
    ('wait_hours', 'Ждать «готово» не дольше, часов', 'int', '', 1, 48),
    ('pool_low', 'Предупреждать, когда почт осталось не больше', 'int', '', 0, 1000),
    ('address_text', 'Текст с почтой и инструкцией ({order}, {email}, {item}, {cmd})', 'longtext', '', None, None),
    ('link_text', 'Текст со ссылкой ({order}, {link})', 'longtext', '', None, None),
    ('nolink_text', 'Текст «письмо не пришло» ({order}, {cmd})', 'longtext', '', None, None),
]


MB_HELP = ('По ящику на строку. Пароли на экран не выводятся. Что можно: УДАЛИТЬ ящик (сотрите строку), ДОБАВИТЬ (новая строка адрес:пароль), '
           'ИЗМЕНИТЬ пароль (допишите после адреса :новый_пароль). Строка с одним адресом оставляет прежний пароль. '
           'Ящики, уже выданные открытым заказам, удалить нельзя. Ящики, в которых уже есть письма, из списка убираются автоматически '
           '(при сохранении проверяются новые, до 40 за раз; остальные проверяются при выдаче). Один ящик не может быть сразу в двух пулах.')
STD_PROFILE = 'стандартный (настройки выше)'


POOL_WARN = 100          # в панели предупреждаем, когда в используемом пуле осталось меньше стольких почт (только показ, на отправку не влияет)


def pool_left(s):
    """Сколько почт можно ещё выдать: в файле минус выданные, использованные и неисправные (как в step_pool_low)."""
    return s['в файле'] - s['issued'] - s['used'] - s['bad']


def pool_line(s):
    if s is None:
        return 'нет списка ящиков'
    left = pool_left(s)
    return (f'Всего {s["в файле"]} / Выдано {s["issued"] + s["used"]} / Осталось {left}' + (' (МАЛО)' if left < POOL_WARN else '')
            + f'; неисправно {s["bad"]}, не проверялись {s["не проверялись"]}')


def panel():
    c = cfg()
    d = db()
    orders = sorted(d['orders'].values(), key=lambda o: o.get('updated', ''), reverse=True)
    warns = []
    if not c['lots']:
        warns.append('Не выбран ни один лот: плагин ничего не делает. Нажмите «Обновить список лотов» и отметьте лоты в настройках.')
    if not token():
        warns.append('Не задан токен SmakMail (переменная SMAK_API_TOKEN или поле ниже).')
    counts = {n: pool_counts(n) for n in c['pools']}
    for n in sorted(used_pools(c)):
        if counts.get(n) is None:
            warns.append(f'Пул «{n}»: нет списка ящиков. Загрузите ящики в форме «Почты — пул {n}» ниже.')
        elif pool_left(counts[n]) < POOL_WARN:
            warns.append(f'В пуле «{n}» осталось {pool_left(counts[n])} почт (меньше {POOL_WARN}). Пополните список.')
    if c['link_pattern'] == magic_link_auto.DEFAULT_PATTERN:
        warns.append('Шаблон ссылки (стандартный профиль) стоит по умолчанию и не сверен с реальным письмом платформы.')
    per_pool = {n: sum(1 for l in c['lots'] if rule_for(c, l)[0] == n) for n in c['pools']}
    per_prof = {n: sum(1 for l in c['lots'] if rule_for(c, l)[1] == n) for n in c['profiles']}
    stat = [['Токен SmakMail', 'задан' if token() else 'нет']]
    for n in c['pools']:
        stat.append([f'Пул «{n}» (лотов: {per_pool[n]})', pool_line(counts[n])])
    stat += [['Автовыдача адреса', 'включена' if c['auto_send'] else 'выключена (кнопками)'],
             ['Автовыдача ссылки', 'включена' if c['auto_link'] else 'выключена (кнопками)'],
             ['Заказов в списке', len(orders)]]
    rows = []
    for o in orders[:40]:
        b = []
        st = o['state']
        if st in ('new', 'no_mailbox', 'failed', 'skipped'):
            b.append({'label': 'Выдать адрес', 'action': 'give_address', 'data': {'id': o['id']},
                      'confirm': f'Выдать адрес покупателю и отправить ему сообщение по заказу #{o["id"]}?'})
        if st == 'unclear':
            b.append({'label': 'Повторить адрес', 'action': 'give_address', 'data': {'id': o['id']},
                      'confirm': f'Сначала проверьте чат: адреса там нет? Тогда повторю отправку по заказу #{o["id"]}.'})
        if st == 'addr_sent':
            b.append({'label': 'Взять ссылку', 'action': 'give_link', 'data': {'id': o['id']},
                      'confirm': f'Ждать письмо и отправить ссылку покупателю по заказу #{o["id"]}? Покупатель уже ввёл адрес на сайте?'})
        has_box = o.get('email') and st not in ('skipped',)
        rows.append({'cells': ['#' + o['id'], o.get('title', '')[:40], o.get('paid_at', '')[5:16].replace('T', ' '),
                               o.get('email', '') if has_box else '', (o.get('pool') or '') if has_box else '',
                               STATES.get(st, st), o.get('note', '')], 'buttons': b})
    pool_opts = [{'v': n, 'l': n} for n in c['pools']]
    prof_opts = [{'v': '', 'l': STD_PROFILE}] + [{'v': n, 'l': n} for n in sorted(c['profiles'])]
    rule_rows = []
    for lot in c['lots']:
        pn, pr = rule_for(c, lot)
        rule_rows.append({'cells': [lot[:80],
                                    {'select': {'options': pool_opts, 'value': pn, 'action': 'set_lot_rule', 'data': {'lot': lot, 'kind': 'pool'}}},
                                    {'select': {'options': prof_opts, 'value': pr, 'action': 'set_lot_rule', 'data': {'lot': lot, 'kind': 'profile'}}}],
                          'buttons': []})
    blocks = []
    for pn in sorted(c['profiles']):
        eff = profile_values(c, pn)
        blocks.append({
            'title': f'Профиль текстов «{pn}» (лотов: {per_prof[pn]})',
            'help': 'Поле, которое вы не меняли, совпадает со стандартным (настройки выше) и при его правке тоже меняется. Назначается лоту в таблице «Правила по лотам».',
            'action': 'save_profile', 'data': {'profile': pn},
            'fields': [{'key': k, 'label': lb, 'type': tp, 'help': hp, 'min': mn, 'max': mx, 'value': eff[k]}
                       for k, lb, tp, hp, mn, mx in FIELDS if k in PROFILE_KEYS],
            'buttons': [{'label': f'Удалить профиль «{pn}»', 'action': 'delete_profile', 'data': {'profile': pn},
                         'confirm': f'Удалить профиль «{pn}»? Лотам с этим профилем вернётся стандартный.'}]})
    forms = [
        {'title': 'Токен SmakMail API', 'help': 'Нужны права mail.read. Токен сохраняется в файл на сервере и обратно на экран не выводится. Если токен попадал в переписку, перевыпустите его.',
         'action': 'set_token', 'kind': 'secret', 'label': 'Токен', 'button': 'Сохранить токен'},
        {'title': 'Новый пул почт', 'help': 'Пул это отдельный список ящиков. Лоты с одним и тем же пулом делят этот список между собой; лоты с разными пулами берут почты из разных списков. Имя: буквы, цифры, _ и -, до 24 знаков.',
         'action': 'add_pool', 'kind': 'text', 'label': 'Имя пула', 'button': 'Создать пул'},
        {'title': 'Новый профиль текстов', 'help': 'Профиль задаёт инструкцию покупателю, команду и шаблон ссылки для лота. Новый профиль сначала повторяет стандартные тексты. Имя: буквы, цифры, _ и -, до 24 знаков.',
         'action': 'add_profile', 'kind': 'text', 'label': 'Имя профиля', 'button': 'Создать профиль'}]
    for i, n in enumerate(c['pools']):
        forms.append({'title': f'Почты — пул «{n}»', 'kind': 'editor', 'action': 'save_mailboxes', 'data': {'pool': n},
                      'button': f'Сохранить список пула «{n}»', 'value': '\n'.join(a for a, _p in box_pairs(n)),
                      'help': MB_HELP if i == 0 else 'Правила те же, что в первом списке: адрес:пароль, по ящику на строку.'})
    buttons = [{'label': 'Обновить список лотов', 'action': 'refresh_lots', 'data': {}}]
    for n in c['pools']:
        buttons.append({'label': f'Убрать ящики с письмами: пул «{n}» (проверить 30)', 'action': 'clean_pool', 'data': {'limit': 30, 'pool': n},
                        'confirm': f'Проверить до 30 ящиков пула «{n}» по API SmakMail и удалить из списка те, где уже есть письма?'})
        if n != 'main':
            buttons.append({'label': f'Удалить пул «{n}»', 'action': 'delete_pool', 'data': {'pool': n},
                            'confirm': f'Удалить пул «{n}»? Удалится только если он никому не назначен и список ящиков в нём пуст.'})
    return {
        'warnings': warns,
        'status': stat,
        'settings': {'action': 'save_settings', 'fields': [
            dict({'key': k, 'label': lb, 'type': tp, 'help': hp, 'min': mn, 'max': mx, 'value': c[k]},
                 **({'options': lot_options(c)} if tp == 'multi' else {})) for k, lb, tp, hp, mn, mx in FIELDS]},
        'blocks': blocks,
        'forms': forms,
        'buttons': buttons,
        'tables': [
            {'title': 'Правила по лотам: пул почт и профиль текстов (выбор применяется сразу)',
             'columns': ['Лот', 'Пул почт', 'Профиль текстов'], 'rows': rule_rows},
            {'title': 'Заказы (последние 40)', 'columns': ['Заказ', 'Лот', 'Оплачен', 'Почта', 'Пул', 'Состояние', 'Примечание'], 'rows': rows}],
    }


def clean_text(k, lb, v):
    """Проверка одного текстового поля (общие настройки и профили). Возвращает очищенное значение или бросает UserError."""
    v = str(v).strip()
    if k in TEXT_VARS:
        v = check_text(k, v)
    elif k == 'link_pattern':
        try:
            re.compile(v)
        except re.error as e:
            raise_user(f'Шаблон ссылки не разобран: {e}')
        if not v or len(v) > 300:
            raise_user('Шаблон ссылки: от 1 до 300 символов.')
    elif k == 'ready_cmd':
        parts = [w.strip() for w in v.split(',') if w.strip()]
        if not parts:
            raise_user('Команда: нужна хотя бы одна.')
        for w in parts:
            if not w.startswith('!') or len(w) < 2 or len(w) > 30 or ' ' in w:
                raise_user(f'Команда «{w}»: должна начинаться с «!», без пробелов, до 30 знаков (например !ссылка).')
        v = ', '.join(parts)
    elif len(v) > 300:
        raise_user(f'«{lb}»: не длиннее 300 символов.')
    return v


def save_cfg(c, **changes):
    """Записывает ВСЕ настройки (api.save_settings заменяет файл целиком), меняя только переданные ключи."""
    data = {k: c[k] for k in DEFAULTS}
    data.update(changes)
    A.save_settings(data)


def a_save_settings(b):
    cur, new = cfg(), {}
    for k, lb, tp, hp, mn, mx in FIELDS:
        if k not in b:
            new[k] = cur[k]
            continue
        v = b[k]
        if tp == 'multi':
            if not isinstance(v, list) or len(v) > 100 or not all(isinstance(x, str) for x in v):
                raise_user(f'«{lb}»: нужен список лотов (не больше 100).')
            seen_t, clean = set(), []
            for x in v:
                x = x.strip()
                if x and len(x) <= 300 and norm_title(x) not in seen_t:
                    seen_t.add(norm_title(x))
                    clean.append(x)
            new[k] = clean
            continue
        if tp == 'bool':
            if not isinstance(v, bool):
                raise_user(f'«{lb}»: нужно да/нет.')
        elif tp == 'int':
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not mn <= v <= mx:
                raise_user(f'«{lb}»: число от {mn} до {mx}.')
            v = int(v)
        else:
            v = clean_text(k, lb, v)
        new[k] = v
    for k in ('pools', 'profiles', 'lot_rules'):          # их правят свои действия; здесь сохраняем как есть
        new[k] = cur[k]
    A.save_settings(new)
    A.log('настройки изменены: ' + ', '.join(k for k in b if k in new and new[k] != cur[k]))
    return {'ok': True}


def a_set_token(b):
    t = str(b.get('value', '')).strip()
    if not SECRET_RE.fullmatch(t):
        raise_user('Токен выглядит неверно (пробелы или слишком короткий).')
    secret_file('smak_token.txt', t)
    A.log('токен SmakMail сохранён')
    return {'note': 'Токен сохранён.'}


# ---------------------------------------------------------------- лоты аккаунта
def lots_cache():
    d = _read('lots_cache.json', [])
    return [x for x in d if isinstance(x, dict) and x.get('title')]


def lot_options(c):
    """Варианты для выбора: лоты из сохранённого списка + уже выбранные, которых в списке нет (чтобы выбор не пропал)."""
    out, seen = [], set()
    for x in lots_cache():
        t = str(x['title'])
        if norm_title(t) in seen:
            continue
        seen.add(norm_title(t))
        out.append({'v': t, 'l': t[:110] + ('  ·  ' + str(x['price']) if x.get('price') else '')})
    for t in c['lots']:
        if norm_title(t) not in seen:
            seen.add(norm_title(t))
            out.append({'v': t, 'l': t[:110] + '  (нет в последнем списке)'})
    return out


def a_refresh_lots(b):
    if not hasattr(A, 'my_lots'):
        raise_user('Эта версия app.py не умеет читать лоты (нет api.my_lots). Обновите app.py.')
    rows = A.account(lambda: A.my_lots())
    keep = [{'id': str(r.get('id', ''))[:20], 'title': str(r.get('title', ''))[:300], 'section': str(r.get('section', ''))[:80],
             'price': str(r.get('price', ''))[:20]} for r in rows if r.get('title')]
    _write('lots_cache.json', keep)
    A.log(f'список лотов обновлён: {len(keep)}')
    return {'note': f'Лотов на аккаунте: {len(keep)}. Откройте настройки выше и отметьте нужные.'}


# ---------------------------------------------------------------- пулы почт: список, правка, очистка
def box_pairs(name='main'):
    try:
        return pool(name).read_pool()
    except PoolError:
        return []


def write_boxes(pairs, name='main'):
    p = _path(pool_files(name)[0])
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(''.join(f'{a}:{pw}\n' for a, pw in pairs))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)


def pool_edit(fn, name='main'):
    """fn(state) меняет состояние пула под его замком."""
    P = pool(name)
    with P._lock:
        st = P._load_state()
        fn(st)
        P._save_state(st)


def pool_state(name='main'):
    P = pool(name)
    with P._lock:
        return P._load_state()


ACTIVE_STATES = ('sending_addr', 'addr_sent', 'link_queue', 'link_working', 'link_sending', 'link_send_failed', 'unclear')


def busy_boxes():
    """Ящики, которые сейчас нужны открытым заказам (удалять их нельзя). Считаются по всем пулам."""
    return {str(o.get('email', '')).lower() for o in db()['orders'].values() if o.get('email') and o['state'] in ACTIVE_STATES}


def drop_boxes(addrs, name='main'):
    """Убирает ящики из списка пула и из его состояния. Выданные открытым заказам не трогает. Возвращает, сколько убрано."""
    addrs = {a.lower() for a in addrs}
    with MB_LOCK:
        addrs -= busy_boxes()
        if not addrs:
            return 0
        pairs = box_pairs(name)
        keep = [(a, pw) for a, pw in pairs if a not in addrs]
        n = len(pairs) - len(keep)
        write_boxes(keep, name)
        pool_edit(lambda st2: [st2['mailboxes'].pop(a, None) for a in addrs], name)
        return n


def purge_used():
    """Ящики, которые пул пометил «в них есть письма», удаляются из списка совсем (во всех пулах)."""
    total = 0
    for name in cfg()['pools']:
        st = pool_state(name)
        used = [a for a, v in st['mailboxes'].items() if v.get('status') == 'used']
        n = drop_boxes(used, name) if used else 0
        if n:
            A.log(f'из пула «{name}» убрано ящиков с письмами: {n}')
        total += n
    return total


def drop_with_mail(pairs, limit, name='main'):
    """Проверяет ящики по API и удаляет те, где есть письма. Возвращает (убрано, проверено)."""
    tk = token()
    if not tk:
        return 0, 0
    found, checked = [], 0
    for addr, pw in pairs[:limit]:
        r = check_mailbox(addr, pw, tk)
        checked += 1
        time.sleep(0.2)
        if r == HAS_MAIL:
            found.append(addr)
    return (drop_boxes(found, name) if found else 0), checked


def pool_arg(b):
    name = str(b.get('pool') or 'main')
    if name not in cfg()['pools']:
        raise_user(f'Пула «{name}» нет.')
    return name


def a_save_mailboxes(b):
    name = pool_arg(b)
    text = str(b.get('value', ''))
    with MB_LOCK:
        old = dict(box_pairs(name))
        busy = busy_boxes()
        elsewhere = {}                                   # ящик -> пул, где он уже лежит (в двух пулах быть нельзя)
        for other in cfg()['pools']:
            if other != name:
                for a, _p in box_pairs(other):
                    elsewhere[a] = other
        new, seen, bad, dup, cross = [], set(), 0, 0, []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            addr, _sep, pw = line.partition(':')
            addr, pw = addr.strip().lower(), pw.strip()
            if '@' not in addr or ' ' in addr or ('' == pw and addr not in old):
                bad += 1
                continue
            if addr in elsewhere:
                cross.append(elsewhere[addr])
                continue
            if addr in seen:
                dup += 1
                continue
            seen.add(addr)
            new.append((addr, pw or old[addr]))
        kept_busy = [a for a in old if a not in seen and a in busy]
        for a in kept_busy:
            new.append((a, old[a]))
        added = [(a, pw) for a, pw in new if a not in old]
        changed = [a for a, pw in new if a in old and old[a] != pw]
        removed = [a for a in old if a not in {x for x, _p in new}]
        write_boxes(new, name)
        def fix_state(st):
            for a in removed:
                st['mailboxes'].pop(a, None)
            for a in changed:
                if st['mailboxes'].get(a, {}).get('status') == 'bad':
                    st['mailboxes'].pop(a, None)          # пароль исправили: ящик проверится заново
        pool_edit(fix_state, name)
    mail_dropped, checked = drop_with_mail(added, 40, name)
    A.log(f'пул «{name}»: добавлено {len(added)}, изменён пароль у {len(changed)}, удалено {len(removed)}, '
          f'убрано с письмами {mail_dropped}, неверных строк {bad}, повторов {dup}, уже в другом пуле {len(cross)}')
    parts = [f'добавлено {len(added) - mail_dropped}', f'пароль изменён у {len(changed)}', f'удалено {len(removed)}']
    if mail_dropped:
        parts.append(f'убрано, потому что в них уже есть письма: {mail_dropped}')
    if added and not token():
        parts.append('токен SmakMail не задан, новые ящики на письма не проверены')
    elif len(added) > checked:
        parts.append(f'проверено на письма {checked} из {len(added)} новых, остальные проверятся при выдаче')
    if kept_busy:
        parts.append(f'не удалены (выданы заказам): {len(kept_busy)}')
    if bad:
        parts.append(f'неверных строк пропущено: {bad} (новый ящик пишется адрес:пароль)')
    if dup:
        parts.append(f'повторов пропущено: {dup}')
    if cross:
        parts.append(f'пропущено, потому что ящик уже в другом пуле: {len(cross)} (в двух пулах ящик быть не может)')
    return {'note': f'Пул «{name}», список сохранён: ' + ', '.join(parts) + '.'}


def a_clean_pool(b):
    if not token():
        raise_user('Не задан токен SmakMail.')
    name = pool_arg(b)
    limit = max(1, min(int(b.get('limit', 30) or 30), 60))
    st = pool_state(name)
    skip = {a for a, v in st['mailboxes'].items() if v.get('status') in ('issued', 'used', 'bad')}
    cs = 'clean_state.json' if name == 'main' else f'clean_state_{name}.json'
    last = _read(cs, {})
    cand = [(a, pw) for a, pw in box_pairs(name) if a not in skip]
    cand.sort(key=lambda x: last.get(x[0], ''))              # сначала ещё не проверявшиеся, потом самые давние
    batch = cand[:limit]
    dropped, checked = drop_with_mail(batch, limit, name)
    stamp = now_iso()
    for a, _pw in batch[:checked]:
        last[a] = stamp
    alive = {a for a, _p in box_pairs(name)}
    _write(cs, {a: t for a, t in last.items() if a in alive})
    A.log(f'проверка пула «{name}»: проверено {checked}, убрано с письмами {dropped}')
    return {'note': f'Пул «{name}»: проверено {checked} из {len(cand)} кандидатов, убрано ящиков с письмами: {dropped}.'}


# ---------------------------------------------------------------- пулы, профили и правила лотов
def new_name(b, what, existing):
    n = str(b.get('value', '')).strip()
    if not POOL_NAME_RE.fullmatch(n):
        raise_user(f'Имя {what}: от 1 до 24 знаков, только буквы, цифры, _ и -.')
    if n.casefold() in {x.casefold() for x in existing} or n.casefold() == 'main':
        raise_user(f'{what.capitalize()} с именем «{n}» уже есть.')
    return n


def a_add_pool(b):
    c = cfg()
    if len(c['pools']) >= MAX_POOLS:
        raise_user(f'Пулов не больше {MAX_POOLS}.')
    n = new_name(b, 'пула', c['pools'])
    if not os.path.exists(_path(pool_files(n)[0])):
        write_boxes([], n)
    save_cfg(c, pools=c['pools'] + [n])
    A.log(f'создан пул «{n}»')
    return {'note': f'Пул «{n}» создан. Загрузите в него ящики (форма «Почты — пул {n}») и назначьте его лотам в таблице правил.'}


def a_delete_pool(b):
    c = cfg()
    n = str(b.get('pool', ''))
    if n == 'main':
        raise_user('Пул main удалить нельзя.')
    if n not in c['pools']:
        raise_user(f'Пула «{n}» нет.')
    lots = [l for l in c['lots'] if rule_for(c, l)[0] == n]
    if lots:
        raise_user(f'Пул «{n}» назначен лотам ({len(lots)}). Сначала назначьте этим лотам другой пул.')
    if any(o.get('pool') == n and o['state'] in ACTIVE_STATES for o in db()['orders'].values()):
        raise_user(f'В пуле «{n}» есть ящики, выданные открытым заказам. Дождитесь их завершения.')
    left = len(box_pairs(n))
    if left:
        raise_user(f'В пуле «{n}» ещё {left} ящиков. Сотрите их из списка и сохраните его (или перенесите в другой пул), потом удаляйте пул.')
    rules = {k: v for k, v in c['lot_rules'].items() if v.get('pool') != n}
    save_cfg(c, pools=[x for x in c['pools'] if x != n], lot_rules=rules)
    A.log(f'удалён пул «{n}»')
    return {'note': f'Пул «{n}» удалён.'}


def a_add_profile(b):
    c = cfg()
    if len(c['profiles']) >= MAX_PROFILES:
        raise_user(f'Профилей не больше {MAX_PROFILES}.')
    n = new_name(b, 'профиля', c['profiles'])
    profiles = dict(c['profiles'])
    profiles[n] = {}
    save_cfg(c, profiles=profiles)
    A.log(f'создан профиль «{n}»')
    return {'note': f'Профиль «{n}» создан: пока он повторяет стандартные тексты. Измените его ниже и назначьте лотам в таблице правил.'}


def a_save_profile(b):
    c = cfg()
    n = str(b.get('profile', ''))
    if n not in c['profiles']:
        raise_user(f'Профиля «{n}» нет.')
    labels = {k: lb for k, lb, _tp, _hp, _mn, _mx in FIELDS}
    old = c['profiles'][n]
    own = dict(old)
    for k in PROFILE_KEYS:
        if k in b:
            own[k] = clean_text(k, labels[k], b[k])
    own = {k: v for k, v in own.items() if v != c[k]}      # хранятся только поля, отличающиеся от стандартных
    profiles = dict(c['profiles'])
    profiles[n] = own
    save_cfg(c, profiles=profiles)
    A.log(f'профиль «{n}» изменён: ' + (', '.join(k for k in PROFILE_KEYS if own.get(k) != old.get(k)) or 'без изменений'))
    return {'note': f'Профиль «{n}» сохранён.'}


def a_delete_profile(b):
    c = cfg()
    n = str(b.get('profile', ''))
    if n not in c['profiles']:
        raise_user(f'Профиля «{n}» нет.')
    profiles = {k: v for k, v in c['profiles'].items() if k != n}
    rules = {}
    for k, v in c['lot_rules'].items():
        v = dict(v)
        if v.get('profile') == n:
            v['profile'] = ''
        rules[k] = v
    save_cfg(c, profiles=profiles, lot_rules=rules)
    A.log(f'удалён профиль «{n}»')
    return {'note': f'Профиль «{n}» удалён, его лотам вернулся стандартный.'}


def a_set_lot_rule(b):
    c = cfg()
    lot, kind, val = str(b.get('lot', '')), str(b.get('kind', '')), str(b.get('value', ''))
    if norm_title(lot) not in {norm_title(x) for x in c['lots']}:
        raise_user('Этот лот не выбран в настройках плагина.')
    if kind == 'pool':
        if val not in c['pools']:
            raise_user(f'Пула «{val}» нет.')
    elif kind == 'profile':
        if val and val not in c['profiles']:
            raise_user(f'Профиля «{val}» нет.')
    else:
        raise_user('Неизвестное правило.')
    rules = {k: dict(v) for k, v in c['lot_rules'].items()}
    r = rules.setdefault(norm_title(lot), {})
    r[kind] = val
    save_cfg(c, lot_rules=rules)
    A.log(f'лот «{lot[:50]}»: {"пул" if kind == "pool" else "профиль"} = {val or "стандартный"}')
    return {'note': f'Лот «{lot[:50]}»: {"пул" if kind == "pool" else "профиль текстов"} «{val or "стандартный"}».'}


def a_give_address(b):
    oid = str(b.get('id', '')).upper()
    return {'note': issue_address(oid, manual=True)}


def a_give_link(b):
    oid = str(b.get('id', '')).upper()
    c = cfg()
    if get(oid) is None:
        raise_user('Такого заказа нет в списке плагина.')
    queue_link(oid, c, manual=True)
    return {'note': 'Заказ в очереди на ссылку: письмо ждём до ' + str(c['link_timeout']) + ' с, ссылка уйдёт покупателю в чат.'}


def register(api):
    global A
    A = api
    api.on_orders(on_orders)
    api.every(1, tick, 'выдача адресов и ссылок')
    api.panel(panel)
    api.action('save_settings', a_save_settings)
    api.action('set_token', a_set_token)
    api.action('save_mailboxes', a_save_mailboxes)
    api.action('refresh_lots', a_refresh_lots)
    api.action('clean_pool', a_clean_pool)
    api.action('give_address', a_give_address)
    api.action('give_link', a_give_link)
    api.action('add_pool', a_add_pool)
    api.action('delete_pool', a_delete_pool)
    api.action('add_profile', a_add_profile)
    api.action('save_profile', a_save_profile)
    api.action('delete_profile', a_delete_profile)
    api.action('set_lot_rule', a_set_lot_rule)
