@echo off
rem Sets PY to a Python 3.12 or newer (and PYW to its windowless twin) if this PC has one. Used by the Jarvis launchers.
rem Every path is quoted: the Windows user folder can contain "&" and spaces ("C:\Users\Rohaan & Co").
rem No block with ( ) is used for the same reason: a ")" inside a path ("Program Files (x86)") would end it early.
set "PY="
set "PYW="
for %%V in (3.14 3.13 3.12) do if not defined PY call :launcher %%V
if not defined PY call :candidate python
if not defined PY call :candidate python3
for %%M in (14 13 12) do if not defined PY call :known %%M
if not defined PY goto :eof
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"
goto :eof

:launcher
rem the "py" launcher that python.org installs: py -3.14
py -%1 -c "import sys" >nul 2>&1 || goto :eof
for /f "usebackq delims=" %%P in (`py -%1 -c "import sys; print(sys.executable)"`) do set "PY=%%P"
goto :eof

:candidate
rem whatever "python" is on the PATH - the Microsoft Store shortcut fails this test, as it should
%1 -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1 || goto :eof
for /f "usebackq delims=" %%P in (`%1 -c "import sys; print(sys.executable)"`) do set "PY=%%P"
goto :eof

:known
rem the places Python 3.1x is installed when it is not on the PATH yet (just installed, or the PATH box was not ticked)
for %%D in ("%LOCALAPPDATA%\Python\pythoncore-3.%1-64" "%LOCALAPPDATA%\Programs\Python\Python3%1" "%ProgramFiles%\Python3%1" "C:\Python3%1") do if not defined PY if exist "%%~D\python.exe" "%%~D\python.exe" -c "import sys" >nul 2>&1 && set "PY=%%~D\python.exe"
goto :eof
