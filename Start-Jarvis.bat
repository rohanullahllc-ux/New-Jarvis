@echo off
rem Starts the Jarvis window. Double-click it (or the Jarvis shortcut the setup puts on the desktop).
rem If something is missing it says so and points you to Setup-Jarvis.bat instead of just closing.
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0jarvis_setup\find_python.cmd"
if defined PY goto :found
echo.
echo   Python was not found, so Jarvis cannot start. Double-click Setup-Jarvis.bat: it installs what is missing.
echo.
pause
goto :eof

:found
rem Try loading the window first: if that fails, run in this window so that the reason can be read.
"%PY%" -c "import config, gui.main_window" >nul 2>&1
if errorlevel 1 goto :console
start "" "%PYW%" "%~dp0JarvisGUI.py"
goto :eof

:console
echo.
echo   Jarvis could not load. Running him here so that you can read why. Setup-Jarvis.bat usually fixes it.
echo.
"%PY%" "%~dp0JarvisGUI.py"
echo.
pause
