# -*- coding: utf-8 -*-
"""Плагин «Почты SmakMail»: выдача адреса почты покупателю и пересылка magic-link из письма (версия 1.0).

Поток: заказ оплачен -> покупателю в чат уходит адрес свободной почты -> покупатель вводит адрес на сайте платформы и
пишет «готово» -> плагин ждёт письмо по IMAP и отправляет ссылку в чат заказа.
Плагин ничего не покупает у SmakMail: ящики (адрес:пароль) вы загружаете сами. API SmakMail нужен только чтобы понять,
пуст ли ящик (свободный ящик = в нём нет писем).

Безопасность (сделано намеренно):
  - плагин по умолчанию ВЫКЛЮЧЕН; автовыдача адреса и автовыдача ссылки включаются отдельными галочками, тоже выключены;
  - работает только с заказами, в названии которых есть ваше ключевое слово (без него не делает ничего);
  - заказы, найденные при первом запуске или после долгого простоя, не трогает (их можно взять вручную кнопкой);
  - на заказ один адрес и не больше N ссылок; журнал отправки пишется ДО отправки, при неясном исходе повтора нет;
  - пароли ящиков, токен SmakMail и ссылки не пишутся ни в журнал, ни в ответы API, ни в оповещения, ни в orders.json;
    ссылка живёт только в памяти до отправки в чат;
  - данные лежат в plugins_data/smakmail/ (в резервные копии не входят).
Файлы в папке данных: mailboxes.txt (СЕКРЕТ: адрес:пароль), smak_token.txt (СЕКРЕТ), pool_state.json, orders.json, settings.json, log.csv.
"""
import datetime, hashlib, json, os, re, threading, time

from mailbox_pool import Pool, PoolError, check_mailbox, EMPTY, HAS_MAIL, BAD, UNKNOWN
import magic_link_auto
from magic_link_auto import AuthError, LinkTimeout, MagicLinkError, wait_for_magic_link

PLUGIN = {'id': 'smakmail', 'name': 'Почты SmakMail', 'version': '1.0',
          'description': 'Выдаёт покупателю адрес почты из вашего пула и присылает в чат ссылку для входа из письма.'}

DEFAULTS = {
    'lot_keywords': '',            # через запятую; пусто = плагин ничего не делает
    'auto_send': False,            # сам отправлять адрес покупателю
    'auto_link': False,            # сам ждать письмо и отправлять ссылку, когда покупатель написал «готово»
    'ready_words': 'готов',        # через запятую; сообщение покупателя считается «готово», если содержит любое слово
    'max_age_hours': 24,           # заказы старше не берутся
    'max_links': 3,                # попыток получить ссылку на заказ
    'link_timeout': 300,           # сколько секунд ждать письмо
    'link_interval': 20,           # пауза между проверками ящика (не меньше 15)
    'link_pattern': magic_link_auto.DEFAULT_PATTERN,
    'max_per_tick': 3,             # адресов за одну минутную проверку
    'ready_poll_min': 2,           # как часто смотреть чат заказа, который ждёт «готово»
    'wait_hours': 6,               # сколько ждать «готово», потом заказ помечается просроченным
    'pool_low': 5,                 # предупреждать, когда непроверенных и свободных ящиков не больше
    'address_text': ('Здравствуйте! По заказу #{order} ваша почта: {email}\n'
                     'Введите этот адрес на сайте платформы, где нужен вход. Когда введёте, напишите здесь «готово», '
                     'и я пришлю ссылку из письма.'),
    'link_text': 'Ваша ссылка для входа: {link}\nОна одноразовая и действует недолго: откройте её сразу.',
    'nolink_text': ('Письмо пока не пришло. Проверьте, что адрес введён без ошибок, запросите письмо ещё раз '
                    'и напишите «готово».'),
}
TEXT_VARS = {'address_text': ('order', 'email'), 'link_text': ('order', 'link'), 'nolink_text': ('order',)}
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
POOL = None


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
    c['link_interval'] = max(15, c['link_interval'])
    return c


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


def pool():
    POOL._token_override = token() or None
    return POOL


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
    words = [w.strip().casefold() for w in c['lot_keywords'].split(',') if w.strip()]
    if not words:
        return
    with STATE_LOCK:
        d = db()
        sig = '|'.join(sorted(words))
        first = 'seen_at' not in d or d.get('kw') != sig          # первый запуск или смена ключевых слов: найденное только запоминаем
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
            if not any(w in title.casefold() for w in words):
                continue
            ts = r.get('ts')
            too_old = ts is None or (now - ts).total_seconds() > c['max_age_hours'] * 3600
            o = {'id': oid, 'buyer': r.get('buyer') or '', 'title': title[:80], 'price': r.get('price'),
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
    c = cfg()
    o = get(oid)
    if o is None:
        raise_user('Такого заказа нет в списке плагина.')
    if not claim(oid, ('new', 'no_mailbox', 'failed', 'skipped', 'unclear') if manual else ('new', 'no_mailbox'), 'new'):
        raise_user('Заказ уже в работе или в другом состоянии: адрес не выдаю.')
    o = get(oid)
    if not o['buyer']:
        upd(oid, state='failed', note='нет ID покупателя')
        raise_user('У заказа нет ID покупателя.')
    if not token():
        upd(oid, note='не задан токен SmakMail')
        raise_user('Не задан токен SmakMail.')
    try:
        email = pool().take_free(oid)
    except PoolError as e:
        upd(oid, note='пул: ' + str(e)[:150])
        warn_once('pool_err', 'Пул почт: ' + str(e)[:200])
        raise_user('Пул почт: ' + str(e))
    if email is None:
        upd(oid, state='no_mailbox', note='свободные почты закончились')
        warn_once('pool_empty', 'Свободные почты закончились: пополните mailboxes.txt (заказ #' + oid + ' ждёт адрес).', hours=3)
        raise_user('Свободных ящиков нет.')
    state = {'sent_journal': False}

    def send():
        node = A.buyer_node(o['buyer'])
        cnt, last, _n = buyer_snapshot(node)
        upd(oid, state='sending_addr', email=email, base_count=cnt, base_hash=last, note='')
        state['sent_journal'] = True                     # с этого момента исход неясен, если связь оборвётся
        return A.chat_send(node, render(c['address_text'], order=oid, email=email))

    try:
        res = A.account(send)
    except Exception as e:
        if state['sent_journal']:
            upd(oid, state='unclear', note='связь оборвалась при отправке адреса: проверьте чат')
            A.log(f'заказ #{oid}: исход отправки адреса неясен ({type(e).__name__})', ok=False)
            A.notify(f'заказ #{oid}: адрес мог не дойти (сбой связи). Проверьте чат и нажмите «Выдать адрес» в разделе «Плагины», если его там нет.')
        else:
            pool().release(oid)
            n = int(o.get('attempts', 0)) + 1
            upd(oid, state='new' if n < ADDR_RETRIES else 'failed', attempts=n, email='', note='не отправлено: ' + str(e)[:150])
            A.log(f'заказ #{oid}: адрес не отправлен, ящик возвращён ({str(e)[:100]})', ok=False)
        raise_user(str(e))
    if res.get('error_site'):
        pool().release(oid)
        n = int(o.get('attempts', 0)) + 1
        upd(oid, state='new' if n < ADDR_RETRIES else 'failed', attempts=n, email='', note='сайт не принял сообщение: ' + res['error_site'][:120])
        A.log(f'заказ #{oid}: сайт не принял сообщение с адресом, ящик возвращён', ok=False)
        raise_user('Сайт не принял сообщение: ' + res['error_site'])
    upd(oid, state='addr_sent', addr_sent_at=now_iso(), note='')
    A.log(f'заказ #{oid}: адрес отправлен покупателю')
    return 'Адрес отправлен.'


# ---------------------------------------------------------------- «готово» от покупателя
def check_ready(oid):
    """Смотрит чат заказа: написал ли покупатель после отправки адреса слово из списка. True = можно брать ссылку."""
    c = cfg()
    o = get(oid)
    node = A.buyer_node(o['buyer'])
    msgs = A.account(lambda: A.chat_history(node))
    buyer = [m for m in msgs if not m.get('mine')]
    base, bhash = int(o.get('base_count', 0)), o.get('base_hash', '')
    if len(msgs) >= 60 and bhash:                 # окно истории заполнено: счёт по числу ненадёжен, ищем последнее известное сообщение
        idx = max([i for i, m in enumerate(buyer) if hash_text(m['text']) == bhash] or [-1])
        new = buyer[idx + 1:] if idx >= 0 else []
    else:
        new = buyer[base:] if len(buyer) > base else []
    words = [w.strip().casefold() for w in c['ready_words'].split(',') if w.strip()]
    return any(any(w in m['text'].casefold() for w in words) for m in new)


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
            upd(o['id'], state='expired', note='покупатель не написал «готово» за ' + str(c['wait_hours']) + ' ч')
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
        email = pool().email_for_order(oid)
        password = pool().password_for(email) if email else None
        if not email or not password:
            upd(oid, state='failed', note='для заказа нет ящика или пароля в mailboxes.txt')
            A.notify(f'заказ #{oid}: для ящика не найден пароль в mailboxes.txt.')
            return
        try:
            link = wait_for_magic_link(email, password, timeout=c['link_timeout'], interval=c['link_interval'], pattern=c['link_pattern'])
        except LinkTimeout:
            upd(oid, state='addr_sent', note='письмо не пришло', ready_checked_at=now_iso(), **_new_baseline(oid))
            A.log(f'заказ #{oid}: письмо не пришло за {c["link_timeout"]} с')
            try:
                A.account(lambda: A.chat_send(A.buyer_node(get(oid)['buyer']), render(c['nolink_text'], order=oid)))
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
    if not link:
        upd(oid, state='link_lost', note='письмо прочитано, а ссылка не сохранилась (перезапуск?): откройте ящик вручную')
        A.notify(f'заказ #{oid}: ссылка потеряна после перезапуска, письмо уже прочитано. Ящик: {o.get("email", "?")}. Откройте письмо вручную.')
        return
    try:
        res = A.account(lambda: A.chat_send(A.buyer_node(o['buyer']), render(c['link_text'], order=oid, link=link)))
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
        if not [w for w in c['lot_keywords'].split(',') if w.strip()]:
            return
        step_addresses(c)
        step_ready(c)
        step_links(c)
        step_pool_low(c)
    finally:
        TICK_LOCK.release()


def pool_counts():
    try:
        return pool().stats()
    except PoolError:
        return None


def step_pool_low(c):
    s = pool_counts()
    if s is None:
        return
    candidates = s['в файле'] - s['issued'] - s['used'] - s['bad']
    if candidates <= c['pool_low']:
        warn_once('pool_low', f'Почт в пуле почти не осталось: кандидатов {candidates} (порог {c["pool_low"]}). Пополните mailboxes.txt.', hours=12)


# ---------------------------------------------------------------- панель и действия
FIELDS = [
    ('lot_keywords', 'Ключевые слова в названии лота (через запятую)', 'text', 'Без них плагин ничего не делает. Берутся только заказы, где в названии есть любое из слов.', None, None),
    ('auto_send', 'Сам отправлять адрес покупателю', 'bool', 'Выключено: адрес выдаёте кнопкой в таблице заказов.', None, None),
    ('auto_link', 'Сам отправлять ссылку, когда покупатель написал «готово»', 'bool', 'Выключено: ссылку берёте кнопкой в таблице заказов.', None, None),
    ('ready_words', 'Слова «готово» (через запятую, нужно хотя бы одно)', 'text', 'Сообщение покупателя считается «готово», если содержит любое слово (без учёта регистра).', None, None),
    ('max_age_hours', 'Брать заказы не старше, часов', 'int', '', 1, 168),
    ('max_links', 'Попыток получить ссылку на заказ', 'int', '', 1, 10),
    ('link_timeout', 'Ждать письмо, секунд', 'int', 'Каждые «пауза» секунд открывается новое IMAP-подключение, а их не больше 120 за 30 минут.', 60, 900),
    ('link_interval', 'Пауза между проверками ящика, секунд (не меньше 15)', 'int', '', 15, 120),
    ('link_pattern', 'Шаблон ссылки (регулярное выражение)', 'text', 'ПО УМОЛЧАНИЮ ИЩЕТ «magic-link» В АДРЕСЕ. Сверьте с реальным письмом платформы и поправьте.', None, None),
    ('max_per_tick', 'Адресов за одну минутную проверку', 'int', '', 1, 20),
    ('ready_poll_min', 'Как часто смотреть чат заказа, минут', 'int', '', 1, 30),
    ('wait_hours', 'Ждать «готово» не дольше, часов', 'int', '', 1, 48),
    ('pool_low', 'Предупреждать, когда почт осталось не больше', 'int', '', 0, 1000),
    ('address_text', 'Текст с адресом ({order}, {email})', 'longtext', '', None, None),
    ('link_text', 'Текст со ссылкой ({order}, {link})', 'longtext', '', None, None),
    ('nolink_text', 'Текст «письмо не пришло» ({order})', 'longtext', '', None, None),
]


def panel():
    c = cfg()
    s = pool_counts()
    d = db()
    orders = sorted(d['orders'].values(), key=lambda o: o.get('updated', ''), reverse=True)
    counts = {}
    for o in orders:
        counts[o['state']] = counts.get(o['state'], 0) + 1
    warns = []
    if not [w for w in c['lot_keywords'].split(',') if w.strip()]:
        warns.append('Не задано ключевое слово лота: плагин ничего не делает.')
    if not token():
        warns.append('Не задан токен SmakMail (переменная SMAK_API_TOKEN или поле ниже).')
    if s is None:
        warns.append('Нет файла mailboxes.txt: загрузите ящики (форма ниже).')
    if c['link_pattern'] == magic_link_auto.DEFAULT_PATTERN:
        warns.append('Шаблон ссылки стоит по умолчанию и не сверен с реальным письмом платформы.')
    stat = [['Токен SmakMail', 'задан' if token() else 'нет'],
            ['Ящиков в файле', s['в файле'] if s else 0],
            ['Выдано / использовано / неисправно', f'{s["issued"]} / {s["used"]} / {s["bad"]}' if s else '—'],
            ['Ещё не проверялись', s['не проверялись'] if s else 0],
            ['Автовыдача адреса', 'включена' if c['auto_send'] else 'выключена (кнопками)'],
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
        rows.append({'cells': ['#' + o['id'], o.get('title', '')[:40], o.get('paid_at', '')[5:16].replace('T', ' '),
                               o.get('email', '') if st not in ('skipped',) else '', STATES.get(st, st), o.get('note', '')], 'buttons': b})
    return {
        'warnings': warns,
        'status': stat,
        'settings': {'action': 'save_settings', 'fields': [
            {'key': k, 'label': lb, 'type': tp, 'help': hp, 'min': mn, 'max': mx, 'value': c[k]} for k, lb, tp, hp, mn, mx in FIELDS]},
        'forms': [
            {'title': 'Токен SmakMail API', 'help': 'Нужны права mail.read. Токен сохраняется в файл на сервере и обратно на экран не выводится. Если токен попадал в переписку, перевыпустите его.',
             'action': 'set_token', 'kind': 'secret', 'label': 'Токен', 'button': 'Сохранить токен'},
            {'title': 'Добавить ящики', 'help': 'По ящику на строку: адрес:пароль. Пароли хранятся только в mailboxes.txt на сервере и обратно не показываются. Дубли пропускаются.',
             'action': 'add_mailboxes', 'kind': 'longtext', 'label': 'Ящики', 'button': 'Добавить'}],
        'buttons': [{'label': 'Проверить 5 ящиков (только чтение)', 'action': 'check_pool', 'data': {'limit': 5}}],
        'tables': [{'title': 'Заказы (последние 40)', 'columns': ['Заказ', 'Лот', 'Оплачен', 'Почта', 'Состояние', 'Примечание'], 'rows': rows}],
    }


def a_save_settings(b):
    cur, new = cfg(), {}
    for k, lb, tp, hp, mn, mx in FIELDS:
        if k not in b:
            new[k] = cur[k]
            continue
        v = b[k]
        if tp == 'bool':
            if not isinstance(v, bool):
                raise_user(f'«{lb}»: нужно да/нет.')
        elif tp == 'int':
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not mn <= v <= mx:
                raise_user(f'«{lb}»: число от {mn} до {mx}.')
            v = int(v)
        else:
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
            elif k == 'ready_words':
                if not [w for w in v.split(',') if w.strip()]:
                    raise_user('Слова «готово»: нужно хотя бы одно (пустой список принял бы и системные сообщения чата).')
            elif len(v) > 300:
                raise_user(f'«{lb}»: не длиннее 300 символов.')
        new[k] = v
    A.save_settings(new)
    A.log('настройки изменены: ' + ', '.join(k for k in b if k in new and new[k] != cur[k]) )
    return {'ok': True}


def a_set_token(b):
    t = str(b.get('value', '')).strip()
    if not SECRET_RE.fullmatch(t):
        raise_user('Токен выглядит неверно (пробелы или слишком короткий).')
    secret_file('smak_token.txt', t)
    A.log('токен SmakMail сохранён')
    return {'note': 'Токен сохранён.'}


def a_add_mailboxes(b):
    text = str(b.get('value', ''))
    have = set()
    try:
        with open(_path('mailboxes.txt'), encoding='utf-8-sig') as f:
            for line in f.read().splitlines():
                if ':' in line and not line.startswith('#'):
                    have.add(line.split(':', 1)[0].strip().lower())
    except OSError:
        pass
    add, bad, dup = [], 0, 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ':' not in line:
            bad += 1
            continue
        addr, pw = line.split(':', 1)
        addr, pw = addr.strip().lower(), pw.strip()
        if '@' not in addr or ' ' in addr or not pw:
            bad += 1
        elif addr in have:
            dup += 1
        else:
            have.add(addr)
            add.append(f'{addr}:{pw}')
    if add:
        p = _path('mailboxes.txt')
        new_file = not os.path.exists(p)
        with open(p, 'a', encoding='utf-8') as f:
            if not new_file and os.path.getsize(p) and not _ends_with_newline(p):
                f.write('\n')
            f.write('\n'.join(add) + '\n')
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    A.log(f'ящики: добавлено {len(add)}, дублей {dup}, неверных строк {bad}')
    return {'note': f'Добавлено {len(add)}, уже были {dup}, неверных строк {bad}.'}


def _ends_with_newline(p):
    with open(p, 'rb') as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) == b'\n'


def a_check_pool(b):
    if not token():
        raise_user('Не задан токен SmakMail.')
    try:
        items = pool().read_pool()[:max(1, min(int(b.get('limit', 5)), 10))]
    except PoolError as e:
        raise_user(str(e))
    tot = {EMPTY: 0, HAS_MAIL: 0, BAD: 0, UNKNOWN: 0}
    for addr, pw in items:
        tot[check_mailbox(addr, pw, token())] += 1
        time.sleep(0.2)
    return {'note': f'Проверено {len(items)}: свободных {tot[EMPTY]}, с письмами {tot[HAS_MAIL]}, неверный пароль/нет ящика {tot[BAD]}, неопределённо {tot[UNKNOWN]}. Статусы не менялись.'}


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
    global A, POOL
    A = api
    POOL = Pool(token=None, pool_file=os.path.join(api.data_dir, 'mailboxes.txt'), state_file=os.path.join(api.data_dir, 'pool_state.json'))
    api.on_orders(on_orders)
    api.every(1, tick, 'выдача адресов и ссылок')
    api.panel(panel)
    api.action('save_settings', a_save_settings)
    api.action('set_token', a_set_token)
    api.action('add_mailboxes', a_add_mailboxes)
    api.action('check_pool', a_check_pool)
    api.action('give_address', a_give_address)
    api.action('give_link', a_give_link)
