@echo off
REM Register the Maya MCP server with Claude Code, and check it can run.
REM
REM     register.bat              register for this user, everywhere
REM     register.bat check        just say what is installed and what is missing
REM
REM The server needs the `mcp` package. It looks for one that already has it, in this order:
REM the MCAMCP venv, then C:\Python310, then whatever `python` is on PATH.
setlocal enabledelayedexpansion

set HERE=%~dp0
set HERE=%HERE:~0,-1%
set LAUNCHER=%HERE%\..\mca-launcher
set PYTHON=

for %%P in (
    "%USERPROFILE%\.mca-mcp\venv\Scripts\python.exe"
    "C:\Python310\python.exe"
    "C:\Python311\python.exe"
) do if exist %%P if not defined PYTHON set PYTHON=%%P

if not defined PYTHON (
    where python >nul 2>nul && set PYTHON=python
)
if not defined PYTHON (
    echo No Python found. Install one, then: python -m pip install mcp
    exit /b 1
)

echo Using %PYTHON%
%PYTHON% -c "import mcp" 2>nul
if errorlevel 1 (
    echo The mcp package is missing from that Python. Installing it...
    %PYTHON% -m pip install mcp || (echo Could not install mcp. & exit /b 1)
)

REM The server imports mca.mcp; maya_launch additionally imports mca.launcher.
set PYTHONPATH=%HERE%;%LAUNCHER%

if /i "%~1"=="check" (
    echo.
    echo --- can the server start and list its tools? ---
    %PYTHON% -c "import sys; sys.path[:0]=[r'%HERE%', r'%LAUNCHER%']; from mca.mcp.maya import server; print('%%d tools:' %% len(server.TOOLS)); [print('   ', t.name) for t in server.TOOLS]"
    echo.
    echo --- is a Maya reachable right now? ---
    %PYTHON% -c "import sys; sys.path[:0]=[r'%HERE%', r'%LAUNCHER%']; from mca.mcp.core import control; found=control.running(); print(found if found else 'no Maya is announcing itself yet')"
    exit /b 0
)

where claude >nul 2>nul || (
    echo The `claude` command was not found, so this cannot register automatically.
    echo Add this to your MCP client's config by hand:
    echo.
    echo   command: %PYTHON%
    echo   args:    -m mca.mcp.maya.server
    echo   env:     PYTHONPATH=%HERE%;%LAUNCHER%
    exit /b 1
)

claude mcp add MCAMaya --scope user --env PYTHONPATH=%HERE%;%LAUNCHER% -- %PYTHON% -m mca.mcp.maya.server
echo.
echo Registered. Restart the MCP client so it picks the server up.
endlocal
