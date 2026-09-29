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
for %%P in ("%USERPROFILE%\.mca-mcp\venv\Scripts\python.exe" "C:\Python310\python.exe") do (
    if exist %%P if not defined PYTHON set PYTHON=%%P
)
if not defined PYTHON set PYTHON=python
set PYTHONPATH=%HERE%;%HERE%\..\mca-launcher
"%PYTHON%" "%HERE%\tests\test_live.py" %*
endlocal
