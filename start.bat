@echo off
REM Double-click entry point for Windows: hands off to start.sh through Git Bash.
setlocal

set "BASH=C:\Program Files\Git\bin\bash.exe"
if not exist "%BASH%" (
  where bash >nul 2>&1
  if errorlevel 1 (
    echo.
    echo Git Bash was not found. Install Git for Windows, or run start.sh from a bash shell.
    echo.
    pause
    exit /b 1
  )
  set "BASH=bash"
)

echo Starting TradeRevive AI...
"%BASH%" "%~dp0start.sh"
echo.
echo The server has stopped.
pause
