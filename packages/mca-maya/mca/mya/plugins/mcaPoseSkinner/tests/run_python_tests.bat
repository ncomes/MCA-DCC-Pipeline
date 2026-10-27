@echo off
REM Run this plug-in's Python suites under one Maya version.
REM
REM     run_python_tests.bat 2025
REM
REM The caller's Maya environment is stripped first. A shell launched from a Maya
REM session carries MAYA_LOCATION and MAYA_SCRIPT_PATH, so every OTHER version's
REM mayapy then sources that version's startup MEL and dies on flags its own
REM version never had. The suites put the framework's own bundles back on
REM sys.path themselves.
setlocal
if "%~1"=="" (echo Usage: run_python_tests.bat ^<maya version^>, e.g. 2025 & exit /b 1)
set MAYA_DISABLE_CER=1
set MAYA_DISABLE_CIP=1
set MAYA_DISABLE_ADP=1
set MAYA_LOCATION=
set MAYA_SCRIPT_PATH=
set MAYA_PLUG_IN_PATH=
set MAYA_MODULE_PATH=
set MAYA_PRESET_PATH=
set XBMLANGPATH=
set PYTHONPATH=
set MAYAPY="C:\Program Files\Autodesk\Maya%~1\bin\mayapy.exe"
if not exist %MAYAPY% (echo Maya %~1 is not installed here. & exit /b 1)
for %%T in ("%~dp0test_*.py") do (
    echo.
    echo === %%~nxT ===
    rem Low priority: these suites solve a whole face on every core, and the
    rem person running them usually wants to keep using their machine.
    start "" /low /b /wait %MAYAPY% -u "%%~fT"
)
echo.
echo Done.
endlocal
