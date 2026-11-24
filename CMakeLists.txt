cmake_minimum_required(VERSION 3.24)
project(Fission540 VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "Fission540 targets Linux only.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(FISSION_BUILD_APP "Build the Qt application" ON)
option(FISSION_BUILD_TESTS "Build tests" ON)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake)
include(FissionWarnings)

find_package(OpenCASCADE REQUIRED)
message(STATUS "OpenCASCADE ${OpenCASCADE_VERSION} at ${OpenCASCADE_INSTALL_PREFIX}")

add_subdirectory(src/kernel)
add_subdirectory(src/core)
add_subdirectory(src/features)

if(FISSION_BUILD_APP)
    find_package(Qt6 REQUIRED COMPONENTS Widgets)
    set(CMAKE_AUTOMOC ON)
    add_subdirectory(src/viewer)
    add_subdirectory(src/ui)
    add_subdirectory(app)
endif()

if(FISSION_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
