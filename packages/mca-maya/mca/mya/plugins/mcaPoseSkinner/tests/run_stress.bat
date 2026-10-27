@echo off
rem MCA-DCC Pipeline - hammer the pose skinner's solver core off-DCC.
rem
rem     run_stress.bat [repeats] [threads] [vertices] [poses] [joints]
rem
rem BE KIND TO THE MACHINE. An earlier version of this script ran the debug-CRT
rem build at face scale on every core; started beside a compile and an open Maya it
rem took a whole workstation down. So:
rem
rem   * every process here runs at LOW priority, so the desktop stays responsive,
rem   * the checked build runs SMALL and on ONE thread - bounds checking needs the
rem     code paths, not the scale,
rem   * the release build leaves two cores for the rest of the machine,
rem   * and nothing here runs concurrently with anything else. Do not start a build
rem     or a Maya suite while this is going.
rem
rem Two builds, because they catch different things:
rem
rem   checked  - debug CRT, _ITERATOR_DEBUG_LEVEL=2, no optimiser. Every container
rem              access is bounds-checked, so a bad index aborts AT THE LINE. This
rem              is the one that turns "an access violation somewhere, sometimes"
rem              into a file and a line number. Roughly 20x slower.
rem   release  - exactly the flags the plug-in ships with. The only build that can
rem              reproduce a fault that depends on the optimiser or on timing.
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
if not exist build mkdir build
if not exist build\checked mkdir build\checked
if not exist build\rel mkdir build\rel

set REPEATS=%1
if "%REPEATS%"=="" set REPEATS=4
set THREADS=%2
if "%THREADS%"=="" set /a THREADS=%NUMBER_OF_PROCESSORS%-2
if %THREADS% LSS 1 set THREADS=1
set SIZE=%3 %4 %5

echo === building checked (low priority) ===
start "" /low /b /wait cl /nologo /EHsc /std:c++17 /W4 /Od /MDd /D_ITERATOR_DEBUG_LEVEL=2 /external:I ..\..\libs\3rdparty\eigen3 /external:W0 /I..\include /I..\..\common\include stress_solver.cpp ..\source\mca_pose_skin.cpp ..\source\mca_pose_skin_solve.cpp /Fo:build\checked\ /Fe:build\stress_checked.exe
if errorlevel 1 ( echo CHECKED COMPILE FAILED & exit /b 1 )

echo === building release (low priority) ===
start "" /low /b /wait cl /nologo /EHsc /std:c++17 /W4 /O2 /Zi /external:I ..\..\libs\3rdparty\eigen3 /external:W0 /I..\include /I..\..\common\include stress_solver.cpp ..\source\mca_pose_skin.cpp ..\source\mca_pose_skin_solve.cpp /Fo:build\rel\ /Fe:build\stress_release.exe /link /MAP:build\stress_release.map
if errorlevel 1 ( echo RELEASE COMPILE FAILED & exit /b 1 )

echo.
echo === checked: bounds-checked, one thread, small ===
start "" /low /b /wait build\stress_checked.exe 1 1 %SIZE%
echo CHECKED errorlevel=%errorlevel%

echo.
echo === release: %REPEATS% repeats on %THREADS% threads ===
start "" /low /b /wait build\stress_release.exe %REPEATS% %THREADS% %SIZE%
echo RELEASE errorlevel=%errorlevel%

echo.
echo === release: %REPEATS% repeats on one thread, for comparison ===
start "" /low /b /wait build\stress_release.exe %REPEATS% 1 %SIZE%
echo SINGLE errorlevel=%errorlevel%
echo DONE
endlocal
