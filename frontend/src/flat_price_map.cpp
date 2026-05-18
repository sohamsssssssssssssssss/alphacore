#include "flat_price_map.hpp"

void PriceLevel::push_back(Order* order) {
    order->prev = tail;
    order->next = nullptr;

    if (tail != nullptr) {
        tail->next = order;
    } else {
        head = order;
    }

    tail = order;
    total_qty += order->qty;
}

void PriceLevel::unlink(Order* order) {
    if (order->prev != nullptr) {
        order->prev->next = order->next;
    } else {
        head = order->next;
    }

    if (order->next != nullptr) {
        order->next->prev = order->prev;
    } else {
        tail = order->prev;
    }

    total_qty -= order->qty;
    order->prev = nullptr;
    order->next = nullptr;
}

bool PriceLevel::empty() const {
    return head == nullptr;
}

FlatPriceMap::FlatPriceMap(std::int64_t min_price, std::int64_t max_price, std::int64_t tick_size, bool owns_orders)
    : min_price_(min_price),
      max_price_(max_price),
      tick_size_(tick_size),
      owns_orders_(owns_orders),
      slots_(0),
      unit_tick_(tick_size == 1),
      levels_(),
      level_active_(),
      order_index_(),
      best_bid_idx_{-1},
      best_ask_idx_{-1} {
    if (tick_size_ <= 0) {
        throw std::invalid_argument("tick_size must be positive");
    }
    if (max_price_ <= min_price_) {
        throw std::invalid_argument("max_price must be greater than min_price");
    }
    if ((max_price_ - min_price_) % tick_size_ != 0) {
        throw std::invalid_argument("price range must be divisible by tick_size");
    }

    slots_ = static_cast<std::size_t>((max_price_ - min_price_) / tick_size_);
    levels_.assign(slots_, PriceLevel{});
    level_active_.assign(slots_, 0);
}

FlatPriceMap::~FlatPriceMap() {
    if (owns_orders_) {
        for (std::size_t i = 0; i < slots_; ++i) {
            if (level_active_[i] == 0) {
                continue;
            }
            Order* curr = levels_[i].head;
            while (curr != nullptr) {
                Order* next = curr->next;
                delete curr;
                curr = next;
            }
        }
    }
}

std::size_t FlatPriceMap::price_to_index(std::int64_t price) const {
    if (price < min_price_ || price >= max_price_) {
        throw std::out_of_range("price out of range");
    }

    const std::int64_t diff = price - min_price_;
    if (!unit_tick_ && (diff % tick_size_ != 0)) {
        throw std::invalid_argument("price not aligned to tick_size");
    }

    return unit_tick_ ? static_cast<std::size_t>(diff) : static_cast<std::size_t>(diff / tick_size_);
}

void FlatPriceMap::insert(std::int64_t price, Order* order) {
    if (order == nullptr) {
        throw std::invalid_argument("order must not be null");
    }

    const std::size_t idx = price_to_index(price);

    PriceLevel& level = levels_[idx];
    if (level_active_[idx] == 0) {
        level_active_[idx] = 1;
    }

    level.push_back(order);
    const std::size_t oid = static_cast<std::size_t>(order->order_id);
    if (oid >= order_index_.size()) {
        std::size_t new_size = order_index_.empty() ? 1024 : order_index_.size();
        while (new_size <= oid) {
            new_size <<= 1u;
        }
        order_index_.resize(new_size, nullptr);
    }
    order_index_[oid] = order;

    const std::ptrdiff_t pidx = static_cast<std::ptrdiff_t>(idx);
    if (best_bid_idx_.value < pidx) {
        best_bid_idx_.value = pidx;
    }
    if (best_ask_idx_.value == -1 || pidx < best_ask_idx_.value) {
        best_ask_idx_.value = pidx;
    }
}

bool FlatPriceMap::remove(std::int64_t price, std::uint64_t order_id) {
    const std::size_t oid = static_cast<std::size_t>(order_id);
    if (oid >= order_index_.size()) {
        return false;
    }
    Order* order = order_index_[oid];
    if (order == nullptr) {
        return false;
    }
    const std::size_t idx = price_to_index(price);
    if (level_active_[idx] == 0) {
        return false;
    }
    PriceLevel& level = levels_[idx];

    level.unlink(order);
    order_index_[oid] = nullptr;
    if (owns_orders_) {
        delete order;
    }

    if (level.empty()) {
        level_active_[idx] = 0;

        if (best_bid_idx_.value == static_cast<std::ptrdiff_t>(idx)) {
            // Scan downward to preserve nearby best-bid locality.
            best_bid_idx_.value = -1;
            for (std::ptrdiff_t i = static_cast<std::ptrdiff_t>(idx) - 1; i >= 0; --i) {
                if (level_active_[static_cast<std::size_t>(i)] != 0) {
                    best_bid_idx_.value = i;
                    break;
                }
            }
        }
        if (best_ask_idx_.value == static_cast<std::ptrdiff_t>(idx)) {
            // Scan upward to preserve nearby best-ask locality.
            best_ask_idx_.value = -1;
            for (std::ptrdiff_t i = static_cast<std::ptrdiff_t>(idx) + 1; i < static_cast<std::ptrdiff_t>(slots_); ++i) {
                if (level_active_[static_cast<std::size_t>(i)] != 0) {
                    best_ask_idx_.value = i;
                    break;
                }
            }
        }
    }

    return true;
}

PriceLevel* FlatPriceMap::best_bid() {
    if (levels_.empty()) {
        return nullptr;
    }

    std::ptrdiff_t start = best_bid_idx_.value;
    if (start < 0 || start >= static_cast<std::ptrdiff_t>(slots_)) {
        start = static_cast<std::ptrdiff_t>(slots_) - 1;
    }

    for (std::ptrdiff_t i = start; i >= 0; --i) {
        if (level_active_[static_cast<std::size_t>(i)] != 0) {
            best_bid_idx_.value = i;
            return &levels_[static_cast<std::size_t>(i)];
        }
    }

    best_bid_idx_.value = -1;
    return nullptr;
}

PriceLevel* FlatPriceMap::best_ask() {
    if (levels_.empty()) {
        return nullptr;
    }

    std::ptrdiff_t start = best_ask_idx_.value;
    if (start < 0 || start >= static_cast<std::ptrdiff_t>(slots_)) {
        start = 0;
    }

    for (std::ptrdiff_t i = start; i < static_cast<std::ptrdiff_t>(slots_); ++i) {
        if (level_active_[static_cast<std::size_t>(i)] != 0) {
            best_ask_idx_.value = i;
            return &levels_[static_cast<std::size_t>(i)];
        }
    }

    best_ask_idx_.value = -1;
    return nullptr;
}

std::int64_t FlatPriceMap::best_bid_price() const {
    for (std::ptrdiff_t i = static_cast<std::ptrdiff_t>(slots_) - 1; i >= 0; --i) {
        if (level_active_[static_cast<std::size_t>(i)] != 0) {
            return min_price_ + static_cast<std::int64_t>(i) * tick_size_;
        }
    }
    return -1;
}

std::int64_t FlatPriceMap::best_ask_price() const {
    for (std::size_t i = 0; i < slots_; ++i) {
        if (level_active_[i] != 0) {
            return min_price_ + static_cast<std::int64_t>(i) * tick_size_;
        }
    }
    return -1;
}
