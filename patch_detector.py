# -*- coding: utf-8 -*-
"""Один раз подключает вкладку «Аккаунт» к detector_app.py (0.8 -> 0.9).
Положите рядом: account_tab.py, funpay_manage.py. Запуск: python patch_detector.py
Делает копию detector_app.py.bak. Если какое-то место не найдено, ничего не меняет."""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(HERE, 'detector_app.py')
src = open(path, encoding='utf-8').read()
if 'account_tab' in src:
    sys.exit('Уже подключено, ничего не делаю.')

E = [
    ("MARKS_LOCK = threading.Lock()",
     "import account_tab as acc          # вкладка «Аккаунт»\nMARKS_LOCK = threading.Lock()"),
    ("VERSION = '0.8'", "VERSION = '0.9'"),
    ("\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; \"",
     "\"default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; \""),
    ("min(n, 10000)", "min(n, 200000)"),
    ("            if u.path == '/api/history':\n                return self._send(200, api_history())\n",
     "            if u.path == '/api/history':\n                return self._send(200, api_history())\n"
     "            if u.path.startswith('/api/acc/'):\n                return self._send(*acc.handle('GET', u.path, {}))\n"),
    ("        if self.path == '/api/quit':",
     "        if self.path.startswith('/api/acc/'):\n            return self._send(*acc.handle('POST', self.path, body))\n        if self.path == '/api/quit':"),
    ("$('v-hist').style.display=(v==='history')?'block':'none';",
     "$('v-hist').style.display=(v==='history')?'block':'none';\n  $('v-acc').style.display=(v==='acc')?'block':'none';"),
    ("$('bar-snap').style.display=(v==='data'||v==='history')?'none':'flex';",
     "$('bar-snap').style.display=(v==='data'||v==='history'||v==='acc')?'none':'flex';"),
    ("$('tab-hist').className='tab'+(v==='history'?' cur':'');",
     "$('tab-hist').className='tab'+(v==='history'?' cur':'');\n  $('tab-acc').className='tab'+(v==='acc'?' cur':'');"),
    ("if(v==='history')loadHist();", "if(v==='history')loadHist();\n  if(v==='acc')loadAcc();"),
    ("h==='prices'||h==='data'||h==='history'?h:'marks'", "h==='prices'||h==='data'||h==='history'||h==='acc'?h:'marks'"),
    ("# ---------- сервер ----------",
     "PAGE = (PAGE.replace('<button class=\"tab\" id=\"tab-hist\" type=\"button\">История</button></nav>',\n"
     "                     '<button class=\"tab\" id=\"tab-hist\" type=\"button\">История</button>'\n"
     "                     '<button class=\"tab\" id=\"tab-acc\" type=\"button\">Аккаунт</button></nav>', 1)\n"
     "        .replace('</main>\\n<script>', acc.HTML + '</main>\\n<script>', 1)\n"
     "        .replace('/* ---------- вкладки ---------- */', acc.JS + '\\n/* ---------- вкладки ---------- */', 1))\n\n\n"
     "# ---------- сервер ----------"),
]
for old, new in E:
    if src.count(old) != 1:
        sys.exit(f'СТОП: не нашёл ровно одно место для правки: {old[:60]!r}. Файл не изменён. Пришлите мне этот вывод.')
    src = src.replace(old, new, 1)
shutil.copyfile(path, path + '.bak')
open(path, 'w', encoding='utf-8').write(src)
print('Готово. Копия: detector_app.py.bak. Теперь запускайте «Запустить.bat», вкладка «Аккаунт» справа.')
