# -*- coding: utf-8 -*-
"""FunPay Менеджер, окно (версия 3.0). Запуск: python funpay_app.py
Нужны рядом: funpay_manage.py (версия 2 и новее). Python 3 с tkinter и beautifulsoup4.
Аватар: PNG/GIF показываются сразу, для JPG/WebP нужна библиотека Pillow (pip install pillow); без неё будет заглушка.

Вход: вставьте golden_key в поле либо нажмите «Войти по golden_key.txt». Ключ хранится только в памяти
программы; в файл он пишется только если вы поставите галочку «Запомнить» (простым текстом, как пароль:
не пересылайте файл). Программа не открывает чаты и заказы и переписку не хранит.

Защита: все запросы идут по одному, с паузой; при капче, 403/429 или выбросе на вход сессия блокируется
и ничего не повторяется и не обходится. Любое изменение лота показывается «было → стало» и уходит
только после вашего подтверждения. Безопасности от блокировки программа не гарантирует.
Адреса и разметка FunPay написаны по памяти и могут не совпасть: при несовпадении программа остановится и скажет.
"""
import io, os, queue, re, sys, threading, urllib.request
import tkinter as tk
from tkinter import ttk, messagebox
from bs4 import BeautifulSoup
import funpay_manage as m

m.MAX_REQUESTS = 300           # лимит запросов за сессию окна
m.PACE = (3, 6)                # пауза между запросами, секунд
KEYFILE = os.path.join(m.HERE, 'golden_key.txt')
LOCK_WORDS = ('Сайт ответил HTTP', 'капч', 'перенаправил')
REQ_LOCK = threading.Lock()
UI_FIELDS = [('title', 'Название', 'entry'), ('desc', 'Описание', 'text'), ('price', 'Цена, ₽', 'entry'),
             ('amount', 'Количество', 'entry'), ('auto', 'Автовыдача', 'check'),
             ('active', 'Лот активен (показывается)', 'check')]


# ---------- работа с сайтом (выполняется в фоне) ----------
def login(key):
    _, _, home = m.request('/', key)
    uid = m.app_data(home).get('userId')
    if not uid:
        raise m.Stop('Ключ не подошёл: сайт вас не узнал (нет ID). Проверьте golden_key.')
    soup = BeautifulSoup(home, 'html.parser')
    nick_el = soup.select_one('.user-link-name')
    nick = nick_el.get_text(strip=True) if nick_el else '(ник не найден в разметке)'
    url = None
    el = soup.select_one('.avatar-photo') or soup.select_one('.user-link-photo')
    if el:
        mt = re.search(r'url\(["\']?([^)"\']+)', el.get('style', ''))
        url = mt.group(1) if mt else None
    return {'uid': str(uid), 'nick': nick, 'avatar_url': url}


def fetch_avatar(url):
    if not url:
        return None
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        url = m.BASE + url
    if not re.match(r'https://([a-z0-9-]+\.)?(funpay|sfunpay)\.com/', url):
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': m.USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read(2 * 1024 * 1024)
    except Exception:
        return None


def make_photo(data, size=64):
    if not data:
        return None
    try:
        from PIL import Image, ImageTk
        return ImageTk.PhotoImage(Image.open(io.BytesIO(data)).convert('RGB').resize((size, size)))
    except Exception:
        pass
    try:
        img = tk.PhotoImage(data=data)
        f = max(1, img.width() // size)
        return img.subsample(f, f)
    except Exception:
        return None


def load_offers(key, uid):
    _, _, prof = m.request(f'/users/{uid}/', key)
    soup = BeautifulSoup(prof, 'html.parser')
    rows = []
    for block in soup.select('div.offer'):
        title = block.select_one('.offer-list-title a')
        href = title.get('href', '') if title else ''
        node = (re.search(r'/lots/(\d+)/', href) or [None, ''])[1]
        section = title.get_text(' ', strip=True) if title else '?'
        for it in block.select('a.tc-item'):
            t, p, am = it.select_one('.tc-desc-text'), it.select_one('.tc-price'), it.select_one('.tc-amount')
            rows.append({'id': it.get('href', '').split('id=')[-1], 'node': node, 'раздел': section,
                         'название': t.get_text(' ', strip=True) if t else '',
                         'цена': p.get_text(' ', strip=True) if p else '',
                         'кол-во': am.get_text(strip=True) if am else ''})
    if not rows:
        raise m.Stop('На странице профиля лоты не найдены: разметка другая или лотов нет.')
    return rows


def load_form(key, node, offer):
    page = f'/lots/offerEdit?node={node}&offer={offer}'
    _, _, html = m.request(page, key)
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', class_=re.compile('offer|edit', re.I)) or soup.find('form')
    if not form:
        raise m.Stop('Форма редактирования не найдена. Ничего не отправлено.')
    fields, boxes, cbs = m.form_fields(form)
    return {'page': page, 'html': html, 'form': form, 'fields': fields, 'boxes': boxes, 'cbs': cbs}


def save_trade_page(key, node):
    _, _, html = m.request(f'/lots/{node}/trade', key)
    os.makedirs(os.path.join(m.HERE, 'pages_own'), exist_ok=True)
    out = os.path.join(m.HERE, 'pages_own', f'trade_{node}.htm')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(m.redact(html))
    soup = BeautifulSoup(html, 'html.parser')
    hits = [e for e in soup.find_all(['a', 'button']) if re.search(r'подн|raise', e.get_text(' ') + ' '.join(e.get('class', [])), re.I)]
    lines = [f'Страница сохранена: {out}']
    if not hits:
        lines.append('Кнопка «поднять» в разметке не найдена. Пришлите файл разработчику.')
    for e in hits[:5]:
        lines.append(f'<{e.name}> «{e.get_text(" ", strip=True)[:40]}» {dict((k, v) for k, v in e.attrs.items() if k != "style")}')
    return '\n'.join(lines)


def find_name(alias, names):
    c = [n for n in names if re.search(m.ALIASES[alias], n, re.I)]
    ru = [n for n in c if '[ru]' in n]
    return c[0] if len(c) == 1 else (ru[0] if len(ru) == 1 else None)


# ---------- окно ----------
class App:
    def __init__(self, root):
        self.root, self.key, self.me, self.rows = root, None, None, []
        self.locked, self.photo = False, None
        self.q = queue.Queue()
        self.status = tk.StringVar(value='Не выполнен вход')
        root.title('FunPay Менеджер')
        root.geometry('980x640')
        orig_log = m.log
        m.log = lambda path, status: (orig_log(path, status), self.q.put(('log', None, f'{path} → HTTP {status}')))
        ttk.Label(root, textvariable=self.status, relief='sunken', anchor='w').pack(side='bottom', fill='x')
        self.body = ttk.Frame(root)
        self.body.pack(fill='both', expand=True)
        self.login_screen()
        self.poll()

    # --- фон ---
    def run_bg(self, fn, ok, label='Работаю...'):
        if self.locked:
            messagebox.showwarning('Сессия остановлена', 'Сайт ответил блокировкой или проверкой. Новые запросы отключены.\n'
                                   'Закройте программу и сообщите «Бизнесс» через пользователя.')
            return
        self.status.set(label)

        def work():
            try:
                with REQ_LOCK:
                    res = fn()
                self.q.put(('ok', ok, res))
            except m.Stop as s:
                self.q.put(('stop', None, str(s)))
            except Exception as e:
                self.q.put(('err', None, f'{type(e).__name__}: {e}'))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, cb, data = self.q.get_nowait()
                if kind == 'log' and hasattr(self, 'log'):
                    self.log.insert('end', data + '\n')
                    self.log.see('end')
                elif kind == 'ok':
                    self.status.set(f'Готово. Запросов в сессии: {m.sent}')
                    cb(data)
                elif kind in ('stop', 'err'):
                    self.status.set('Остановлено' if kind == 'stop' else 'Ошибка')
                    if kind == 'stop' and any(w in data for w in LOCK_WORDS):
                        self.locked = True
                        data += '\n\nСессия заблокирована: программа ничего не повторяет и не обходит. Сообщите «Бизнесс» через пользователя.'
                    messagebox.showerror('Остановлено' if kind == 'stop' else 'Ошибка', data)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    # --- вход ---
    def login_screen(self):
        self.clear()
        f = ttk.Frame(self.body, padding=30)
        f.place(relx=0.5, rely=0.4, anchor='center')
        ttk.Label(f, text='Вход в FunPay', font=('', 16, 'bold')).pack(pady=(0, 10))
        ttk.Label(f, text='Вставьте cookie golden_key. Ключ даёт полный доступ к аккаунту, никому его не отправляйте.',
                  wraplength=440).pack()
        self.key_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.key_var, show='•', width=52).pack(pady=8)
        self.remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='Запомнить в golden_key.txt на этом ПК (простым текстом)', variable=self.remember).pack()
        ttk.Button(f, text='Войти', command=lambda: self.do_login(self.key_var.get().strip())).pack(pady=8)
        if os.path.exists(KEYFILE):
            ttk.Separator(f).pack(fill='x', pady=6)
            ttk.Label(f, text='Найден файл golden_key.txt').pack()
            ttk.Button(f, text='Войти по golden_key.txt', command=lambda: self.do_login(open(KEYFILE, encoding='utf-8').read().strip(), False)).pack(pady=4)
            ttk.Button(f, text='Удалить сохранённый ключ', command=self.forget_key).pack()

    def forget_key(self):
        if messagebox.askyesno('Удалить', 'Удалить golden_key.txt с этого ПК?'):
            try:
                os.remove(KEYFILE)
            except OSError:
                pass
            self.login_screen()

    def do_login(self, key, may_save=True):
        if not key:
            messagebox.showwarning('Нет ключа', 'Вставьте golden_key.')
            return
        remember = may_save and self.remember.get()

        def work():
            me = login(key)
            return me, fetch_avatar(me['avatar_url'])

        def ok(res):
            me, img = res
            self.key, self.me = key, me
            if remember:
                with open(KEYFILE, 'w', encoding='utf-8') as f:
                    f.write(key)
            self.photo = make_photo(img)
            self.key_var.set('')
            self.main_screen()
            self.refresh_offers()
        self.run_bg(work, ok, 'Вхожу...')

    def logout(self):
        self.key = self.me = None
        self.rows = []
        self.login_screen()
        self.status.set('Вы вышли, ключ стёрт из памяти программы')

    # --- главный экран ---
    def main_screen(self):
        self.clear()
        head = ttk.Frame(self.body, padding=10)
        head.pack(fill='x')
        if self.photo:
            ttk.Label(head, image=self.photo).pack(side='left', padx=(0, 12))
        else:
            c = tk.Canvas(head, width=64, height=64, highlightthickness=0)
            c.create_oval(2, 2, 62, 62, fill='#8a8fa3', outline='')
            c.create_text(32, 32, text=(self.me['nick'][:1] or '?').upper(), fill='white', font=('', 24, 'bold'))
            c.pack(side='left', padx=(0, 12))
        info = ttk.Frame(head)
        info.pack(side='left')
        ttk.Label(info, text=self.me['nick'], font=('', 14, 'bold')).pack(anchor='w')
        ttk.Label(info, text=f"ID: {self.me['uid']}").pack(anchor='w')
        ttk.Button(head, text='Выйти', command=self.logout).pack(side='right')
        nb = ttk.Notebook(self.body)
        nb.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.tab_offers(nb)
        self.tab_raise(nb)
        t = ttk.Frame(nb, padding=20)
        nb.add(t, text='Сообщения')
        ttk.Label(t, wraplength=700, text='Писать клиентам: следующий этап. Переписка не будет сохраняться и логироваться; '
                  'каждое сообщение уйдёт только после вашего подтверждения.').pack(anchor='w')
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text='Журнал')
        self.log = tk.Text(t, height=10, wrap='none')
        self.log.pack(fill='both', expand=True)
        self.log.insert('end', 'Здесь видны все запросы к сайту (без содержимого). Файл: manage_log.csv\n')

    def tab_offers(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text='Лоты')
        bar = ttk.Frame(t)
        bar.pack(fill='x', pady=(0, 6))
        ttk.Button(bar, text='Обновить список', command=self.refresh_offers).pack(side='left')
        ttk.Button(bar, text='Изменить выбранный лот', command=self.edit_selected).pack(side='left', padx=6)
        cols = ('id', 'раздел', 'название', 'цена', 'кол-во')
        self.tree = ttk.Treeview(t, columns=cols, show='headings', selectmode='browse')
        for c, w in zip(cols, (90, 170, 420, 90, 70)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor='w')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.edit_selected())

    def tab_raise(self, nb):
        t = ttk.Frame(nb, padding=20)
        nb.add(t, text='Поднятие')
        ttk.Label(t, wraplength=700, text='Поднятие предложений будет в версии 3.1. Адрес и форма запроса мне неизвестны точно, '
                  'поэтому сначала нужна страница вашего раздела. Выберите лот на вкладке «Лоты» и нажмите кнопку: '
                  'программа сохранит страницу раздела (токены вырезаны) и покажет найденную кнопку. Ничего не нажимается и не поднимается.').pack(anchor='w')
        ttk.Button(t, text='Сохранить страницу раздела выбранного лота', command=self.dump_trade).pack(anchor='w', pady=10)

    # --- действия ---
    def refresh_offers(self):
        self.run_bg(lambda: load_offers(self.key, self.me['uid']), self.show_offers, 'Загружаю лоты...')

    def show_offers(self, rows):
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert('', 'end', iid=r['id'], values=(r['id'], r['раздел'], r['название'], r['цена'], r['кол-во']))

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Выберите лот', 'Сначала выберите лот в списке.')
            return None
        return next(r for r in self.rows if r['id'] == sel[0])

    def dump_trade(self):
        r = self.selected()
        if r:
            self.run_bg(lambda: save_trade_page(self.key, r['node']), lambda s: messagebox.showinfo('Готово', s))

    def edit_selected(self):
        r = self.selected()
        if r:
            self.run_bg(lambda: load_form(self.key, r['node'], r['id']), lambda d: self.edit_dialog(r, d), 'Загружаю форму лота...')

    def edit_dialog(self, r, d):
        win = tk.Toplevel(self.root)
        win.title(f"Лот {r['id']}")
        win.geometry('620x520')
        names = set(d['fields']) | set(d['boxes'])
        widgets = {}
        f = ttk.Frame(win, padding=12)
        f.pack(fill='both', expand=True)
        for alias, label, kind in UI_FIELDS:
            real = find_name(alias, names)
            if not real:
                continue
            ttk.Label(f, text=label).pack(anchor='w', pady=(6, 0))
            if kind == 'entry':
                w = ttk.Entry(f)
                w.insert(0, d['fields'].get(real, ''))
                w.pack(fill='x')
            elif kind == 'text':
                w = tk.Text(f, height=8, wrap='word')
                w.insert('1.0', d['fields'].get(real, ''))
                w.pack(fill='x')
            else:
                w = tk.BooleanVar(value=real in d['fields'])
                ttk.Checkbutton(f, text=label, variable=w).pack(anchor='w')
            widgets[real] = (kind, w)
        if not widgets:
            ttk.Label(f, text='Поля формы не распознаны. Пришлите вывод команды inspect разработчику.').pack()

        def value(kind, w):
            return w.get('1.0', 'end-1c') if kind == 'text' else (('1' if w.get() else '0') if kind == 'check' else w.get().strip())

        def save():
            sets = []
            for real, (kind, w) in widgets.items():
                v = value(kind, w)
                cur = d['fields'].get(real, '')
                if kind == 'check':
                    if (v == '1') != (real in d['fields']):
                        sets.append(f'{real}={v}')
                elif v != cur:
                    sets.append(f'{real}={v}')
            if not sets:
                messagebox.showinfo('Без изменений', 'Вы ничего не изменили.', parent=win)
                return
            try:
                new, changes = m.apply_sets(d['fields'], d['boxes'], d['cbs'], sets)
            except SystemExit as e:
                messagebox.showerror('Ошибка', str(e), parent=win)
                return
            if not changes:
                messagebox.showinfo('Без изменений', 'Значения уже такие же.', parent=win)
                return
            text = '\n'.join(f'{n}: {m.mask(n, str(o))!r} → {m.mask(n, str(nw))!r}' for n, o, nw in changes)
            if not messagebox.askyesno('Подтвердите', f'Лот {r["id"]}. Было → стало:\n\n{text}\n\nОтправить на FunPay?', parent=win):
                return

            def done(res):
                status, resp = res
                messagebox.showinfo('Ответ сайта', f'HTTP {status}\n{resp}\n\nПрограмма не толкует ответ: проверьте лот на сайте.')
                win.destroy()
            self.run_bg(lambda: m.submit_form(self.key, d['form'], d['html'], new, d['page'], changes), done, 'Отправляю...')
        ttk.Button(win, text='Сохранить (покажу «было → стало»)', command=save).pack(pady=8)


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
