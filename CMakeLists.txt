cmake_minimum_required(VERSION 3.15...3.27)
project(DC2)

if (CMAKE_VERSION VERSION_LESS 3.18)
  set(DEV_MODULE Development)
else()
  set(DEV_MODULE Development.Module)
endif()

message(STATUS "C++ Compiler ID: ${CMAKE_CXX_COMPILER_ID}")
message(STATUS "C++ Compiler Version: ${CMAKE_CXX_COMPILER_VERSION}")

if (NOT DataAcqSDK_ROOT)
    message(FATAL_ERROR
        "DataAcqSDK_ROOT is not set. Pass -DDataAcqSDK_ROOT=<sdk root> "
        "or set it in CMakeUserPresets.json.")
endif()

if (NOT XirisWeldSDK_ROOT)
    message(FATAL_ERROR
        "XirisWeldSDK_ROOT is not set. Pass -DXirisWeldSDK_ROOT=<sdk root> "
        "or set it in CMakeUserPresets.json.")
endif()

if (NOT EXISTS "${DataAcqSDK_ROOT}/Include/oldaapi.h")
    message(FATAL_ERROR "oldaapi.h not found under ${DataAcqSDK_ROOT}")
endif()

if (NOT EXISTS "${XirisWeldSDK_ROOT}/include/WeldSDK")
    message(FATAL_ERROR "WeldSDK not found under ${XirisWeldSDK_ROOT}")
endif()

find_package(Python 3.12.10 COMPONENTS Interpreter ${DEV_MODULE} REQUIRED)

if (NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Choose the type of build." FORCE)
  set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS "Debug" "Release" "MinSizeRel" "RelWithDebInfo")
endif()

# Detect the installed nanobind package and import it into CMake
execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE nanobind_ROOT)
find_package(nanobind CONFIG REQUIRED)

add_library(OLDAAPI SHARED IMPORTED)
set_target_properties(OLDAAPI PROPERTIES
    IMPORTED_IMPLIB     "${DataAcqSDK_ROOT}/lib64/oldaapi64.lib"
    IMPORTED_LOCATION   "C:/Windows/System32/oldaapi64.dll"
    INTERFACE_INCLUDE_DIRECTORIES "${DataAcqSDK_ROOT}/Include"
)

add_library(OLMEM SHARED IMPORTED)
set_target_properties(OLMEM PROPERTIES
    IMPORTED_IMPLIB     "${DataAcqSDK_ROOT}/lib64/OLMEM64.lib"
    IMPORTED_LOCATION   "C:/Windows/System32/olmem64.dll.dll"
    INTERFACE_INCLUDE_DIRECTORIES "${DataAcqSDK_ROOT}/Include"
)

add_library(WeldSDK SHARED IMPORTED)
set_target_properties(WeldSDK PROPERTIES
    IMPORTED_IMPLIB "${XirisWeldSDK_ROOT}/lib/WeldSDK.lib"
    IMPORTED_LOCATION "${XirisWeldSDK_ROOT}/bin/WeldSDK.dll"
    INTERFACE_INCLUDE_DIRECTORIES "${XirisWeldSDK_ROOT}/include"
)

add_library(XAudioSDK SHARED IMPORTED)
set_target_properties(XAudioSDK PROPERTIES
    IMPORTED_IMPLIB "${XirisWeldSDK_ROOT}/lib/XAudioSDK.lib"
    IMPORTED_LOCATION "${XirisWeldSDK_ROOT}/bin/XAudioSDK.dll"
    INTERFACE_INCLUDE_DIRECTORIES "${XirisWeldSDK_ROOT}/include"
)

nanobind_add_module(lembox_bindings STABLE_ABI NB_STATIC lembox.cpp)
target_link_libraries(lembox_bindings PRIVATE OLDAAPI OLMEM)

nanobind_add_module(xiris_bindings STABLE_ABI NB_STATIC xiris.cpp)
target_link_libraries(xiris_bindings PRIVATE WeldSDK XAudioSDK)