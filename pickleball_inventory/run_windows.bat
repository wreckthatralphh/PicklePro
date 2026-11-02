@echo off
cd /d "%~dp0"
echo Installing requirements...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)
echo.
echo Starting PicklePro at http://localhost:3000
echo Close this window or press Ctrl+C to stop.
start "" http://localhost:3000
python app.py
pause
