# -*- coding: utf-8 -*-
"""Один раз подключает «Напоминания о подтверждении» во вкладку «Аккаунт».
Нужно, чтобы уже был применён patch_chat.py. Положите рядом remind_tab.py. Запуск: python patch_remind.py
Делает копию detector_app.py.bak. Если какое-то место не найдено, ничего не меняет."""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, 'detector_app.py')
src = open(path, encoding='utf-8').read()
if 'remind_tab' in src:
    sys.exit('Уже подключено, ничего не делаю.')
if 'chat_tab' not in src:
    sys.exit('Сначала примените patch_chat.py (напоминания отправляются через модуль сообщений).')
for f in ('remind_tab.py', 'chat_tab.py'):
    if not os.path.exists(os.path.join(HERE, f)):
        sys.exit(f'Рядом нет {f}. Положите его в эту папку.')

E = [
    ("import account_tab as acc          # вкладка «Аккаунт»",
     "import account_tab as acc          # вкладка «Аккаунт»\nimport remind_tab as remind        # напоминания о подтверждении"),
    ("        if self.path.startswith('/api/acc/'):\n            return self._send(*acc.handle('POST', self.path, body))\n",
     "        if self.path.startswith('/api/remind/'):\n            return self._send(*remind.handle('POST', self.path, body))\n"
     "        if self.path.startswith('/api/acc/'):\n            return self._send(*acc.handle('POST', self.path, body))\n"),
    ("# ---------- сервер ----------",
     "PAGE = (PAGE.replace('<div id=\"ac-edit\"', remind.HTML + '<div id=\"ac-edit\"', 1)\n"
     "        .replace('/* ---------- вкладки ---------- */', remind.JS + '\\n/* ---------- вкладки ---------- */', 1))\n\n\n"
     "# ---------- сервер ----------"),
]
for old, new in E:
    if src.count(old) != 1:
        sys.exit(f'СТОП: не нашёл ровно одно место для правки: {old[:60]!r}. Файл не изменён. Пришлите мне этот вывод.')
    src = src.replace(old, new, 1)
shutil.copyfile(path, path + '.bak')
open(path, 'w', encoding='utf-8').write(src)
print('Готово. Копия: detector_app.py.bak. Запускайте «Запустить.bat», в «Аккаунте» появится блок «Напоминания о подтверждении заказа».')
