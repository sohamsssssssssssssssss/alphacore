#include "engine.hpp"

#include <chrono>
#include <thread>

namespace {
std::uint64_t now_ns() {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
}
}  // namespace

WorkerThread::WorkerThread(std::int64_t min_price,
                           std::int64_t max_price,
                           std::int64_t tick_size,
                           MpscQueue<Trade, (1u << 20)>* out)
    : running_(false), thread_(), in_queue_(), bid_book_(min_price, max_price, tick_size, false), ask_book_(min_price, max_price, tick_size, false), pool_(), out_trades_(out) {}

WorkerThread::~WorkerThread() {
    request_stop();
    join();
}

bool WorkerThread::enqueue(const Order& order) {
    return in_queue_.push(order);
}

void WorkerThread::start() {
    running_.store(true, std::memory_order_release);
    thread_ = std::thread(&WorkerThread::run, this);
}

void WorkerThread::request_stop() {
    running_.store(false, std::memory_order_release);
}

void WorkerThread::join() {
    if (thread_.joinable()) {
        thread_.join();
    }
}

void WorkerThread::run() {
    Order incoming(0, 1, 0, Side::BID, 0);

    while (running_.load(std::memory_order_acquire)) {
        bool did_work = false;
        while (in_queue_.pop(incoming)) {
            did_work = true;
            handle_order(incoming);
        }
        if (!did_work) {
            std::this_thread::yield();
        }
    }

    while (in_queue_.pop(incoming)) {
        handle_order(incoming);
    }
}

void WorkerThread::handle_order(const Order& incoming) {
    Order* live = pool_.acquire(incoming.order_id, incoming.price, incoming.qty, incoming.side, incoming.symbol_id);
    if (live == nullptr) {
        return;
    }

    if (live->side == Side::BID) {
        match_bid(live);
    } else {
        match_ask(live);
    }
}

void WorkerThread::match_bid(Order* bid) {
    while (bid->qty > 0) {
        PriceLevel* best_ask_level = ask_book_.best_ask();
        if (best_ask_level == nullptr || best_ask_level->head == nullptr) {
            break;
        }

        Order* ask = best_ask_level->head;
        if (ask->price > bid->price) {
            break;
        }

        const std::uint32_t fill_qty = (bid->qty < ask->qty) ? bid->qty : ask->qty;
        const std::int64_t fill_px = ask->price;

        bid->qty -= fill_qty;
        ask->qty -= fill_qty;
        best_ask_level->total_qty -= fill_qty;

        publish_trade(bid->order_id, ask->order_id, fill_px, fill_qty);

        if (ask->qty == 0) {
            ask_book_.remove(ask->price, ask->order_id);
            pool_.release(ask);
            continue;
        }
    }

    if (bid->qty > 0) {
        bid_book_.insert(bid->price, bid);
    } else {
        pool_.release(bid);
    }
}

void WorkerThread::match_ask(Order* ask) {
    while (ask->qty > 0) {
        PriceLevel* best_bid_level = bid_book_.best_bid();
        if (best_bid_level == nullptr || best_bid_level->head == nullptr) {
            break;
        }

        Order* bid = best_bid_level->head;
        if (bid->price < ask->price) {
            break;
        }

        const std::uint32_t fill_qty = (ask->qty < bid->qty) ? ask->qty : bid->qty;
        const std::int64_t fill_px = bid->price;

        ask->qty -= fill_qty;
        bid->qty -= fill_qty;
        best_bid_level->total_qty -= fill_qty;

        publish_trade(bid->order_id, ask->order_id, fill_px, fill_qty);

        if (bid->qty == 0) {
            bid_book_.remove(bid->price, bid->order_id);
            pool_.release(bid);
            continue;
        }
    }

    if (ask->qty > 0) {
        ask_book_.insert(ask->price, ask);
    } else {
        pool_.release(ask);
    }
}

void WorkerThread::publish_trade(std::uint64_t buy_id,
                                 std::uint64_t sell_id,
                                 std::int64_t px,
                                 std::uint32_t qty) {
    Trade t{buy_id, sell_id, px, qty, now_ns()};
    while (!out_trades_->push(t)) {
        std::this_thread::yield();
    }
}

MatchingEngine::MatchingEngine(std::size_t num_threads,
                               std::int64_t min_price,
                               std::int64_t max_price,
                               std::int64_t tick_size)
    : started_(false), workers_(), trades_out_() {
    const std::size_t threads = (num_threads == 0) ? 1 : num_threads;
    workers_.reserve(threads);
    for (std::size_t i = 0; i < threads; ++i) {
        workers_.push_back(std::make_unique<WorkerThread>(min_price, max_price, tick_size, &trades_out_));
    }
}

MatchingEngine::~MatchingEngine() {
    stop();
}

void MatchingEngine::start() {
    bool expected = false;
    if (!started_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
        return;
    }

    for (auto& w : workers_) {
        w->start();
    }
}

void MatchingEngine::stop() {
    bool expected = true;
    if (!started_.compare_exchange_strong(expected, false, std::memory_order_acq_rel)) {
        return;
    }

    for (auto& w : workers_) {
        w->request_stop();
    }
    for (auto& w : workers_) {
        w->join();
    }
}

std::size_t MatchingEngine::route_worker(std::uint32_t symbol_id) const {
    return static_cast<std::size_t>(std::hash<std::uint32_t>{}(symbol_id) % workers_.size());
}

void MatchingEngine::route(const Order& order) {
    const std::size_t idx = route_worker(order.symbol_id);
    while (!workers_[idx]->enqueue(order)) {
        std::this_thread::yield();
    }
}

bool MatchingEngine::pop_trade(Trade& trade) {
    return trades_out_.pop(trade);
}
