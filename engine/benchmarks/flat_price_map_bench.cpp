#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <random>
#include <thread>
#include <vector>

#include "../src/flat_price_map.hpp"

#if defined(__x86_64__) || defined(__i386__)
#include <x86intrin.h>
#endif

int main() {
    constexpr std::int64_t min_price = 10'000;
    constexpr std::int64_t max_price = 20'000;
    constexpr std::int64_t tick_size = 1;
    constexpr std::size_t n_orders = 1'000'000;

    FlatPriceMap map(min_price, max_price, tick_size, false);

    std::mt19937_64 rng(42);
    std::uniform_int_distribution<std::int64_t> price_dist(min_price, max_price - tick_size);

    std::vector<Order> orders;
    orders.reserve(n_orders);
    for (std::size_t i = 0; i < n_orders; ++i) {
        orders.emplace_back(static_cast<std::uint64_t>(i + 1), price_dist(rng), 100, Side::BID);
    }

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
    for (std::size_t i = 0; i < n_orders; ++i) {
        map.insert(orders[i].price, &orders[i]);
    }
    const std::uint64_t c1 = __rdtsc();

    const double total_ns = static_cast<double>(c1 - c0) / cycles_per_ns;
    ns_per_op = total_ns / static_cast<double>(n_orders);
#else
    const auto t0 = std::chrono::high_resolution_clock::now();
    for (std::size_t i = 0; i < n_orders; ++i) {
        map.insert(orders[i].price, &orders[i]);
    }
    const auto t1 = std::chrono::high_resolution_clock::now();

    const auto total_ns = static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    ns_per_op = total_ns / static_cast<double>(n_orders);
#endif

    std::cout << std::fixed << std::setprecision(2)
              << "Insert: " << ns_per_op << " ns/op\n";

    return 0;
}
