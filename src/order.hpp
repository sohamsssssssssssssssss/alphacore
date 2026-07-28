#pragma once
#include <cstdint>
#include <cstring>

enum class Side : uint8_t {
    BID = 0,
    ASK = 1
};

enum class OrderType : uint8_t {
    LIMIT  = 0,
    MARKET = 1
};

enum class OrderStatus : uint8_t {
    OPEN      = 0,
    FILLED    = 1,
    CANCELLED = 2,
    PARTIAL   = 3
};

struct Order {
    uint64_t    order_id;
    uint64_t    timestamp_ns;
    int64_t     price;
    uint64_t    quantity;
    uint64_t    remaining;
    Side        side;
    OrderType   type;
    OrderStatus status;
    char        symbol[16];   // fixed size, no heap allocation

    void set_symbol(const char* s) {
        strncpy(symbol, s, 15);
        symbol[15] = '\0';
    }
};
