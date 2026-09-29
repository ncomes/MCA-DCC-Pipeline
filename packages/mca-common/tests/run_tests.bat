@echo off
REM Run every launcher suite.
REM
REM     run_tests.bat                                  uses py -3, then python
REM     run_tests.bat "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
REM
REM Maya's mayapy is a good choice on a machine with no other Python 3: it has PySide6, so
REM the window suite runs rather than skipping.
setlocal
set PYTHON=%~1
if "%PYTHON%"=="" (
    where py >nul 2>nul && set PYTHON=py -3
)
if "%PYTHON%"=="" (
    where python >nul 2>nul && set PYTHON=python
)
if "%PYTHON%"=="" (
    echo No Python found. Pass one as the first argument.
    exit /b 1
)

set FAILED=0
for %%S in (test_core.py test_api.py test_ui_window.py) do (
    echo.
    echo === %%S ===
    %PYTHON% "%~dp0%%S" || set FAILED=1
)

echo.
if "%FAILED%"=="0" (echo All suites passed.) else (echo Something failed.)
exit /b %FAILED%
