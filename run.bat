@echo off
rem Starts the browser (runs setup first if needed).
cd /d "%~dp0"
if not exist "python\Lib\site-packages\PySide6" call setup.bat || exit /b 1
rem Passwords need the cryptography library (added in an update; a few MB, once).
if not exist "python\Lib\site-packages\cryptography" (
    echo Adding the encryption library for Passwords ...
    "%~dp0python\python.exe" -m pip install --disable-pip-version-check --no-warn-script-location cryptography >> setup.log 2>&1
)
start "" "%~dp0python\pythonw.exe" "%~dp0safari_browser.py" %*
