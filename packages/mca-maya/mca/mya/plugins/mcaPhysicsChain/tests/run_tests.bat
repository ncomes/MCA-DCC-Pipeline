@echo off
rem MCA-DCC Pipeline - off-DCC tests for the solver maths.
rem No Maya, no licence, no viewport. Runs in about a second.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /EHsc /std:c++17 /W4 /I..\include test_solver.cpp ..\source\mca_solver.cpp /Fo:build\ /Fe:build\test_solver.exe
if errorlevel 1 ( echo COMPILE FAILED & exit /b 1 )
build\test_solver.exe
echo TESTS errorlevel=%errorlevel%
echo DONE
