// AlphaCore — Full Order-Add Latency Benchmark
// ==============================================
// Measures the complete order-Add pipeline from producer enqueue through
// consumer dequeue, FlatPriceMap insert, and Pool allocation, including
// queuing delay under contention (N concurrent producers).
//
// NOTE: MatchingEngine contains MpscQueue<Trade, (1u<<20)> which is ~50MB.
// Engine MUST be heap-allocated to avoid stack overflow.
//
// What it measures:
//   MPSC enqueue (producer side) -> queuing delay ->
//   MPSC dequeue (consumer worker thread) ->
//   Pool order object allocation ->
//   FlatPriceMap insert ->
//   (If match) Trade publication to output queue
//
// What it does NOT include:
//   FIX message parsing / serialization (separate gateway bench)
//   Journal / WAL writing
//   Network I/O
//   Risk / compliance checks
//
// Methodology:
//   - Each mode runs as a SEPARATE process invocation to prevent cache/TLB
//     pollution between measurement phases (the dominant cause of the
//     previously observed 2.5x variance).
//   - Within a process, run_add_bench() is called TWICE: the first call
//     warms caches and its result is discarded; the second call is reported.
//   - Latency distribution uses a batching approach (N=100 calls per batch)
//     to avoid sub-nanosecond timer-resolution artifacts on macOS.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <random>
#include <thread>
#include <vector>

#include "../src/engine.hpp"
#include "../src/mpsc_queue.hpp"

// For latency distribution, we batch N iterations to amortize timer overhead
// and avoid sub-nanosecond resolution issues on macOS.
constexpr std::size_t LATENCY_BATCH_SIZE = 100;

// Must fit within WorkerThread's Pool<Order, 100000> capacity
constexpr std::size_t kSymbolCount = 4;
constexpr std::size_t kOrdersPerProducer = 50'000;
constexpr std::size_t kTotalOrders = kSymbolCount * kOrdersPerProducer;

// Kernel objects for the benchmark
struct ProducerState {
    std::uint32_t symbol_id;
    std::vector<std::int64_t> prices;
    std::vector<std::uint32_t> qtys;
    std::vector<std::uint32_t> sessions;
    std::vector<std::uint32_t> accounts;
};

static double run_add_bench(std::size_t num_symbols,
                            std::size_t orders_per_producer) {
    std::mt19937_64 rng(42);
    std::uniform_int_distribution<std::int64_t> price_dist(100, 900);
    std::uniform_int_distribution<std::uint32_t> qty_dist(1, 100);
    std::uniform_int_distribution<std::uint32_t> session_dist(1, 10);
    std::uniform_int_distribution<std::uint32_t> account_dist(1, 10);

    std::vector<ProducerState> producers(num_symbols);
    std::uint64_t oid_base = 0;
    for (std::size_t s = 0; s < num_symbols; ++s) {
        producers[s].symbol_id = static_cast<std::uint32_t>(s);
        producers[s].prices.reserve(orders_per_producer);
        producers[s].qtys.reserve(orders_per_producer);
        producers[s].sessions.reserve(orders_per_producer);
        producers[s].accounts.reserve(orders_per_producer);
        for (std::size_t i = 0; i < orders_per_producer; ++i) {
            producers[s].prices.push_back(price_dist(rng));
            producers[s].qtys.push_back(qty_dist(rng));
            producers[s].sessions.push_back(session_dist(rng));
            producers[s].accounts.push_back(account_dist(rng));
        }
    }

    // Heap-allocate to avoid stack overflow (50MB internal queue)
    auto engine = std::make_unique<MatchingEngine>(num_symbols, 1, 1000, 1, 500);
    engine->start();

    std::atomic<std::size_t> producer_done{0};
    std::atomic<std::size_t> trade_count{0};
    std::atomic<bool> consumer_done{false};

    // Each producer gets its own oid range to avoid any shared-state synchronization
    std::atomic<std::uint64_t> next_oid{oid_base + 1};

    auto t0 = std::chrono::high_resolution_clock::now();

    // Consumer drain thread: wait until all producers finish, then drain everything
    std::thread consumer([&]() {
        Trade t;
        // Spin until all producers are done
        while (producer_done.load(std::memory_order_acquire) < num_symbols) {
            while (engine->pop_trade(t)) {
                trade_count.fetch_add(1, std::memory_order_relaxed);
            }
            std::this_thread::yield();
        }
        // Final drain: exhaust any remaining trades
        while (engine->pop_trade(t)) {
            trade_count.fetch_add(1, std::memory_order_relaxed);
        }
        consumer_done.store(true, std::memory_order_release);
    });

    // Producer threads: each one uses its own pre-computed per-producer order IDs
    std::vector<std::thread> producer_threads;
    producer_threads.reserve(num_symbols);

    for (std::size_t s = 0; s < num_symbols; ++s) {
        producer_threads.emplace_back([&, s]() {
            const auto& prod = producers[s];
            for (std::size_t i = 0; i < orders_per_producer; ++i) {
                Side side = (i % 2 == 0) ? Side::BID : Side::ASK;
                const std::uint64_t oid = next_oid.fetch_add(1, std::memory_order_relaxed);
                engine->route(Order(oid, prod.prices[i], prod.qtys[i],
                                    side, prod.symbol_id, 0,
                                    prod.sessions[i], prod.accounts[i]));
            }
            producer_done.fetch_add(1, std::memory_order_release);
        });
    }

    for (auto& th : producer_threads) th.join();

    // Wait for consumer with timeout
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!consumer_done.load(std::memory_order_acquire)) {
        if (std::chrono::steady_clock::now() > deadline) {
            std::cerr << "WARNING: Consumer timeout. "
                      << trade_count.load() << " trades\n";
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    consumer.join();

    auto t1 = std::chrono::high_resolution_clock::now();
    engine->stop();

    double elapsed_ns = static_cast<double>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    return elapsed_ns / static_cast<double>(num_symbols * orders_per_producer);
}

static std::vector<double> measure_latency_samples(std::size_t num_symbols,
                                                     std::size_t orders_per_symbol) {
    std::mt19937_64 rng(99);
    std::uniform_int_distribution<std::int64_t> price_dist(100, 900);
    std::uniform_int_distribution<std::uint32_t> qty_dist(1, 100);
    std::uniform_int_distribution<std::uint32_t> session_dist(1, 10);
    std::uniform_int_distribution<std::uint32_t> account_dist(1, 10);

    // Price band: center=500, half_width=500 -> covers [0, 1000] to include all prices
    auto engine = std::make_unique<MatchingEngine>(num_symbols, 1, 1000, 1, 500);
    engine->start();

    // Warm-up: 500 orders with all fields populated (including session/account
    // for the safety-check path)
    std::uint64_t oid = 100'000;
    for (std::size_t i = 0; i < 500; ++i) {
        engine->route(Order(++oid, price_dist(rng), qty_dist(rng),
                            (i % 2 == 0) ? Side::BID : Side::ASK,
                            static_cast<std::uint32_t>(i % num_symbols),
                            0,
                            session_dist(rng),
                            account_dist(rng)));
    }
    Trade dummy;
    while (engine->pop_trade(dummy)) {}

    // Drain thread
    std::atomic<bool> drain_done{false};
    std::thread drain([&]() {
        while (!drain_done.load(std::memory_order_acquire)) {
            Trade t;
            while (engine->pop_trade(t)) {}
            std::this_thread::yield();
        }
    });

    // Measure individual route() latency using batch timing to avoid
    // sub-nanosecond resolution issues. Each sample is the mean of
    // LATENCY_BATCH_SIZE consecutive calls.
    const std::size_t total = num_symbols * orders_per_symbol;
    const std::size_t num_batches = total / LATENCY_BATCH_SIZE;
    std::vector<double> latencies;
    latencies.reserve(num_batches);

    for (std::size_t b = 0; b < num_batches; ++b) {
        auto t0 = std::chrono::high_resolution_clock::now();
        for (std::size_t i = 0; i < LATENCY_BATCH_SIZE; ++i) {
            std::size_t idx = b * LATENCY_BATCH_SIZE + i;
            std::size_t s = idx / orders_per_symbol;
            std::int64_t px = price_dist(rng);
            std::uint32_t qty = qty_dist(rng);
            Side side = (i % 2 == 0) ? Side::BID : Side::ASK;
            engine->route(Order(++oid, px, qty, side, static_cast<std::uint32_t>(s),
                                0, session_dist(rng), account_dist(rng)));
        }
        auto t1 = std::chrono::high_resolution_clock::now();
        double batch_ns = static_cast<double>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
        latencies.push_back(batch_ns / static_cast<double>(LATENCY_BATCH_SIZE));
    }

    drain_done.store(true, std::memory_order_release);
    while (engine->pop_trade(dummy)) {}
    engine->stop();
    drain.join();

    return latencies;
}

// Single-mode: lean_throughput | lean_latency | full_throughput | full_latency
// Each mode runs as a separate process invocation to avoid cache/TLB pollution
// between measurement phases (confirmed cause of 2.5x variance).
// Within a process, run_add_bench() is called TWICE: first warms caches,
// the second call is the reported measurement.

static void do_throughput(const char* label) {
    // Call 1: warmup (result discarded — brings caches to steady state)
    run_add_bench(kSymbolCount, kOrdersPerProducer);
    // Call 2: measured
    double ns = run_add_bench(kSymbolCount, kOrdersPerProducer);
    double mops = (1'000'000'000.0 / ns) / 1'000'000.0;
    std::cout << std::fixed << std::setprecision(2);
    std::cout << "RESULT throughput " << label << " " << ns << " " << mops << "\n";
    
    // Additional intra-process runs to test variance
    for (int i = 0; i < 3; ++i) {
        ns = run_add_bench(kSymbolCount, kOrdersPerProducer);
        mops = (1'000'000'000.0 / ns) / 1'000'000.0;
        std::cout << "RESULT throughput " << label << " (extra) " << ns << " " << mops << "\n";
    }
}

static void do_latency(const char* label) {
    // For latency distribution, the single-threaded warmup already runs 40K
    // orders so no extra warmup call is needed.
    auto samples = measure_latency_samples(kSymbolCount, 10000);
    std::sort(samples.begin(), samples.end());
    std::size_t n = samples.size();
    double sum = std::accumulate(samples.begin(), samples.end(), 0.0);
    double avg = sum / static_cast<double>(n);
    double p50 = samples[static_cast<std::size_t>(n * 0.50)];
    double p99 = samples[static_cast<std::size_t>(n * 0.99)];
    double min_val = samples[0];
    double max_val = samples[n - 1];
    std::cout << std::fixed << std::setprecision(2);
    std::cout << "RESULT latency " << label
              << " avg=" << avg << " p50=" << p50
              << " p99=" << p99 << " min=" << min_val
              << " max=" << max_val << "\n";
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: add_bench <mode>\n";
        std::cerr << "  Modes: lean_throughput lean_latency";
#ifdef ALPHACORE_FAULT_INJECT
        std::cerr << " full_throughput full_latency";
#endif
        std::cerr << "\n";
        return 1;
    }

    std::string mode = argv[1];

    if (mode == "lean_throughput" || mode == "lean_latency") {
        const char* label = "lean";
        if (mode == "lean_throughput") {
            do_throughput(label);
        } else {
            do_latency(label);
        }
#ifdef ALPHACORE_FAULT_INJECT
    } else if (mode == "full_throughput" || mode == "full_latency") {
        const char* label = "full";
        if (mode == "full_throughput") {
            do_throughput(label);
        } else {
            do_latency(label);
        }
#endif
    } else {
        std::cerr << "Unknown mode: " << mode << "\n";
        return 1;
    }

    return 0;
}
