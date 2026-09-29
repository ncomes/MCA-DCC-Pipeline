@echo off
REM Ask MotionBuilder's own Python why a package that installed will not import.
REM
REM   probe_mobu.bat                     - newest first-run sandbox, psutil
REM   probe_mobu.bat "<deps folder>"     - a particular dependency folder
REM   probe_mobu.bat "<deps folder>" numpy
setlocal enabledelayedexpansion

set MOBUPY=C:\Program Files\Autodesk\MotionBuilder 2024\bin\x64\mobupy.exe
if not exist "%MOBUPY%" (
    echo Could not find mobupy at "%MOBUPY%".
    pause
    exit /b 1
)

set TARGET=%~1
if "%TARGET%"=="" (
    REM Newest first-run sandbox, if there is one; otherwise the real dependency folder.
    for /f "delims=" %%D in ('dir /b /ad /o-d "%LOCALAPPDATA%\MCA\first-run" 2^>nul') do (
        if not defined STAMP set STAMP=%%D
    )
    if defined STAMP (
        set TARGET=%LOCALAPPDATA%\MCA\first-run\!STAMP!\deps\mobu-2024
    ) else (
        set TARGET=%LOCALAPPDATA%\MCA\deps\mobu-2024
    )
)

set PACKAGE=%~2
if "%PACKAGE%"=="" set PACKAGE=psutil

echo.
echo   mobupy : %MOBUPY%
echo   deps   : %TARGET%
echo   package: %PACKAGE%
echo.

"%MOBUPY%" "%~dp0probe_mobu.py" "%TARGET%" "%PACKAGE%"
echo.
pause
endlocal
