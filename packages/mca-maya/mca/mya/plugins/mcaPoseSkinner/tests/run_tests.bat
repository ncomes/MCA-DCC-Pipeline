@echo off
rem MCA-DCC Pipeline - off-DCC tests for the pose skinning maths.
rem No Maya, no licence, no viewport. Low priority, because the person running it
rem usually wants to keep using their machine while it goes.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
if not exist build mkdir build
rem /external:I puts Eigen behind a "not our code" wall so /W4 applies to OUR files
rem and not to a few hundred lines of template instantiation notes.
rem No /openmp: the solver threads itself on plain CRT threads now. See
rem mca::parallelFor for why, and the plug-in's CMakeLists for the same note.
start "" /low /b /wait cl /nologo /EHsc /std:c++17 /W4 /O2 /external:I ..\..\libs\3rdparty\eigen3 /external:W0 /I..\include /I..\..\common\include test_solver.cpp ..\source\mca_pose_skin.cpp ..\source\mca_pose_skin_solve.cpp /Fo:build\ /Fe:build\test_solver.exe
if errorlevel 1 ( echo COMPILE FAILED & exit /b 1 )
start "" /low /b /wait build\test_solver.exe
echo TESTS errorlevel=%errorlevel%
echo DONE
