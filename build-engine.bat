@echo off
rem Rebuilds the browser engine with H.264/AAC video support (details: README.txt, "Video formats").
rem Safe to run again: it continues where it stopped, and later updates the engine when a
rem newer release is out. Progress is also written to engine\status.txt.
cd /d "%~dp0"
title Huginn engine build
if not exist "python\Lib\site-packages\PySide6" call setup.bat || goto :end
"%~dp0python\python.exe" -u "%~dp0engine\build_engine.py" %*
:end
echo.
echo You can close this window.
pause >nul
