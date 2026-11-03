@echo off
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
rem Execute after market hours via Task Scheduler; script does NOT schedule itself.
py -u examples\daily_archive.py >> logs\daily_archive.log 2>&1
exit /b %errorlevel%
