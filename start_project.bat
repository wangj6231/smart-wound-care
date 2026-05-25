@echo off
title Smart Wound Care System - Service Starter

echo ===================================================
echo   Starting Smart Wound Care System and Ngrok...
echo ===================================================

echo.
echo 1. Starting MySQL Database Server...
start "" /B "D:\xampp\mysql\bin\mysqld.exe" --defaults-file="D:\xampp\mysql\bin\my.ini" --console
timeout /t 3 > nul

echo.
echo 2. Starting FastAPI Backend Server (http://127.0.0.1:8000)...
start "" /B "%~dp0venv\Scripts\uvicorn.exe" main:app --host 127.0.0.1 --port 8000 --reload
timeout /t 3 > nul

echo.
echo 3. Starting Ngrok Tunnel...
start "" /B "ngrok" http 8000
timeout /t 4 > nul

echo.
echo ===================================================
echo   Services started successfully!
echo   Local Address: http://127.0.0.1:8000/login.html
echo ===================================================
echo.

:: Query Ngrok URL using PowerShell
powershell -Command "try { $url = (Invoke-RestMethod -Uri http://127.0.0.1:4040/api/tunnels).tunnels.public_url; if ($url) { Write-Host 'Ngrok Public URL: ' $url '/login.html' -ForegroundColor Green } else { Write-Host 'Ngrok started, but could not get public URL.' -ForegroundColor Yellow } } catch { Write-Host 'Could not query Ngrok local API yet.' -ForegroundColor Red }"

echo.
echo ===================================================
echo   Note: Closing this window will stop all services!
echo ===================================================
echo.

pause
