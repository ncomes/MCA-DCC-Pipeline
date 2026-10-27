# MCA-DCC Pipeline - mesh tiler
# Copyright (c) 2026 Nathan Comes. MIT licensed.

cmake_minimum_required(VERSION 3.7)

project(mcaMeshTiler)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/../cmake)

set(PLUGIN_SOURCES_DIR ${CMAKE_CURRENT_SOURCE_DIR}/source)
set(PLUGIN_HEADERS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)

file(GLOB_RECURSE PLUGIN_SOURCES ${PLUGIN_SOURCES_DIR}/*.c ${PLUGIN_SOURCES_DIR}/*.cpp)
file(GLOB_RECURSE PLUGIN_HEADERS ${PLUGIN_HEADERS_DIR}/*.h ${PLUGIN_HEADERS_DIR}/*.hpp)

# Every Maya whose devkit is on this machine. OpenSubdiv ships with Maya itself -
# osdCPU.lib, osdGPU.lib and the Far headers are present in 2022, 2024, 2025 and
# 2026 under the same names - so one source tree covers all four. The plug-in
# this replaces built for 2025 only.
set(MAYA_VERSIONS "2022;2024;2025;2026")

foreach(VERSION_FOUND IN LISTS MAYA_VERSIONS)

    set(Maya_FIND_VERSION_EXACT 1)
    set(Maya_FIND_VERSION ${VERSION_FOUND})

    # Not REQUIRED: a machine with only some of the devkits installed should
    # build what it can rather than failing the whole configure step.
    find_package(Maya)

    if(NOT MAYA_FOUND)
        message(STATUS "Maya ${VERSION_FOUND} not found - skipping")
        continue()
    endif()

    set(PLUGIN_NAME ${CMAKE_PROJECT_NAME}_maya${MAYA_VERSION})
    set(PLUGINS_FOLDER Plugins/Maya/${MAYA_VERSION})

    add_library(${PLUGIN_NAME} SHARED ${PLUGIN_SOURCES} ${PLUGIN_HEADERS})
    set_target_properties(${PLUGIN_NAME} PROPERTIES FOLDER ${PLUGINS_FOLDER})
    target_include_directories(${PLUGIN_NAME} PRIVATE include ../common/include)
    target_include_directories(${PLUGIN_NAME} PUBLIC ${MAYA_INCLUDE_DIRS})

    # OpenSubdiv comes out of Maya's own lib folder rather than being vendored,
    # so the version we build against always matches the version Maya loaded.
    # Vendoring a second copy is how you get two OpenSubdivs in one process.
    find_library(OSD_CPU_LIBRARY osdCPU PATHS ${MAYA_LIBRARY_DIRS} NO_DEFAULT_PATH)
    if(NOT OSD_CPU_LIBRARY)
        message(FATAL_ERROR "osdCPU not found in ${MAYA_LIBRARY_DIRS} for Maya ${MAYA_VERSION}")
    endif()

    target_link_directories(${PLUGIN_NAME} PRIVATE ${MAYA_LIBRARY_DIRS})
    target_link_libraries(${PLUGIN_NAME} PRIVATE ${MAYA_LIBRARIES} ${OSD_CPU_LIBRARY})
    unset(OSD_CPU_LIBRARY CACHE)

    # Land the binary where the other plug-ins in this tree keep theirs, so the
    # Maya module path and the loader do not need a special case for us.
    foreach(CONFIG_TYPE Debug Release RelWithDebInfo MinSizeRel)
        string(TOUPPER ${CONFIG_TYPE} CONFIG_UPPER)
        set_target_properties(${PLUGIN_NAME} PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY_${CONFIG_UPPER}
                ${CMAKE_CURRENT_SOURCE_DIR}/plug-in/${MAYA_VERSION}/${CONFIG_TYPE}
            LIBRARY_OUTPUT_DIRECTORY_${CONFIG_UPPER}
                ${CMAKE_CURRENT_SOURCE_DIR}/plug-in/${MAYA_VERSION}/${CONFIG_TYPE})
    endforeach()

    MAYA_SET_PLUGIN_PROPERTIES(${PLUGIN_NAME})
endforeach()

source_group("Include" FILES ${PLUGIN_HEADERS})
source_group("Source" FILES ${PLUGIN_SOURCES})
