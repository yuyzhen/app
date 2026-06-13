@echo off
setlocal
cd /d "%~dp0"
where python.exe >nul 2>nul
if not %errorlevel%==0 (
    echo Python 3.10 or newer was not found on PATH.
    pause
    exit /b 1
)
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconsole --onefile --name ShenzhenWeatherWidget --icon "%~dp0weather_widget.ico" "%~dp0weather_widget.py"
echo.
echo Built executable: %~dp0dist\ShenzhenWeatherWidget.exe
pause
endlocal
