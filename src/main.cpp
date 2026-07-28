#include <iostream>
#include "orderbook.hpp"

int main() {
    OrderBook book;

    Order buy;
    buy.order_id    = 1;
    buy.set_symbol("RELIANCE");
    buy.side        = Side::BID;
    buy.type        = OrderType::LIMIT;
    buy.price       = 254750; // 2547.50 INR in paisa
    buy.quantity    = 100;
    buy.timestamp_ns = 0;

    Order sell;
    sell.order_id    = 2;
    sell.set_symbol("RELIANCE");
    sell.side        = Side::ASK;
    sell.type        = OrderType::LIMIT;
    sell.price       = 254750;
    sell.quantity    = 60;
    sell.timestamp_ns = 0;

    book.add_order(buy);
    auto trades = book.add_order(sell);

    std::cout << "Trades executed: " << trades.size() << "\n";
    for (auto& t : trades) {
        std::cout << "  qty=" << t.quantity
                  << " price=" << t.price << " paisa\n";
    }
    std::cout << "Bid levels remaining: " << book.bid_levels() << "\n";
    return 0;
}
