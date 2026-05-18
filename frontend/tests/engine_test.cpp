#include <chrono>
#include <cstdint>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>

#include "../src/engine.hpp"

namespace {

bool wait_for_trades(MatchingEngine& engine, std::vector<Trade>& out, std::size_t expected, int timeout_ms = 1000) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    Trade t{};
    while (std::chrono::steady_clock::now() < deadline) {
        while (engine.pop_trade(t)) {
            out.push_back(t);
            if (out.size() >= expected) {
                return true;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return out.size() >= expected;
}

void print_result(const char* name, bool ok) {
    std::cout << name << ": " << (ok ? "PASS" : "FAIL") << "\n";
}

}  // namespace

int main() {
    bool overall = true;

    {
        auto engine = std::make_unique<MatchingEngine>(1, 1, 1000, 1);
        engine->start();

        engine->route(Order(1, 100, 10, Side::BID, 7));
        engine->route(Order(2, 100, 10, Side::ASK, 7));

        std::vector<Trade> trades;
        const bool got = wait_for_trades(*engine, trades, 1);
        const bool ok = got && trades[0].price == 100 && trades[0].qty == 10;
        print_result("Exact match", ok);
        overall = overall && ok;

        engine->stop();
    }

    {
        auto engine = std::make_unique<MatchingEngine>(1, 1, 1000, 1);
        engine->start();

        engine->route(Order(10, 100, 10, Side::BID, 9));
        engine->route(Order(11, 99, 6, Side::ASK, 9));
        engine->route(Order(12, 100, 10, Side::ASK, 9));

        std::vector<Trade> trades;
        const bool got = wait_for_trades(*engine, trades, 2);

        bool qty_ok = false;
        bool px_ok = true;
        if (got && trades.size() >= 2) {
            const std::uint32_t total = trades[0].qty + trades[1].qty;
            qty_ok = (total == 10);
            px_ok = (trades[0].price == 100 && trades[1].price == 100);
        }

        const bool ok = got && qty_ok && px_ok;
        print_result("Partial fill", ok);
        overall = overall && ok;

        engine->stop();
    }

    return overall ? 0 : 1;
}
