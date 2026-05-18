cmake_minimum_required(VERSION 3.18)
project(alphacore_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_STRIP "")

execute_process(
    COMMAND python3 -m pybind11 --cmakedir
    OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
)
if(PYBIND11_CMAKE_DIR)
    list(APPEND CMAKE_PREFIX_PATH "${PYBIND11_CMAKE_DIR}")
endif()

find_package(pybind11 CONFIG QUIET)
if(NOT pybind11_FOUND)
    include(FetchContent)
    FetchContent_Declare(
        pybind11
        GIT_REPOSITORY https://github.com/pybind/pybind11.git
        GIT_TAG v3.0.1
    )
    FetchContent_MakeAvailable(pybind11)
endif()

pybind11_add_module(alphacore_cpp
    src/bindings.cpp
    src/engine.cpp
    src/flat_price_map.cpp
    src/gateway.cpp
    src/itch_parser.cpp
    src/replication.cpp
    src/heartbeat.cpp
)

target_compile_options(alphacore_cpp PRIVATE -O3 -march=native)

add_executable(flat_price_map_bench benchmarks/flat_price_map_bench.cpp src/flat_price_map.cpp)
target_compile_options(flat_price_map_bench PRIVATE -O3 -march=native)
target_compile_features(flat_price_map_bench PRIVATE cxx_std_20)

add_executable(pool_bench benchmarks/pool_bench.cpp)
target_compile_options(pool_bench PRIVATE -O3 -march=native)
target_compile_features(pool_bench PRIVATE cxx_std_20)

add_executable(mpsc_bench benchmarks/mpsc_bench.cpp)
target_compile_options(mpsc_bench PRIVATE -O3 -march=native)
target_compile_features(mpsc_bench PRIVATE cxx_std_20)

add_executable(itch_bench benchmarks/itch_bench.cpp src/flat_price_map.cpp src/engine.cpp src/itch_parser.cpp src/replication.cpp src/heartbeat.cpp)
target_compile_options(itch_bench PRIVATE -O3 -march=native)
target_compile_features(itch_bench PRIVATE cxx_std_20)
