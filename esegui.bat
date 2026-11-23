@echo off
rem MAVI - prepara l'ambiente, esegue i controlli e prova il modello locale.
rem Tutto l'output finisce in esito.txt, nella stessa cartella.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo ==== MAVI %date% %time% ==== > esito.txt

rem Cerca Python: prima il launcher py, poi le installazioni per utente, infine python.
set PY=
where py >NUL 2>&1 && set PY=py
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set PY="%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY python --version >NUL 2>&1 && set PY=python
if not defined PY (
  echo PYTHON NON TROVATO: installalo e poi rilancia esegui.bat. >> esito.txt
  echo.
  echo  Python non e' installato su questo PC.
  echo  Installalo e poi rilancia esegui.bat.
  echo.
  pause
  exit /b 1
)

echo Lavoro in corso: non chiudere questa finestra. L'output va in esito.txt
%PY% --version >> esito.txt 2>&1
if not exist .venv\Scripts\python.exe (
  echo ---- creo l'ambiente Python ---- >> esito.txt
  %PY% -m venv .venv >> esito.txt 2>&1
)
echo ---- installo le dipendenze ---- >> esito.txt
.venv\Scripts\python -m pip install -q -r requirements.txt >> esito.txt 2>&1
echo ---- verifica.py ---- >> esito.txt
.venv\Scripts\python verifica.py >> esito.txt 2>&1
echo ---- prova_estrazione.py ---- >> esito.txt
.venv\Scripts\python prova_estrazione.py >> esito.txt 2>&1
echo ---- ollama ps (CPU o GPU) ---- >> esito.txt
ollama ps >> esito.txt 2>&1
echo ==== FINE %time% ==== >> esito.txt
echo.
echo  Finito. Puoi chiudere questa finestra.
pause
