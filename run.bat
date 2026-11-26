@echo off
cd /d "%~dp0"

:: Launch windowless Python GUI and immediately close this command prompt window
where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pyw main.py %*
) else (
    start "" pythonw main.py %*
)

exit
