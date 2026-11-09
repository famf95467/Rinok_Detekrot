@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto nopython
%PY% detector_app.py
if errorlevel 1 goto failed
exit /b 0
:nopython
echo.
echo Не найден Python. Установите Python 3 с сайта python.org и поставьте галочку Add Python to PATH.
echo Потом запустите этот файл снова.
pause
exit /b 1
:failed
echo.
echo Программа не запустилась или закрылась с ошибкой. Причина написана выше.
echo Скопируйте весь текст этого окна и пришлите его мне.
pause
exit /b 1
