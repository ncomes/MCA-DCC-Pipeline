@echo off
rem MCA-DCC Pipeline - build the dynamic chain plug-in for every Maya found.
rem Output lands in plug-in\<version>\<config>\mcaPhysicsChain_maya<version>.mll
mkdir build 2>nul
cmake -H. -Bbuild -G "Visual Studio 17 2022" -A x64
cmake --build build/ --config Release
