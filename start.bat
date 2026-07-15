@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set PYTHON=C:\Users\yincx\AppData\Local\Programs\Python\Python311\python.exe

if not exist "%PYTHON%" (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

echo Python:
%PYTHON% --version
echo.

if not exist "frontend\node_modules\" (
    echo [1/3] Installing frontend deps...
    cd frontend
    call npm install
    cd ..
    echo.
)

echo [2/3] Starting backend: http://localhost:8000
start "self-agent-backend" "%PYTHON%" -m uvicorn self_agent.app.main:app --host 0.0.0.0 --port 8000 --reload

timeout /t 2 /nobreak >nul

echo [3/3] Starting frontend: http://localhost:5173
cd frontend
start "self-agent-frontend" npm run dev
cd ..

echo.
echo ============================================
echo   Backend:  http://localhost:8000/docs
echo   Frontend: http://localhost:5173
echo   Close the two terminal windows to stop.
echo ============================================
pause