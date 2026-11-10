# -*- coding: utf-8 -*-
"""Правит account_tab.py и funpay_manage.py (рядом с этим файлом). Делает копии .bak.
1) Запрос поднятия: game_id, node_id и node_ids[] (как второй запрос браузера, 44 байта; так же шлёт Cardinal).
2) funpay_manage: шлёт cookie_prefs=1 (настройка cookie, как в браузере и в Cardinal) и запоминает cookie,
   которые сайт сам выдаёт в ответах на наши запросы (кроме golden_key и fav_games). В manage_log.csv
   пишутся только ИМЕНА таких cookie, значения не пишутся. Значения из браузера не копируются.
Если какое-то место не найдено, ничего не меняет."""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def patch(name, edits, marker):
    path = os.path.join(HERE, name)
    src = open(path, encoding='utf-8').read()
    if marker in src:
        print(f'{name}: уже применено.')
        return None
    for variants in edits:
        hits = [(o, n) for o, n in variants if src.count(o) == 1]
        if len(hits) != 1:
            sys.exit(f'СТОП ({name}): не нашёл ровно одно место: {variants[0][0][:70]!r}. Ничего не изменено.')
        src = src.replace(hits[0][0], hits[0][1], 1)
    return path, src


NEW_DATA = "data=[('game_id', str(game)), ('node_id', str(node_id)), ('node_ids[]', str(node_id))], referer=page)"
acc = patch('account_tab.py', [[
    ("data={'game_id': str(game), 'node_id': str(node_id)}, referer=page)", NEW_DATA),
    ("data={'game_id': str(game), 'node_id': str(node_id), 'csrf_token': tok}, referer=page)", NEW_DATA),
]], "('node_ids[]'")

fm = patch('funpay_manage.py', [
    [("    cookie = '; '.join([f'golden_key={key}'] + [f'{k}={v}' for k, v in JAR.items()])",
      "    jar = {'cookie_prefs': '1'}\n    jar.update(JAR)\n"
      "    cookie = '; '.join([f'golden_key={key}'] + [f'{k}={v}' for k, v in jar.items()])")],
    [("    for c in hdr.get_all('Set-Cookie') or []:\n"
      "        m = re.match(r'\\s*(PHPSESSID)=([^;]*)', c)\n"
      "        if m:\n"
      "            JAR[m.group(1)] = m.group(2)\n",
      "    names = []\n"
      "    for c in hdr.get_all('Set-Cookie') or []:\n"
      "        m = re.match(r'\\s*([A-Za-z0-9_.\\-]+)=([^;]*)', c)\n"
      "        if m and m.group(1) not in ('golden_key', 'fav_games') and m.group(2):\n"
      "            JAR[m.group(1)] = m.group(2)\n"
      "            names.append(m.group(1))\n")],
    [("    log(('POST ' if data is not None else '') + path, status)",
      "    log(('POST ' if data is not None else '') + path + (' [Set-Cookie: ' + ','.join(names) + ']' if names else ''), status)")],
], 'cookie_prefs')

for r, name in ((acc, 'account_tab.py'), (fm, 'funpay_manage.py')):
    if r:
        shutil.copyfile(r[0], r[0] + '.bak')
        open(r[0], 'w', encoding='utf-8').write(r[1])
        print(f'{name}: готово, копия {name}.bak')
print('Перезапустите программу.')
