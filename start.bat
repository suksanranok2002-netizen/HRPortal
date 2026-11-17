@echo off
cd /d "%~dp0"
set PORT=8080
where py >nul 2>nul
if %errorlevel%==0 (py -3 server.py --port %PORT%) else (python server.py --port %PORT%)
pause
