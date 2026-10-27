# MCA-DCC Pipeline - physics chain solver
# Copyright (c) 2026 Nathan Comes. MIT licensed.

cmake_minimum_required(VERSION 3.7)

project(mcaPhysicsChain)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/../cmake)

set(PLUGIN_SOURCES_DIR ${CMAKE_CURRENT_SOURCE_DIR}/source)
set(PLUGIN_HEADERS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)

file(GLOB_RECURSE PLUGIN_SOURCES ${PLUGIN_SOURCES_DIR}/*.c ${PLUGIN_SOURCES_DIR}/*.cpp)
file(GLOB_RECURSE PLUGIN_HEADERS ${PLUGIN_HEADERS_DIR}/*.h ${PLUGIN_HEADERS_DIR}/*.hpp)

# Every Maya whose devkit is on this machine. The solver has no Maya types in it
# and the node uses nothing newer than 2022, so one source tree covers all four.
# Drop a version from this list rather than branching the code if one ever needs
# to be dropped.
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
    target_link_directories(${PLUGIN_NAME} PRIVATE ${MAYA_LIBRARIES})
    target_link_libraries(${PLUGIN_NAME} PRIVATE ${MAYA_LIBRARIES})

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
