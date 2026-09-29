@echo off
REM Prove the whole chain without an MCP client and without the editor:
REM start Maya, run Python in it, read the scene, close it.
REM
REM     test_live.bat            uses the launcher's remembered Maya version
REM     test_live.bat 2025
setlocal
set HERE=%~dp0
set HERE=%HERE:~0,-1%
set PYTHON=
for %%P in ("C:\Python310\python.exe" "C:\Python311\python.exe" "%USERPROFILE%\.mca-mcp\venv\Scripts\python.exe") do (
    if exist "%%~P" if not defined PYTHON set PYTHON=%%~P
)
if not defined PYTHON set PYTHON=python
set PYTHONPATH=%HERE%;%HERE%\..\mca-launcher
set MAYA_VERSION=%~1
if "%MAYA_VERSION%"=="" (
    set MAYA_VERSION=2025
    echo No version given - using 2025, which is the one this has been proven on.
    echo Pass one to override: test_live.bat 2026
)
echo Using "%PYTHON%" and Maya %MAYA_VERSION%
set LOG=%HERE%\tests\last_run.log
echo Writing a copy of this run to %LOG%
"%PYTHON%" -u "%HERE%\tests\test_live.py" %MAYA_VERSION% > "%LOG%" 2>&1
type "%LOG%"
echo.
echo (saved to %LOG%)
pause
endlocal
