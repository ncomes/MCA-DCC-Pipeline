@echo off
REM Ask MotionBuilder's own Python why a package that installed will not import.
REM
REM   probe_mobu.bat                          - newest first-run sandbox, psutil
REM   probe_mobu.bat "<deps folder>"          - a particular dependency folder
REM   probe_mobu.bat "<deps folder>" numpy    - a particular package
REM
REM Everything it prints is also written to %LOCALAPPDATA%\MCA\probe_mobu.txt.

set MOBUPY=C:\Program Files\Autodesk\MotionBuilder 2024\bin\x64\mobupy.exe
if not exist "%MOBUPY%" goto :nomobu

echo.
echo   mobupy: %MOBUPY%
echo.
"%MOBUPY%" "%~dp0probe_mobu.py" %1 %2
echo.
echo   Done. The same text is in %LOCALAPPDATA%\MCA\probe_mobu.txt
pause
exit /b 0

:nomobu
echo Could not find mobupy at "%MOBUPY%".
echo Pass the path to another MotionBuilder by editing this file.
pause
exit /b 1
