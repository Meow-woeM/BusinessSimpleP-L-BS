@echo off
rem One-click launcher for Windows: creates a virtualenv on first run,
rem installs dependencies, opens the browser, and starts the app.
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    set "PYTHON=python"
)

if not exist .venv (
    echo First run: setting up Python environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create a virtual environment. Install Python 3.10+ from
        echo https://www.python.org/downloads/ and check "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo Starting Simple P^&L - your browser will open in a moment.
echo Close this window or use the Quit button in the app to stop.
python launcher.py
pause
