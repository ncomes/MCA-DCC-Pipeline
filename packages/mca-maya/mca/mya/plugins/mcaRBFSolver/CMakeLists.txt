# MCA-DCC Pipeline - RBF solver
# Copyright (c) 2026 Nathan Comes. MIT licensed.

cmake_minimum_required(VERSION 3.7)

project(mcaRBFSolver)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/../cmake)

set(PLUGIN_SOURCES_DIR ${CMAKE_CURRENT_SOURCE_DIR}/source)
set(PLUGIN_HEADERS_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)

file(GLOB_RECURSE PLUGIN_SOURCES ${PLUGIN_SOURCES_DIR}/*.c ${PLUGIN_SOURCES_DIR}/*.cpp)
file(GLOB_RECURSE PLUGIN_HEADERS ${PLUGIN_HEADERS_DIR}/*.h ${PLUGIN_HEADERS_DIR}/*.hpp)

# Eigen, already vendored in this tree and already used by rbfRetargeter. Header
# only, so there is nothing to link - and using the copy that is here rather than
# a second one keeps a single version in the process.
# Eigen is header-only and is NOT vendored in this repository - it belongs to its
# own authors, so it is a dependency to provide rather than source to ship. Looked
# for in three places, in order, so a checkout builds whichever way Eigen is here:
#
#   1. -DMCA_EIGEN_DIR=/path/to/eigen  (or the MCA_EIGEN_DIR environment variable)
#   2. libs/3rdparty/eigen3            (a local vendored copy, if you keep one)
#   3. find_package(Eigen3)            (a system or package-manager install)
if(NOT MCA_EIGEN_DIR AND DEFINED ENV{MCA_EIGEN_DIR})
    set(MCA_EIGEN_DIR $ENV{MCA_EIGEN_DIR})
endif()

if(MCA_EIGEN_DIR AND EXISTS ${MCA_EIGEN_DIR}/Eigen/Dense)
    set(EIGEN_INCLUDE_DIR ${MCA_EIGEN_DIR})
elseif(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/../libs/3rdparty/eigen3/Eigen/Dense)
    set(EIGEN_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../libs/3rdparty/eigen3)
else()
    find_package(Eigen3 3.3 QUIET)
    if(TARGET Eigen3::Eigen)
        get_target_property(EIGEN_INCLUDE_DIR Eigen3::Eigen
                            INTERFACE_INCLUDE_DIRECTORIES)
    endif()
endif()

if(NOT EIGEN_INCLUDE_DIR OR NOT EXISTS ${EIGEN_INCLUDE_DIR}/Eigen/Dense)
    message(FATAL_ERROR
        "Eigen (3.3 or newer, header-only) is required and was not found.\n"
        "  Pass -DMCA_EIGEN_DIR=<path to the folder containing Eigen/Dense>,\n"
        "  set the MCA_EIGEN_DIR environment variable,\n"
        "  put a copy at libs/3rdparty/eigen3,\n"
        "  or install Eigen3 so find_package can see it.")
endif()

message(STATUS "Eigen: ${EIGEN_INCLUDE_DIR}")

# The plug-in this replaces was a Python 2 script, so it had no build at all and
# has not loaded in any Maya since 2022.
set(MAYA_VERSIONS "2022;2024;2025;2026")

foreach(VERSION_FOUND IN LISTS MAYA_VERSIONS)

    # FindMaya caches MAYA_LOCATION and MAYA_EXECUTABLE without a version suffix,
    # so whatever the first iteration settles on is reused by every iteration
    # after it - and if that first search went through the "re-searching without
    # environment variables" path, the cached value is wrong for everyone. Clear
    # them each time round so each version is found on its own merits.
    unset(MAYA_LOCATION CACHE)
    unset(MAYA_EXECUTABLE CACHE)
    unset(MAYA_VERSION CACHE)

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
    target_include_directories(${PLUGIN_NAME} PUBLIC ${MAYA_INCLUDE_DIRS} ${EIGEN_INCLUDE_DIR})

    target_link_directories(${PLUGIN_NAME} PRIVATE ${MAYA_LIBRARY_DIRS})
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
