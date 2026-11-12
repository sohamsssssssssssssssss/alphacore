#include "engine.hpp"

#include <chrono>
#include <cstdlib>
#include <thread>

#ifdef __APPLE__
#include <pthread.h>
#include <pthread/qos.h>
#endif

namespace {
std::uint64_t now_ns() {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
}
}  // namespace

// Set current thread to high QoS (performance cores on Apple Silicon)
static inline void set_perf_qos() {
#ifdef __APPLE__
    pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
#endif
}

WorkerThread::WorkerThread(std::int64_t min_price,
                           std::int64_t max_price,
                           std::int64_t tick_size,
                           MpscQueue<Trade, (1u << 20)>* out,
                           std::int64_t price_band_center,
                           std::int64_t price_band_half_width)
    : running_(false), thread_(), in_queue_(), bid_book_(min_price, max_price, tick_size, false),
      ask_book_(min_price, max_price, tick_size, false), pool_(), out_trades_(out)
#ifdef ALPHACORE_FAULT_INJECT
      , price_band_center_(price_band_center), price_band_half_width_(price_band_half_width)
#endif
{}

WorkerThread::~WorkerThread() {
    request_stop();
    join();
}

bool WorkerThread::enqueue(const Order& order) {
    return in_queue_.push(order);
}

void WorkerThread::start() {
    running_.store(true, std::memory_order_release);
    thread_ = std::thread([this]() {
        set_perf_qos();
        run();
    });
}

void WorkerThread::request_stop() {
    running_.store(false, std::memory_order_release);
}

void WorkerThread::join() {
    if (thread_.joinable()) {
        thread_.join();
    }
}

#ifdef ALPHACORE_FAULT_INJECT
bool WorkerThread::check_order_safety(const Order& incoming) {
    // --- CHECK 1: Self-trade prevention ---
    // Reject an order if it would trade against a resting order from the same session.
    if (incoming.side == Side::BID) {
        PriceLevel* best_ask = ask_book_.best_ask();
        if (best_ask && best_ask->head) {
            // The best ask's head is the order at the front of the queue
            Order* top = best_ask->head;
            if (top->session_id == incoming.session_id && top->session_id != 0) {
                return false; // self-trade detected
            }
        }
    } else {
        PriceLevel* best_bid = bid_book_.best_bid();
        if (best_bid && best_bid->head) {
            Order* top = best_bid->head;
            if (top->session_id == incoming.session_id && top->session_id != 0) {
                return false; // self-trade detected
            }
        }
    }

    // --- CHECK 2: Wash-trade heuristic ---
    // Flag same-account cross: both sides of the potential trade belong to same account.
    if (incoming.side == Side::BID) {
        PriceLevel* best_ask = ask_book_.best_ask();
        if (best_ask && best_ask->head) {
            Order* top = best_ask->head;
            if (top->account_id == incoming.account_id && top->account_id != 0) {
                return false; // wash-trade detected
            }
        }
    } else {
        PriceLevel* best_bid = bid_book_.best_bid();
        if (best_bid && best_bid->head) {
            Order* top = best_bid->head;
            if (top->account_id == incoming.account_id && top->account_id != 0) {
                return false; // wash-trade detected
            }
        }
    }

    // --- CHECK 3: Limit-up / limit-down price band ---
    // Reject orders with price outside [center - half_width, center + half_width].
    if (price_band_half_width_ > 0) {
        const std::int64_t low = price_band_center_ - price_band_half_width_;
        const std::int64_t high = price_band_center_ + price_band_half_width_;
        if (incoming.price < low || incoming.price > high) {
            return false; // price outside band
        }
    }

    return true;
}
#endif

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
#ifdef ALPHACORE_FAULT_INJECT
    // Run real safety checks. If any check fails, the order is silently dropped
    // (in a real system this would send a rejection message to the client).
    if (!check_order_safety(incoming)) {
        return;
    }
#endif

    Order* live = pool_.acquire(incoming.order_id, incoming.price, incoming.qty, incoming.side,
                                incoming.symbol_id, incoming.timestamp_ns,
                                incoming.session_id, incoming.account_id);
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
                               std::int64_t tick_size,
                               std::int64_t price_band)
    : started_(false), workers_(), trades_out_(), price_band_(price_band) {
    const std::size_t threads = (num_threads == 0) ? 1 : num_threads;
    workers_.reserve(threads);
    for (std::size_t i = 0; i < threads; ++i) {
        workers_.push_back(std::make_unique<WorkerThread>(min_price, max_price, tick_size, &trades_out_, 500, price_band_));
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

std::vector<BookSnapshot> MatchingEngine::snapshot_all() const {
    std::vector<BookSnapshot> result;
    result.reserve(workers_.size());
    for (std::size_t i = 0; i < workers_.size(); ++i) {
        BookSnapshot snap;
        snap.symbol_id = static_cast<std::uint32_t>(i);
        snap.bids = workers_[i]->snapshot_bids();
        snap.asks = workers_[i]->snapshot_asks();
        result.push_back(std::move(snap));
    }
    return result;
}
