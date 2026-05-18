#pragma once

#include <atomic>
#include <cstdint>
#include <memory>
#include <thread>
#include <vector>

#include "flat_price_map.hpp"
#include "mpsc_queue.hpp"
#include "pool.hpp"

struct Trade {
    std::uint64_t buy_order_id;
    std::uint64_t sell_order_id;
    std::int64_t price;
    std::uint32_t qty;
    std::uint64_t timestamp_ns;
};

class WorkerThread {
public:
    WorkerThread(std::int64_t min_price, std::int64_t max_price, std::int64_t tick_size, MpscQueue<Trade, (1u << 20)>* out);
    ~WorkerThread();

    WorkerThread(const WorkerThread&) = delete;
    WorkerThread& operator=(const WorkerThread&) = delete;

    bool enqueue(const Order& order);
    void start();
    void request_stop();
    void join();

private:
    void run();
    void handle_order(const Order& incoming);
    void match_bid(Order* bid);
    void match_ask(Order* ask);
    void publish_trade(std::uint64_t buy_id, std::uint64_t sell_id, std::int64_t px, std::uint32_t qty);

    std::atomic<bool> running_;
    std::thread thread_;

    MpscQueue<Order, 65536> in_queue_;
    FlatPriceMap bid_book_;
    FlatPriceMap ask_book_;
    Pool<Order, 100000> pool_;
    MpscQueue<Trade, (1u << 20)>* out_trades_;
};

class MatchingEngine {
public:
    explicit MatchingEngine(std::size_t num_threads = std::thread::hardware_concurrency(),
                            std::int64_t min_price = 1,
                            std::int64_t max_price = 1'000'001,
                            std::int64_t tick_size = 1);
    ~MatchingEngine();

    MatchingEngine(const MatchingEngine&) = delete;
    MatchingEngine& operator=(const MatchingEngine&) = delete;

    void start();
    void stop();
    void route(const Order& order);

    bool pop_trade(Trade& trade);

private:
    std::size_t route_worker(std::uint32_t symbol_id) const;

    std::atomic<bool> started_;
    std::vector<std::unique_ptr<WorkerThread>> workers_;
    MpscQueue<Trade, (1u << 20)> trades_out_;
};
