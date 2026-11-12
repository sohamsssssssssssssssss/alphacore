#include <iostream>
#include <chrono>
#include <vector>
#include "orderbook.hpp"

int main() {
    const int NUM_ORDERS = 1'000'000;

    // Pre-build orders so benchmark doesn't measure object construction
    std::vector<Order> orders;
    orders.reserve(NUM_ORDERS);

    for (int i = 0; i < NUM_ORDERS; i++) {
        Order o;
        o.order_id     = i + 1;
        o.set_symbol("RELIANCE");
        o.type         = OrderType::LIMIT;
        o.timestamp_ns = 0;
        o.quantity     = 10;

        // Alternate bids and asks at slightly different prices
        // so they don't all match — we want resting orders too
        if (i % 2 == 0) {
            o.side  = Side::BID;
            o.price = 254700 + (i % 10);  // 254700 - 254709
        } else {
            o.side  = Side::ASK;
            o.price = 254800 + (i % 10);  // 254800 - 254809
        }
        orders.push_back(o);
    }

    OrderBook book;

    auto start = std::chrono::high_resolution_clock::now();

    for (auto& o : orders)
        book.add_order(o);

    auto end = std::chrono::high_resolution_clock::now();

    double total_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    double per_order_ns = total_ns / NUM_ORDERS;

    std::cout << "Orders processed : " << NUM_ORDERS << "\n";
    std::cout << "Total time       : " << (total_ns / 1e6) << " ms\n";
    std::cout << "Per order        : " << per_order_ns << " ns\n";
    std::cout << "Bid levels       : " << book.bid_levels() << "\n";
    std::cout << "Ask levels       : " << book.ask_levels() << "\n";

    return 0;
}
