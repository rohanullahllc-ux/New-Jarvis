@echo off
rem Opens the Jarvis admin panel on its own (settings, shortcuts, contacts, backups). It asks for your Jarvis password first.
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0jarvis_setup\find_python.cmd"
if defined PY goto :found
echo.
echo   Python was not found. Double-click Setup-Jarvis.bat: it installs what is missing.
echo.
pause
goto :eof

:found
"%PY%" "%~dp0JarvisAdmin.py" %*
if errorlevel 1 pause
