cmake_minimum_required(VERSION 3.20)
project(alphacore_cpp CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_BUILD_TYPE Release)

# Compiler flags: O3 = max optimization, march=native = use all CPU features
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native -Wall -Wextra")

add_library(orderbook_lib
    src/orderbook.cpp
)
target_include_directories(orderbook_lib PUBLIC src/)

add_executable(alphacore src/main.cpp)
target_link_libraries(alphacore orderbook_lib)

add_executable(bench benchmarks/bench.cpp)
target_link_libraries(bench orderbook_lib)
