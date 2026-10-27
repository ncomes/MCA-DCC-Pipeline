@echo off
rem MCA-DCC Pipeline - off-DCC tests for the RBF maths.
rem No Maya, no licence, no viewport. Runs in about a second.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
if not exist build mkdir build
rem /external:I puts Eigen behind an "not our code" wall so /W4 applies to OUR
rem files and not to a few hundred lines of template instantiation notes from a
rem third-party header. A runner that prints that much noise is one nobody reads.
cl /nologo /EHsc /std:c++17 /W4 /external:I ..\..\libs\3rdparty\eigen3 /external:W0 /I..\include test_rbf.cpp ..\source\mca_rbf.cpp /Fo:build\ /Fe:build\test_rbf.exe
if errorlevel 1 ( echo COMPILE FAILED & exit /b 1 )
build\test_rbf.exe
echo TESTS errorlevel=%errorlevel%
echo DONE
