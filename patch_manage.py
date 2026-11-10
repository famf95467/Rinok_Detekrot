# -*- coding: utf-8 -*-
"""Диагностика: при неожиданном ответе сайта (не 200) в ошибке покажутся путь запроса и заголовки ответа
(без cookie). Ничего не обходит и не повторяет. Запуск: python patch_manage.py (рядом с funpay_manage.py).
Делает копию funpay_manage.py.bak."""
import os, shutil, sys

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'funpay_manage.py')
src = open(path, encoding='utf-8').read()
old = "        raise Stop(f'Неожиданный ответ HTTP {status}. Ответ: {redact(text)[:300]}')"
new = ("        shown = '; '.join(f'{k}: {str(v)[:80]}' for k, v in hdr.items()\n"
       "                          if k.lower() not in ('set-cookie', 'cookie', 'authorization'))\n"
       "        raise Stop(f'Неожиданный ответ HTTP {status} на {\"POST \" if data is not None else \"\"}{path}. '\n"
       "                   f'Тело ответа: {redact(text)[:300] or \"(пустое)\"}. Заголовки: {shown[:700]}')")
if 'Заголовки:' in src:
    sys.exit('Уже применено.')
if src.count(old) != 1:
    sys.exit('СТОП: нужная строка не найдена ровно один раз. Файл не изменён.')
shutil.copyfile(path, path + '.bak')
open(path, 'w', encoding='utf-8').write(src.replace(old, new, 1))
print('Готово. Копия: funpay_manage.py.bak. Перезапустите программу.')
