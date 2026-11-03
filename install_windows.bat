@echo off
setlocal
cd /d "%~dp0"
py -m pip install .
if errorlevel 1 (
 echo [ERROR] Package installation failed.
 pause
 exit /b 1
)
py -m M_TSE --data-dir "%~dp0tse_data" init
if errorlevel 1 (
 echo [ERROR] Archive initialization failed.
 pause
 exit /b 1
)
echo Installation and local TDA archive initialization completed.
echo Run: py -m M_TSE --data-dir "%~dp0tse_data" status
pause
