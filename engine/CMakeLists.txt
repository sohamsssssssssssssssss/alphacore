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

# ── Full Add-path benchmark ──────────────────────────────────────────
add_executable(add_bench benchmarks/add_bench.cpp src/engine.cpp src/flat_price_map.cpp)
target_compile_options(add_bench PRIVATE -O3 -march=native)
target_compile_features(add_bench PRIVATE cxx_std_20)
target_include_directories(add_bench PRIVATE src/)

# ── Test executables ─────────────────────────────────────────────────
add_executable(engine_test tests/engine_test.cpp src/engine.cpp src/flat_price_map.cpp)
target_compile_options(engine_test PRIVATE -O3 -march=native)
target_compile_features(engine_test PRIVATE cxx_std_20)
target_include_directories(engine_test PRIVATE src/)

add_executable(replication_test tests/replication_test.cpp src/replication.cpp src/heartbeat.cpp)
target_compile_options(replication_test PRIVATE -O3 -march=native)
target_compile_features(replication_test PRIVATE cxx_std_20)
target_include_directories(replication_test PRIVATE src/)

add_executable(gateway_test tests/gateway_test.cpp src/engine.cpp src/flat_price_map.cpp src/gateway.cpp src/replication.cpp src/heartbeat.cpp)
target_compile_options(gateway_test PRIVATE -O3 -march=native)
target_compile_features(gateway_test PRIVATE cxx_std_20)
target_include_directories(gateway_test PRIVATE src/)

add_executable(fault_test tests/chaos/fault_test.cpp)
target_compile_options(fault_test PRIVATE -O3 -march=native -DALPHACORE_FAULT_INJECT)
target_compile_features(fault_test PRIVATE cxx_std_20)
target_include_directories(fault_test PRIVATE src/)

# ── Add-bench with fault injection (full mode) ───────────────────────
add_executable(add_bench_full benchmarks/add_bench.cpp src/engine.cpp src/flat_price_map.cpp)
target_compile_options(add_bench_full PRIVATE -O3 -march=native -DALPHACORE_FAULT_INJECT)
target_compile_features(add_bench_full PRIVATE cxx_std_20)
target_include_directories(add_bench_full PRIVATE src/)

add_executable(ha_chaos_test tests/chaos/ha_chaos_test.cpp src/replication.cpp src/heartbeat.cpp)
target_compile_options(ha_chaos_test PRIVATE -O3 -march=native)
target_compile_features(ha_chaos_test PRIVATE cxx_std_20)
target_include_directories(ha_chaos_test PRIVATE src/)

add_executable(deterministic_replay_test tests/chaos/deterministic_replay_test.cpp src/replication.cpp src/heartbeat.cpp src/engine.cpp src/flat_price_map.cpp)
target_compile_options(deterministic_replay_test PRIVATE -O3 -march=native)
target_compile_features(deterministic_replay_test PRIVATE cxx_std_20)
target_include_directories(deterministic_replay_test PRIVATE src/)

# ── TSan build (separate preset) ─────────────────────────────────────
# Usage: cmake -DCMAKE_BUILD_TYPE=TSan -DALPHACORE_TSAN=ON .. && make
if(ALPHACORE_TSAN)
    message(STATUS "Building with ThreadSanitizer")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fsanitize=thread -fno-omit-frame-pointer -g -O1 -DALPHACORE_FAULT_INJECT")
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -fsanitize=thread")

    add_executable(mpsc_tsan_test tests/chaos/mpsc_tsan_test.cpp src/engine.cpp src/flat_price_map.cpp)
    target_compile_options(mpsc_tsan_test PRIVATE -g -O1 -fsanitize=thread)
    target_compile_features(mpsc_tsan_test PRIVATE cxx_std_20)
    target_include_directories(mpsc_tsan_test PRIVATE src/)
    target_link_options(mpsc_tsan_test PRIVATE -fsanitize=thread)
endif()
