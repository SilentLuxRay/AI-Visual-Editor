@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0runtime\python.exe" (
    echo Dedicated Python runtime not found.
    echo Download the Windows Portable ZIP from the GitHub Releases page
    echo and extract the entire archive before starting the application.
    pause
    exit /b 1
)
set "PYTHONHOME="
set "PYTHONPATH="
"%~dp0runtime\python.exe" -I "%~dp0processore_immagini.py"
if errorlevel 1 (
    echo.
    echo Startup failed. Please read the error message above.
    pause
)
endlocal
