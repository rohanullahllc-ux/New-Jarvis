@echo off
rem Jarvis setup: double-click this. It finds Python (or offers to install it), then starts the setup wizard.
rem Run it again any time: it only does what is missing.   Options go on the end, e.g.  Setup-Jarvis.bat --check
rem Every path is quoted: the Windows user folder can contain "&" and spaces.
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Jarvis setup

call "%~dp0jarvis_setup\find_python.cmd"
if defined PY goto :run

echo.
echo   Python 3.12 or newer was not found on this PC. Jarvis is written in Python (3.14 is the version he was built on).
echo.
if defined JARVIS_SETUP_DRY_RUN goto :dry
choice /c YN /m "  May I download and install Python 3.14 for you now (free, from python.org)"
if errorlevel 2 goto :manual
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0jarvis_setup\install_python.ps1"
call "%~dp0jarvis_setup\find_python.cmd"
if defined PY goto :run
echo.
echo   Python was installed, but this window cannot see it yet. Close this window and double-click Setup-Jarvis.bat again.
goto :end

:dry
echo   (test mode: I would now offer to install Python)
goto :end

:manual
echo.
echo   Please install Python 3.14 from https://www.python.org/downloads/  and tick "Add python.exe to PATH" on the first screen.
echo   Then double-click Setup-Jarvis.bat again.
goto :end

:run
echo.
echo   Using Python: "%PY%"
"%PY%" "%~dp0setup_jarvis.py" %*
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" echo   The setup stopped with a problem (code %CODE%). Read the lines above; running this file again carries on from here.

:end
echo.
pause
endlocal
