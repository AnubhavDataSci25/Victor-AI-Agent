@echo off
setlocal
title Victor AI Agent

echo =======================================================
echo               VICTOR AI AGENT LAUNCHER
echo =======================================================
echo.

:: 1. Verify that the project directory exists
if not exist "E:\Victor AI Agent" (
    echo [ERROR] Project directory not found: E:\Victor AI Agent
    echo Please verify that the drive is connected and the directory exists.
    echo.
    pause
    exit /b 1
)

:: 2. Navigate to project root (works from any drive or directory)
echo [1/3] Navigating to E:\Victor AI Agent...
cd /d "E:\Victor AI Agent"
if errorlevel 1 (
    echo [ERROR] Failed to navigate to directory: E:\Victor AI Agent
    echo.
    pause
    exit /b 1
)

:: 3. Locate and activate the Python virtual environment
echo [2/3] Activating Python virtual environment...
set "VENV_ACTIVATE="
if exist "E:\Victor AI Agent\.venv\Scripts\activate.bat" (
    set "VENV_ACTIVATE=E:\Victor AI Agent\.venv\Scripts\activate.bat"
) else if exist "E:\Victor AI Agent\venv\Scripts\activate.bat" (
    set "VENV_ACTIVATE=E:\Victor AI Agent\venv\Scripts\activate.bat"
)

if "%VENV_ACTIVATE%"=="" (
    echo [ERROR] Virtual environment not found in E:\Victor AI Agent\.venv or E:\Victor AI Agent\venv
    echo Please ensure the Python virtual environment is installed.
    echo.
    pause
    exit /b 1
)

call "%VENV_ACTIVATE%"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment at: %VENV_ACTIVATE%
    echo.
    pause
    exit /b 1
)

:: 4. Launch Victor AI Agent
:: Note: The application entry point is app.main (which executes uvicorn.run("app.main:app")).
:: We run the requested command python -m app.main:app, with seamless fallback to python -m app.main.
echo [3/3] Starting Victor AI Agent...
echo Command: python -m app.main:app
echo.

python -m app.main:app %* 2>nul || python -m app.main %*

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo =======================================================
echo  Victor process stopped (Exit Code: %EXIT_CODE%).
echo =======================================================
echo.
pause
