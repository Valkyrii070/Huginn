@echo off
rem One-time setup: puts a portable Python + PySide6 (+ cryptography, for Passwords) inside this folder.
rem Nothing is installed system-wide; delete the folder to remove everything.
rem The installer (Install Huginn.bat) runs this too and follows its STEP / Progress lines in setup.log.
setlocal
cd /d "%~dp0"
set "PYVER=3.12.10"
set "PYDIR=%~dp0python"
set "PYEXE=%PYDIR%\python.exe"
set "PYTHONUNBUFFERED=1"
echo [%date% %time%] setup started> setup.log

if not exist "%PYEXE%" (
    echo STEP python>> setup.log
    echo Downloading portable Python %PYVER% ...
    curl.exe -L --fail --silent --show-error -o python-embed.zip "https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip" >> setup.log 2>&1 || goto :fail
    mkdir "%PYDIR%" 2>nul
    tar -xf python-embed.zip -C "%PYDIR%" >> setup.log 2>&1 || goto :fail
    del python-embed.zip
    rem Enable site-packages (needed for pip) and this folder on sys.path.
    (echo python312.zip& echo .& echo Lib\site-packages& echo ..& echo import site)> "%PYDIR%\python312._pth"
)
"%PYEXE%" --version >> setup.log 2>&1 || goto :fail

"%PYEXE%" -m pip --version >nul 2>nul || (
    echo STEP pip>> setup.log
    echo Installing pip ...
    curl.exe -L --fail --silent --show-error -o get-pip.py "https://bootstrap.pypa.io/get-pip.py" >> setup.log 2>&1 || goto :fail
    "%PYEXE%" get-pip.py --no-warn-script-location >> setup.log 2>&1 || goto :fail
    del get-pip.py
)

rem PySide6 is upgraded on a rerun - unless an H.264 engine was built for it (engine\installed.json):
rem upgrading would swap that engine out. The engine's own Update... keeps it current instead.
set "UPGRADE=--upgrade"
if exist "%~dp0engine\installed.json" set "UPGRADE="
rem Download progress as "Progress <bytes> of <total>" lines, for the installer (pip 24.1 and later).
set "PROGRESS="
"%PYEXE%" -m pip install --help 2>nul | findstr /c:"raw]" >nul && set "PROGRESS=--progress-bar raw"
echo STEP engine>> setup.log
echo Installing PySide6 (about 250 MB, a few minutes) and the password manager's encryption library ...
"%PYEXE%" -m pip install --disable-pip-version-check --no-warn-script-location %PROGRESS% %UPGRADE% PySide6 cryptography >> setup.log 2>&1 || goto :fail
echo STEP check>> setup.log
"%PYEXE%" -c "import PySide6, PySide6.QtWebEngineWidgets, cryptography; print('PYSIDE_OK', PySide6.__version__)" >> setup.log 2>&1 || goto :fail
echo SETUP_OK>> setup.log
echo Setup finished.
exit /b 0

:fail
echo SETUP_FAILED>> setup.log
echo Setup failed - see setup.log in this folder.
exit /b 1
