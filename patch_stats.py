# -*- coding: utf-8 -*-
"""Один раз подключает «Статистику» во вкладку «Аккаунт» detector_app.py.
Положите рядом stats_tab.py. Запуск: python patch_stats.py
Делает копию detector_app.py.bak. Если какое-то место не найдено, ничего не меняет."""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, 'detector_app.py')
src = open(path, encoding='utf-8').read()
if 'stats_tab' in src:
    sys.exit('Уже подключено, ничего не делаю.')
if not os.path.exists(os.path.join(HERE, 'stats_tab.py')):
    sys.exit('Рядом нет stats_tab.py. Положите его в эту папку.')

E = [
    ("import account_tab as acc          # вкладка «Аккаунт»",
     "import account_tab as acc          # вкладка «Аккаунт»\nimport stats_tab as stats          # статистика"),
    ("        if self.path.startswith('/api/acc/'):\n            return self._send(*acc.handle('POST', self.path, body))\n",
     "        if self.path.startswith('/api/stat/'):\n            return self._send(*stats.handle('POST', self.path, body))\n"
     "        if self.path.startswith('/api/acc/'):\n            return self._send(*acc.handle('POST', self.path, body))\n"),
    ("# ---------- сервер ----------",
     "stats.CTX['prices'] = api_prices\nPAGE = (PAGE.replace('<div id=\"ac-edit\"', stats.HTML + '<div id=\"ac-edit\"', 1)\n"
     "        .replace('/* ---------- вкладки ---------- */', stats.JS + '\\n/* ---------- вкладки ---------- */', 1))\n\n\n"
     "# ---------- сервер ----------"),
]
for old, new in E:
    if src.count(old) != 1:
        sys.exit(f'СТОП: не нашёл ровно одно место для правки: {old[:60]!r}. Файл не изменён. Пришлите мне этот вывод.')
    src = src.replace(old, new, 1)
shutil.copyfile(path, path + '.bak')
open(path, 'w', encoding='utf-8').write(src)
print('Готово. Копия: detector_app.py.bak. Запускайте «Запустить.bat», в «Аккаунте» появится блок «Статистика».')
