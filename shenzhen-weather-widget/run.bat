@echo off
setlocal
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0weather_widget.py"
    goto :done
)
where python.exe >nul 2>nul
if %errorlevel%==0 (
    start "" python.exe "%~dp0weather_widget.py"
    goto :done
)
echo Python 3.10 or newer was not found on PATH.
echo Please install Python from https://www.python.org/downloads/windows/
pause
:done
endlocal
