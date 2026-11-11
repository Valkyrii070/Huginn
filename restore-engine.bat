@echo off
rem Puts the standard browser engine (without H.264/AAC) back. Close Huginn first.
cd /d "%~dp0"
title Huginn - restore standard engine
"%~dp0python\python.exe" -u "%~dp0engine\build_engine.py" --restore
echo.
echo You can close this window.
pause >nul
