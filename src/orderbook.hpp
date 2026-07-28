#pragma once
#include <map>
#include <list>
#include <unordered_map>
#include <vector>
#include <optional>
#include "order.hpp"

struct Trade {
    uint64_t buy_order_id;
    uint64_t sell_order_id;
    int64_t  price;
    uint64_t quantity;
    uint64_t timestamp_ns;
};

class OrderBook {
public:
    // Add an order to the book. Returns trades if matching occurred.
    std::vector<Trade> add_order(Order& order);

    // Cancel an order by ID. Returns true if found and cancelled.
    bool cancel_order(uint64_t order_id);

    // Best bid price (highest buy). Empty if no bids.
    std::optional<int64_t> best_bid() const;

    // Best ask price (lowest sell). Empty if no asks.
    std::optional<int64_t> best_ask() const;

    // Spread in paisa. Empty if either side is empty.
    std::optional<int64_t> spread() const;

    size_t bid_levels() const { return bids_.size(); }
    size_t ask_levels() const { return asks_.size(); }

private:
    // bids: sorted descending (highest price first) — best bid at begin()
    // asks: sorted ascending (lowest price first) — best ask at begin()
    using PriceLevel = std::list<Order*>;

    std::map<int64_t, PriceLevel, std::greater<int64_t>> bids_;
    std::map<int64_t, PriceLevel>                        asks_;

    // Fast lookup: order_id -> pointer to order
    std::unordered_map<uint64_t, Order> orders_;

    std::vector<Trade> match(Order& incoming);
};
