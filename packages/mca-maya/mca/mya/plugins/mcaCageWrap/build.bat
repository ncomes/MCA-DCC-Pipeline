@echo off
rem MCA-DCC Pipeline - build the cage wrap plug-in for every Maya found.
rem Output lands in plug-in\<version>\Release\mcaCageWrap_maya<version>.mll
rem
rem If the link fails with LNK1104 on a .mll, an open Maya has that version
rem loaded and is holding the file. Unload it (a plug-in cannot be unloaded while
rem nodes of its type exist in the scene, so clear those first) or close Maya.
mkdir build 2>nul
cmake -H. -Bbuild -G "Visual Studio 17 2022" -A x64
cmake --build build/ --config Release
