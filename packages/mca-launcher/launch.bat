@echo off
REM Open the MCA Launcher.
REM
REM Double-click this, or make a desktop shortcut to it. It finds a Python with PySide6,
REM puts this package on the path, and opens the window with no console behind it.
REM
REM Once mca-launcher is pip-installed, `mca-launcher` on its own does the same thing and
REM this file stops being needed.
setlocal

set HERE=%~dp0
set RUNNER=

REM pythonw first: no console window behind the launcher.
for %%P in (
    "C:\Python310\pythonw.exe"
    "C:\Python311\pythonw.exe"
    "C:\Python312\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
) do if exist "%%~P" if not defined RUNNER set RUNNER=%%~P

REM Failing that, any python at all - the console stays open, which is fine for debugging.
if not defined RUNNER (
    for %%P in ("C:\Python310\python.exe" "C:\Python311\python.exe") do (
        if exist "%%~P" if not defined RUNNER set RUNNER=%%~P
    )
)
if not defined RUNNER (
    where pythonw >nul 2>nul && set RUNNER=pythonw
)
if not defined RUNNER (
    echo No Python with PySide6 was found. Install Python 3.10 or newer and "pip install PySide6",
    echo or pass one as the first argument: launch.bat "C:\Path\To\pythonw.exe"
    pause
    exit /b 1
)
if not "%~1"=="" set RUNNER=%~1

REM Qt variables inherited from a DCC or another Qt application would point this at the wrong
REM Qt plug-ins. The launcher strips these for the DCCs it starts; it wants the same itself.
set QT_PLUGIN_PATH=
set QML2_IMPORT_PATH=
set QML_IMPORT_PATH=
set QT_QPA_PLATFORM_PLUGIN_PATH=
set QT_API=
set PYTHONPATH=%HERE%

start "" "%RUNNER%" -m mca.launcher
endlocal
