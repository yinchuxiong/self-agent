@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set PYTHON=C:\Users\yincx\AppData\Local\Programs\Python\Python311\python.exe

echo ============================================
echo   Killing existing processes...
echo ============================================

:: Kill processes by port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   Killing PID %%a (port 8000)
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo   Killing PID %%a (port 5173)
    taskkill /f /pid %%a >nul 2>&1
)

:: Kill by window title
taskkill /fi "WINDOWTITLE eq self-agent-backend*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq self-agent-frontend*" /f >nul 2>&1

echo.
echo ============================================
echo   Starting services...
echo ============================================
echo.

if not exist "%PYTHON%" (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

echo [1/2] Starting backend: http://localhost:8000
start "self-agent-backend" "%PYTHON%" -m uvicorn self_agent.app.main:app --host 0.0.0.0 --port 8000 --reload

timeout /t 2 /nobreak >nul

echo [2/2] Starting frontend: http://localhost:5173
cd frontend
start "self-agent-frontend" npm run dev
cd ..

echo.
echo ============================================
echo   Backend:  http://localhost:8000/docs
echo   Frontend: http://localhost:5173
echo ============================================
pause
