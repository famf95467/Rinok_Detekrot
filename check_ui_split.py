# -*- coding: utf-8 -*-
"""Проверка разбиения ui/ (FunPay Detector). Запуск:
  python check_ui_split.py --ui ui --orig ui_orig [--html ui.html]
(а) сборка из ИСХОДНЫХ частей (--orig) по manifest.txt совпадает с ui.html до байта (нужен --html: файл, который сейчас раздаёт сервер);
(б) разница между исходной и новой сборкой: какие части изменились и что именно (unified diff в check_diff.txt);
плюс проверка JS (node --check, если node есть) и что сборка и manifest согласованы."""
import argparse, difflib, hashlib, os, shutil, subprocess, sys, tempfile, re


def parts(d):
    names = [l.strip() for l in open(os.path.join(d, 'manifest.txt'), encoding='utf-8') if l.strip() and not l.startswith('#')]
    missing = [n for n in names if not os.path.isfile(os.path.join(d, n))]
    if missing:
        sys.exit('СТОП: в manifest.txt есть файлы, которых нет в папке: ' + ', '.join(missing))
    return names


def build(d):
    return {n: open(os.path.join(d, n), 'rb').read() for n in parts(d)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ui', required=True)
    ap.add_argument('--orig', required=True)
    ap.add_argument('--html', default='')
    ap.add_argument('--out', default='check_diff.txt')
    a = ap.parse_args()
    orig, new = build(a.orig), build(a.ui)
    ok = True
    print('(а) сборка исходных частей против ui.html')
    if a.html and os.path.isfile(a.html):
        ref = open(a.html, 'rb').read()
        same = b''.join(orig.values()) == ref
        print(f'    {"СОВПАДАЕТ до байта" if same else "НЕ СОВПАДАЕТ"}: части {len(b"".join(orig.values()))} Б, ui.html {len(ref)} Б, md5 {hashlib.md5(b"".join(orig.values())).hexdigest()[:8]} / {hashlib.md5(ref).hexdigest()[:8]}')
        ok &= same
    else:
        print('    ПРОПУЩЕНО: не дан --html (файл ui.html, который сейчас раздаёт сервер)')
    print('(б) что изменилось между исходными частями и новыми')
    changed = [n for n in new if orig.get(n) != new[n]]
    print('    изменённые части:', ', '.join(changed) or 'нет')
    print('    порядок и состав манифеста:', 'тот же' if list(orig) == list(new) else 'ИЗМЕНИЛСЯ')
    ok &= list(orig) == list(new)
    with open(a.out, 'w', encoding='utf-8') as f:
        for n in changed:
            x = orig[n].decode('utf-8').splitlines(True)
            y = new[n].decode('utf-8').splitlines(True)
            f.write(''.join(difflib.unified_diff(x, y, 'было/' + n, 'стало/' + n, n=0)) + '\n')
    total_add = sum(len(new[n]) - len(orig[n]) for n in changed)
    print(f'    размер сборки: было {sum(map(len, orig.values()))} Б, стало {sum(map(len, new.values()))} Б (+{total_add} Б); построчная разница в {a.out}')
    html = b''.join(new.values()).decode('utf-8')
    scripts = re.findall(r'<script>([\s\S]*?)</script>', html)
    if shutil.which('node') and scripts:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as t:
            t.write('\n'.join(scripts))
        r = subprocess.run(['node', '--check', t.name], capture_output=True, text=True)
        print('    JS (node --check):', 'ок' if r.returncode == 0 else 'ОШИБКА ' + r.stderr[:300])
        ok &= r.returncode == 0
    else:
        print('    JS: пропущено (нет node или скриптов)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
