@echo off
rem Run as Administrator. Starts the portal at Windows startup, opens the firewall port and schedules a daily backup.
net session >nul 2>&1
if not %errorlevel%==0 (echo Please right-click this file and choose "Run as administrator" & pause & exit /b 1)

set DIR=%~dp0
set NETDIR=\\192.168.20.6\Express\HRPortal_Windows\HRPortal

schtasks /create /tn "HR Master Portal" /tr "\"%DIR%start.bat\"" /sc onstart /ru SYSTEM /rl HIGHEST /f
schtasks /create /tn "HR Master Portal Backup" /tr "\"%NETDIR%\backup.bat\"" /sc daily /st 22:00 /ru SYSTEM /f
netsh advfirewall firewall add rule name="HR Master Portal" dir=in action=allow protocol=TCP localport=8080

echo.
echo Done. Restart the server (or run start.bat) and open http://192.168.20.165:8080
pause
