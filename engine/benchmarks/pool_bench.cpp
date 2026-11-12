#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <thread>

#include "../src/pool.hpp"

#if defined(__x86_64__) || defined(__i386__)
#include <x86intrin.h>
#endif

struct Order {
    std::uint64_t order_id;
    std::int64_t price;
    std::uint32_t qty;
};

constexpr std::size_t n_ops = 1'000'000;
static Pool<Order, n_ops> pool;

int main() {
    double ns_per_op = 0.0;

#if defined(__x86_64__) || defined(__i386__)
    auto estimate_cycles_per_ns = []() -> double {
        const auto wall0 = std::chrono::high_resolution_clock::now();
        const std::uint64_t c0 = __rdtsc();
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        const std::uint64_t c1 = __rdtsc();
        const auto wall1 = std::chrono::high_resolution_clock::now();
        const auto ns = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(wall1 - wall0).count());
        return (ns > 0.0) ? static_cast<double>(c1 - c0) / ns : 1.0;
    };

    const double cycles_per_ns = estimate_cycles_per_ns();

    const std::uint64_t c0 = __rdtsc();
    for (std::size_t i = 0; i < n_ops; ++i) {
        Order* o = pool.acquire();
        if (o == nullptr) {
            std::cerr << "Pool exhausted\n";
            return 1;
        }
        o->order_id = static_cast<std::uint64_t>(i + 1);
        o->price = 10'000 + static_cast<std::int64_t>(i % 1000);
        o->qty = 100;
        pool.release(o);
    }
    const std::uint64_t c1 = __rdtsc();

    const double total_ns = static_cast<double>(c1 - c0) / cycles_per_ns;
    ns_per_op = total_ns / static_cast<double>(n_ops);
#else
    const auto t0 = std::chrono::high_resolution_clock::now();
    for (std::size_t i = 0; i < n_ops; ++i) {
        Order* o = pool.acquire();
        if (o == nullptr) {
            std::cerr << "Pool exhausted\n";
            return 1;
        }
        o->order_id = static_cast<std::uint64_t>(i + 1);
        o->price = 10'000 + static_cast<std::int64_t>(i % 1000);
        o->qty = 100;
        pool.release(o);
    }
    const auto t1 = std::chrono::high_resolution_clock::now();

    const auto total_ns = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    ns_per_op = total_ns / static_cast<double>(n_ops);
#endif

    std::cout << std::fixed << std::setprecision(2)
              << "Pool acquire+release: " << ns_per_op << " ns/op\n";

    return 0;
}
