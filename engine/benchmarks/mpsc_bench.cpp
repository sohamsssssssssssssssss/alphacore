#include <atomic>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <thread>
#include <vector>

#include "../src/mpsc_queue.hpp"

constexpr std::size_t producer_count = 4;
constexpr std::size_t items_per_producer = 1'000'000;
constexpr std::size_t total_items = producer_count * items_per_producer;
constexpr std::size_t queue_size = 1u << 20;

static MpscQueue<std::uint64_t, queue_size> q;

int main() {
    std::atomic<std::size_t> consumed{0};

    const auto t0 = std::chrono::high_resolution_clock::now();

    std::thread consumer([&]() {
        std::uint64_t value = 0;
        while (consumed.load(std::memory_order_relaxed) < total_items) {
            if (q.pop(value)) {
                consumed.fetch_add(1, std::memory_order_relaxed);
            } else {
                std::this_thread::yield();
            }
        }
    });

    std::vector<std::thread> producers;
    producers.reserve(producer_count);

    for (std::size_t p = 0; p < producer_count; ++p) {
        producers.emplace_back([&, p]() {
            const std::uint64_t base = static_cast<std::uint64_t>(p) << 32;
            for (std::size_t i = 0; i < items_per_producer; ++i) {
                const std::uint64_t item = base | static_cast<std::uint64_t>(i);
                while (!q.push(item)) {
                    std::this_thread::yield();
                }
            }
        });
    }

    for (auto& th : producers) {
        th.join();
    }
    consumer.join();

    const auto t1 = std::chrono::high_resolution_clock::now();
    const double seconds = std::chrono::duration<double>(t1 - t0).count();
    const double mops = (static_cast<double>(total_items) / 1'000'000.0) / seconds;

    std::cout << std::fixed << std::setprecision(2)
              << "MPSC throughput: " << mops << " M ops/sec\n";

    return 0;
}
