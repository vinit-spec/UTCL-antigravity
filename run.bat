@echo off
echo =====================================================================
echo   UTCL Bus Management System - LAN Production Server
echo =====================================================================
echo.
echo  Starting server...
echo.
echo  Access on THIS machine : http://localhost:8000
echo  Access on LAN (name)   : http://%COMPUTERNAME%:8000
echo.

REM Resolve and display actual LAN IP address
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4 Address"') do (
    set LAN_IP=%%a
    goto :showip
)
:showip
set LAN_IP=%LAN_IP: =%
echo  Access on LAN (IP)     : http://%LAN_IP%:8000
echo.
echo  WebSocket: Enabled (Flask-SocketIO / threading mode)
echo  Database : MySQL - configured in db_config.json
echo.
echo  NOTE: Share the LAN (IP) address above with other devices.
echo        Make sure Windows Firewall allows port 8000.
echo =====================================================================
echo.
:server_start
echo  [%DATE% %TIME%] Starting UTCL Bus Management Server process...
.venv\Scripts\python.exe server.py
echo.
echo  [%DATE% %TIME%] WARNING: Server process terminated (exit code: %ERRORLEVEL%).
echo  Auto-restarting in 3 seconds... Press Ctrl+C to abort.
timeout /t 3 >nul
goto :server_start
