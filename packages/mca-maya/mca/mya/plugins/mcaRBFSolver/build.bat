@echo off
rem MCA-DCC Pipeline - build the RBF solver for every Maya found.
rem Output lands in plug-in\<version>\Release\mcaRBFSolver_maya<version>.mll
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

mkdir build 2>nul
cmake -H. -Bbuild -G "Visual Studio 17 2022" -A x64
cmake --build build/ --config Release
