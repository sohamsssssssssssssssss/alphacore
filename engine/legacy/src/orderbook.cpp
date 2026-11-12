#include "orderbook.hpp"
#include <chrono>

static uint64_t now_ns() {
    return std::chrono::steady_clock::now().time_since_epoch().count();
}

std::vector<Trade> OrderBook::add_order(Order& order) {
    order.remaining = order.quantity;
    order.status    = OrderStatus::OPEN;

    std::vector<Trade> trades = match(order);

    if (order.remaining > 0 && order.type == OrderType::LIMIT) {
        orders_[order.order_id] = order;
        Order* stored = &orders_[order.order_id];
        if (order.side == Side::BID)
            bids_[order.price].push_back(stored);
        else
            asks_[order.price].push_back(stored);
    }

    return trades;
}

std::vector<Trade> OrderBook::match(Order& incoming) {
    std::vector<Trade> trades;

    while (incoming.remaining > 0) {
        if (incoming.side == Side::BID) {
            if (asks_.empty()) break;
            auto best_it = asks_.begin();
            if (incoming.price < best_it->first) break;

            auto& level = best_it->second;
            while (incoming.remaining > 0 && !level.empty()) {
                Order* resting = level.front();
                uint64_t fill_qty = std::min(incoming.remaining, resting->remaining);

                Trade t;
                t.price         = best_it->first;
                t.quantity      = fill_qty;
                t.timestamp_ns  = now_ns();
                t.buy_order_id  = incoming.order_id;
                t.sell_order_id = resting->order_id;
                trades.push_back(t);

                incoming.remaining -= fill_qty;
                resting->remaining -= fill_qty;

                if (resting->remaining == 0) {
                    resting->status = OrderStatus::FILLED;
                    orders_.erase(resting->order_id);
                    level.pop_front();
                } else {
                    resting->status = OrderStatus::PARTIAL;
                }
            }
            if (level.empty()) asks_.erase(best_it);

        } else {
            if (bids_.empty()) break;
            auto best_it = bids_.begin();
            if (incoming.price > best_it->first) break;

            auto& level = best_it->second;
            while (incoming.remaining > 0 && !level.empty()) {
                Order* resting = level.front();
                uint64_t fill_qty = std::min(incoming.remaining, resting->remaining);

                Trade t;
                t.price         = best_it->first;
                t.quantity      = fill_qty;
                t.timestamp_ns  = now_ns();
                t.buy_order_id  = resting->order_id;
                t.sell_order_id = incoming.order_id;
                trades.push_back(t);

                incoming.remaining -= fill_qty;
                resting->remaining -= fill_qty;

                if (resting->remaining == 0) {
                    resting->status = OrderStatus::FILLED;
                    orders_.erase(resting->order_id);
                    level.pop_front();
                } else {
                    resting->status = OrderStatus::PARTIAL;
                }
            }
            if (level.empty()) bids_.erase(best_it);
        }
    }

    if (incoming.remaining == 0)
        incoming.status = OrderStatus::FILLED;
    else if (incoming.remaining < incoming.quantity)
        incoming.status = OrderStatus::PARTIAL;

    return trades;
}

bool OrderBook::cancel_order(uint64_t order_id) {
    auto it = orders_.find(order_id);
    if (it == orders_.end()) return false;

    Order& o = it->second;

    if (o.side == Side::BID) {
        auto level_it = bids_.find(o.price);
        if (level_it != bids_.end()) {
            level_it->second.remove_if([order_id](Order* p){ return p->order_id == order_id; });
            if (level_it->second.empty()) bids_.erase(level_it);
        }
    } else {
        auto level_it = asks_.find(o.price);
        if (level_it != asks_.end()) {
            level_it->second.remove_if([order_id](Order* p){ return p->order_id == order_id; });
            if (level_it->second.empty()) asks_.erase(level_it);
        }
    }

    o.status = OrderStatus::CANCELLED;
    orders_.erase(it);
    return true;
}

std::optional<int64_t> OrderBook::best_bid() const {
    if (bids_.empty()) return std::nullopt;
    return bids_.begin()->first;
}

std::optional<int64_t> OrderBook::best_ask() const {
    if (asks_.empty()) return std::nullopt;
    return asks_.begin()->first;
}

std::optional<int64_t> OrderBook::spread() const {
    auto bid = best_bid();
    auto ask = best_ask();
    if (!bid || !ask) return std::nullopt;
    return *ask - *bid;
}
