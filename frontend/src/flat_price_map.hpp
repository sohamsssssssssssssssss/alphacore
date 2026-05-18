#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

enum class Side : std::uint8_t {
    BID,
    ASK,
};

struct Order {
    Order() : order_id(0), symbol_id(0), price(0), qty(0), side(Side::BID), timestamp_ns(0), prev(nullptr), next(nullptr) {}

    std::uint64_t order_id;
    std::uint32_t symbol_id;
    std::int64_t price;
    std::uint32_t qty;
    Side side;
    std::uint64_t timestamp_ns;

    Order* prev;
    Order* next;

    explicit Order(std::uint64_t id,
                   std::int64_t px,
                   std::uint32_t quantity,
                   Side s,
                   std::uint32_t symbol = 0,
                   std::uint64_t ts_ns = 0)
        : order_id(id),
          symbol_id(symbol),
          price(px),
          qty(quantity),
          side(s),
          timestamp_ns(ts_ns),
          prev(nullptr),
          next(nullptr) {}
};

struct PriceLevel {
    Order* head;
    Order* tail;
    std::uint64_t total_qty;

    PriceLevel() : head(nullptr), tail(nullptr), total_qty(0) {}

    void push_back(Order* order);
    void unlink(Order* order);
    bool empty() const;
};

class FlatPriceMap {
public:
    FlatPriceMap(std::int64_t min_price, std::int64_t max_price, std::int64_t tick_size, bool owns_orders = true);
    ~FlatPriceMap();

    FlatPriceMap(const FlatPriceMap&) = delete;
    FlatPriceMap& operator=(const FlatPriceMap&) = delete;

    void insert(std::int64_t price, Order* order);
    bool remove(std::int64_t price, std::uint64_t order_id);

    PriceLevel* best_bid();
    PriceLevel* best_ask();
    std::int64_t best_bid_price() const;
    std::int64_t best_ask_price() const;

private:
    std::size_t price_to_index(std::int64_t price) const;

    const std::int64_t min_price_;
    const std::int64_t max_price_;
    const std::int64_t tick_size_;
    const bool owns_orders_;
    std::size_t slots_;
    bool unit_tick_;

    std::vector<PriceLevel> levels_;
    std::vector<std::uint8_t> level_active_;
    std::vector<Order*> order_index_;

    struct alignas(64) CacheIndex {
        std::ptrdiff_t value;
    };
    CacheIndex best_bid_idx_;
    CacheIndex best_ask_idx_;
};
