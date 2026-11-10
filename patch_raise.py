# -*- coding: utf-8 -*-
"""Правит account_tab.py: запрос поднятия шлёт только game_id и node_id (как браузер),
без csrf_token; в ответе показывает время ожидания (wait, unlock_at).
Запуск: python patch_raise.py (рядом с account_tab.py). Делает копию account_tab.py.bak.
Если какое-то место не найдено ровно один раз, ничего не меняет."""
import os, shutil, sys

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'account_tab.py')
src = open(path, encoding='utf-8').read()
if "'game_id': str(game), 'node_id': str(node_id)}" in src:
    sys.exit('Уже применено.')

E = [
    ("    tok = fm.app_data(html).get('csrf-token')\n    if btn is None or not game or not tok:",
     "    if btn is None or not game:"),
    ("('номер игры (data-game)' if not game else 'csrf-токен')",
     "'номер игры (data-game)'"),
    ("data={'game_id': str(game), 'node_id': str(node_id), 'csrf_token': tok}, referer=page)",
     "data={'game_id': str(game), 'node_id': str(node_id)}, referer=page)"),
    ("        err, modal = j.get('error'), bool(j.get('modal'))\n",
     "        err, modal = j.get('error'), bool(j.get('modal'))\n"
     "        if j.get('wait'):\n"
     "            msg += f\" (ждать примерно {int(j['wait']) // 60} мин, до {j.get('unlock_at', '?')} UTC)\"\n"),
]
for old, new in E:
    if src.count(old) != 1:
        sys.exit(f'СТОП: не нашёл ровно одно место: {old[:60]!r}. Файл не изменён. Пришлите мне этот вывод.')
    src = src.replace(old, new, 1)
shutil.copyfile(path, path + '.bak')
open(path, 'w', encoding='utf-8').write(src)
print('Готово. Копия: account_tab.py.bak. Перезапустите программу.')
