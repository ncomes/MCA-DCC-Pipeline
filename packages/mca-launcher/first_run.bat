@echo off
REM Open the launcher as if this machine had never seen it.
REM
REM Everything the launcher writes - project preferences, the dependency folders it fills,
REM its logs - is moved into a scratch folder for this run only. Your real preferences
REM (Documents\mca_preferences) and your real dependency folders (%LOCALAPPDATA%\MCA\deps)
REM are not read and not touched, so the first launch installs packages for real and
REM proves the bootstrap on a machine that has nothing.
REM
REM Delete the folder it prints when you are done with it.
setlocal

set HERE=%~dp0

REM One folder per run, so two first runs never see each other's leftovers.
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%T
set SANDBOX=%LOCALAPPDATA%\MCA\first-run\%STAMP%

set MCA_PREFS_ROOT=%SANDBOX%\prefs
set MCA_DEPS_ROOT=%SANDBOX%\deps
set MCA_LOGS_ROOT=%SANDBOX%\logs
mkdir "%MCA_PREFS_ROOT%" 2>nul
mkdir "%MCA_DEPS_ROOT%" 2>nul
mkdir "%MCA_LOGS_ROOT%" 2>nul

echo.
echo   First-run sandbox: %SANDBOX%
echo.
echo   prefs -^> %MCA_PREFS_ROOT%
echo   deps  -^> %MCA_DEPS_ROOT%
echo   logs  -^> %MCA_LOGS_ROOT%
echo.
echo   Your real preferences and dependency folders are untouched by this run.
echo.

REM Same interpreter search as launch.bat, but python rather than pythonw: the console
REM stays, because on a first run the output is the point.
set RUNNER=
for %%P in (
    "C:\Python310\python.exe"
    "C:\Python311\python.exe"
    "C:\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do if exist "%%~P" if not defined RUNNER set RUNNER=%%~P
if not defined RUNNER (
    where python >nul 2>nul && set RUNNER=python
)
if not defined RUNNER (
    echo No Python with PySide6 was found. Pass one as the first argument:
    echo     first_run.bat "C:\Path\To\python.exe"
    pause
    exit /b 1
)
if not "%~1"=="" set RUNNER=%~1

set QT_PLUGIN_PATH=
set QML2_IMPORT_PATH=
set QML_IMPORT_PATH=
set QT_QPA_PLATFORM_PLUGIN_PATH=
set QT_API=
set PYTHONPATH=%HERE%

"%RUNNER%" -m mca.launcher
echo.
echo   Closed. The sandbox is still at: %SANDBOX%
pause
endlocal
