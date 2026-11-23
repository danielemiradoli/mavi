@echo off
rem Avvia MAVI e apre il browser. Il clone si sceglie nella pagina. Per fermarlo chiudi questa finestra.
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist clones\carne_cavallo\vault\context.db .venv\Scripts\python seed_carne_cavallo.py
if not exist clones\modigliani\vault\context.db .venv\Scripts\python seed_modigliani.py
echo.
echo MAVI e' in funzione su http://127.0.0.1:8000  -  chiudi questa finestra per fermarlo.
start "" cmd /c "timeout /t 3 >NUL & start http://127.0.0.1:8000/"
.venv\Scripts\python -m uvicorn app:app --port 8000
pause
