@echo off
rem MCA-DCC Pipeline - off-DCC tests for the cage maths.
rem No Maya, no licence, no viewport. Runs in a couple of seconds.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /EHsc /std:c++17 /W4 /O2 /I..\include /I..\..\common\include test_cage.cpp ..\source\mca_cage_wrap.cpp /Fo:build\ /Fe:build\test_cage.exe
if errorlevel 1 ( echo COMPILE FAILED & exit /b 1 )
build\test_cage.exe
echo TESTS errorlevel=%errorlevel%
echo DONE
