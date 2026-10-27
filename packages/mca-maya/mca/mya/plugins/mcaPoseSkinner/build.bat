@echo off
rem MCA-DCC Pipeline - build the pose skinner for every Maya found.
rem Output lands in plug-in\<version>\Release\mcaPoseSkinner_maya<version>.mll
rem
rem If the link fails with LNK1104 on a .mll, an open Maya has that version
rem loaded and is holding the file. Unload it (a plug-in cannot be unloaded while
rem nodes of its type exist in the scene, so clear those first) or close Maya.
rem Clear the caller's Maya environment first. A shell launched from a running
rem Maya carries MAYA_LOCATION, which makes FindMaya pick that version, notice it
rem is not the one being asked for, and re-search - and the re-search leaves
rem MAYA_VERSION empty, which trips an unquoted comparison in FindMaya.cmake:
rem   if(${MAYA_VERSION} STREQUAL "2011")   ->   if( STREQUAL "2011")
rem The other plug-ins only escape this because their build/ caches predate the
rem problem; a fresh configure hits it every time.
set MAYA_LOCATION=
set MAYA_PLUG_IN_PATH=
set MAYA_MODULE_PATH=
set MAYA_SCRIPT_PATH=

rem Low priority, and one compiler at a time.
rem
rem Four Maya versions x four translation units, each of which instantiates a good
rem deal of Eigen, is enough to saturate a workstation - and a saturated workstation
rem beside an open Maya is how this plug-in's author lost an afternoon. It costs a
rem couple of minutes to be polite about it. Pass /m:4 by hand on a build machine.
mkdir build 2>nul
start "" /low /b /wait cmake -H. -Bbuild -G "Visual Studio 17 2022" -A x64
start "" /low /b /wait cmake --build build/ --config Release -- /m:1 /p:CL_MPCount=1
