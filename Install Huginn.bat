@echo off
rem Opens Huginn's installer: a window where you choose where Huginn goes and what it sets up.
rem Nothing is installed until you press Install. It installs for you only (no admin rights needed).
if not exist "%~dp0installer\install.ps1" (
    echo Please unzip the whole Huginn folder first ^(right-click the zip, Extract All^), then run this again.
    pause
    exit /b 1
)
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0installer\install.ps1" %*
