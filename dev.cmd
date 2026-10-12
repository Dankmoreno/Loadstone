@echo off
REM Tareas de desarrollo de Loadstone. Sin esto, los comandos viven en la
REM memoria de quien los escribio y se pierden.
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo No hay entorno virtual. Crealo con:
    echo     python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -e .[dev]
    exit /b 1
)

if "%1"=="" goto ayuda
if "%1"=="test"     goto test
if "%1"=="lint"     goto lint
if "%1"=="fix"      goto fix
if "%1"=="check"    goto check
if "%1"=="gui"      goto gui
if "%1"=="build"    goto build
if "%1"=="logs"     goto logs
goto ayuda

:test
"%PY%" -m pytest -q
exit /b %ERRORLEVEL%

:lint
"%PY%" -m ruff check .
exit /b %ERRORLEVEL%

:fix
"%PY%" -m ruff check --fix .
"%PY%" -m ruff format .
exit /b %ERRORLEVEL%

:check
"%PY%" -m ruff check . && "%PY%" -m pytest -q
exit /b %ERRORLEVEL%

:gui
"%PY%" -m loadstone --debug
exit /b %ERRORLEVEL%

:build
"%PY%" -m PyInstaller packaging\loadstone.spec --noconfirm --distpath dist --workpath build
if errorlevel 1 exit /b 1
dist\Loadstone\Loadstone.exe --selftest
if errorlevel 1 (echo La autocomprobacion del ejecutable ha fallado & exit /b 1)
echo Compilacion correcta: dist\Loadstone\
exit /b 0

:logs
"%PY%" -c "from loadstone.core.logs import log_file; print(log_file())"
exit /b 0

:ayuda
echo Uso: dev ^<tarea^>
echo.
echo   test    ejecuta las pruebas
echo   lint    revisa el estilo
echo   fix     corrige y formatea lo que se pueda
echo   check   lint + test, como la integracion continua
echo   gui     abre la aplicacion con registro detallado
echo   build   genera el ejecutable y lo autocomprueba
echo   logs    muestra donde esta el archivo de registro
exit /b 1
