@echo off
REM Find out which layer of the Maya transport is silent. Maya must be open with its command
REM ports on (the bootstrap, or the editor, will have done that).
setlocal
set HERE=%~dp0
set HERE=%HERE:~0,-1%
set PYTHON=
for %%P in ("C:\Python310\python.exe" "C:\Python311\python.exe") do (
    if exist "%%~P" if not defined PYTHON set PYTHON=%%~P
)
if not defined PYTHON set PYTHON=python
set PYTHONPATH=%HERE%\..
set LOG=%HERE%\probe.log
"%PYTHON%" -u "%HERE%\probe.py" > "%LOG%" 2>&1
type "%LOG%"
echo.
echo (saved to %LOG%)
pause
