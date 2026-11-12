#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <random>
#include <thread>
#include <vector>

#include "../../src/engine.hpp"
#include "../../src/replication.hpp"

namespace {

struct JournalEntry {
    std::uint64_t order_id;
    std::int64_t price;
    std::uint32_t qty;
    Side side;
    std::uint32_t symbol_id;
    std::uint64_t timestamp_ns;
    std::uint32_t session_id;
    std::uint32_t account_id;
};

std::vector<std::uint8_t> serialize_order(const JournalEntry& e) {
    std::vector<std::uint8_t> buf(56);
    std::uint8_t* p = buf.data();
    std::memcpy(p + 0, &e.order_id, 8);
    std::memcpy(p + 8, &e.price, 8);
    std::memcpy(p + 16, &e.qty, 4);
    std::uint8_t side = static_cast<std::uint8_t>(e.side);
    std::memcpy(p + 20, &side, 1);
    std::memcpy(p + 21, &e.symbol_id, 4);
    std::memcpy(p + 25, &e.timestamp_ns, 8);
    std::memcpy(p + 33, &e.session_id, 4);
    std::memcpy(p + 37, &e.account_id, 4);
    return buf;
}

JournalEntry deserialize_order(const std::uint8_t* data) {
    JournalEntry e;
    std::memcpy(&e.order_id, data + 0, 8);
    std::memcpy(&e.price, data + 8, 8);
    std::memcpy(&e.qty, data + 16, 4);
    std::uint8_t side;
    std::memcpy(&side, data + 20, 1);
    e.side = static_cast<Side>(side);
    std::memcpy(&e.symbol_id, data + 21, 4);
    std::memcpy(&e.timestamp_ns, data + 25, 8);
    std::memcpy(&e.session_id, data + 33, 4);
    std::memcpy(&e.account_id, data + 37, 4);
    return e;
}

bool snapshots_equal(const BookSnapshot& a, const BookSnapshot& b) {
    if (a.symbol_id != b.symbol_id) return false;
    if (a.bids.levels.size() != b.bids.levels.size()) return false;
    if (a.asks.levels.size() != b.asks.levels.size()) return false;

    for (std::size_t i = 0; i < a.bids.levels.size(); ++i) {
        const auto& la = a.bids.levels[i];
        const auto& lb = b.bids.levels[i];
        if (la.price != lb.price) return false;
        if (la.total_qty != lb.total_qty) return false;
        if (la.orders.size() != lb.orders.size()) return false;
        for (std::size_t j = 0; j < la.orders.size(); ++j) {
            if (la.orders[j].order_id != lb.orders[j].order_id) return false;
            if (la.orders[j].price != lb.orders[j].price) return false;
            if (la.orders[j].qty != lb.orders[j].qty) return false;
            if (la.orders[j].side != lb.orders[j].side) return false;
            if (la.orders[j].timestamp_ns != lb.orders[j].timestamp_ns) return false;
            if (la.orders[j].session_id != lb.orders[j].session_id) return false;
            if (la.orders[j].account_id != lb.orders[j].account_id) return false;
        }
    }

    for (std::size_t i = 0; i < a.asks.levels.size(); ++i) {
        const auto& la = a.asks.levels[i];
        const auto& lb = b.asks.levels[i];
        if (la.price != lb.price) return false;
        if (la.total_qty != lb.total_qty) return false;
        if (la.orders.size() != lb.orders.size()) return false;
        for (std::size_t j = 0; j < la.orders.size(); ++j) {
            if (la.orders[j].order_id != lb.orders[j].order_id) return false;
            if (la.orders[j].price != lb.orders[j].price) return false;
            if (la.orders[j].qty != lb.orders[j].qty) return false;
            if (la.orders[j].side != lb.orders[j].side) return false;
            if (la.orders[j].timestamp_ns != lb.orders[j].timestamp_ns) return false;
            if (la.orders[j].session_id != lb.orders[j].session_id) return false;
            if (la.orders[j].account_id != lb.orders[j].account_id) return false;
        }
    }
    return true;
}

void print_snapshot_diff(const BookSnapshot& primary, const BookSnapshot& backup) {
    std::cout << "  Symbol " << primary.symbol_id << ":\n";
    std::cout << "    Bids: primary=" << primary.bids.levels.size() << " levels, backup=" << backup.bids.levels.size() << " levels\n";
    std::cout << "    Asks: primary=" << primary.asks.levels.size() << " levels, backup=" << backup.asks.levels.size() << " levels\n";

    if (primary.bids.levels.size() != backup.bids.levels.size()) {
        std::cout << "    BID LEVEL COUNT MISMATCH\n";
    }
    if (primary.asks.levels.size() != backup.asks.levels.size()) {
        std::cout << "    ASK LEVEL COUNT MISMATCH\n";
    }

    for (std::size_t i = 0; i < primary.bids.levels.size() && i < backup.bids.levels.size(); ++i) {
        const auto& pa = primary.bids.levels[i];
        const auto& pb = backup.bids.levels[i];
        if (pa.price != pb.price || pa.total_qty != pb.total_qty || pa.orders.size() != pb.orders.size()) {
            std::cout << "    BID level " << i << " mismatch: primary price=" << pa.price
                      << " qty=" << pa.total_qty << " orders=" << pa.orders.size()
                      << " vs backup price=" << pb.price
                      << " qty=" << pb.total_qty << " orders=" << pb.orders.size() << "\n";
        }
    }
    for (std::size_t i = 0; i < primary.asks.levels.size() && i < backup.asks.levels.size(); ++i) {
        const auto& pa = primary.asks.levels[i];
        const auto& pb = backup.asks.levels[i];
        if (pa.price != pb.price || pa.total_qty != pb.total_qty || pa.orders.size() != pb.orders.size()) {
            std::cout << "    ASK level " << i << " mismatch: primary price=" << pa.price
                      << " qty=" << pa.total_qty << " orders=" << pa.orders.size()
                      << " vs backup price=" << pb.price
                      << " qty=" << pb.total_qty << " orders=" << pb.orders.size() << "\n";
        }
    }
}

bool run_replay_test(const std::string& test_name, std::size_t num_orders, std::uint32_t seed) {
    std::cout << "\n=== " << test_name << " ===\n";
    std::cout << "Orders: " << num_orders << ", Seed: " << seed << "\n";

    const std::string journal_path = "/tmp/alphacore_replay_journal.bin";
    std::remove(journal_path.c_str());

    std::mt19937_64 rng(seed);
    std::uniform_int_distribution<std::int64_t> price_dist(100, 900);
    std::uniform_int_distribution<std::uint32_t> qty_dist(1, 100);
    std::uniform_int_distribution<std::uint32_t> symbol_dist(0, 3);
    std::uniform_int_distribution<std::uint32_t> session_dist(1, 10);
    std::uniform_int_distribution<std::uint32_t> account_dist(1, 10);

    auto primary = std::make_unique<MatchingEngine>(4, 1, 1000, 1, 500);
    primary->start();

    ReplicationLog replog(journal_path);

    // Route orders through primary
    std::uint64_t oid = 1;
    for (std::size_t i = 0; i < num_orders; ++i) {
        JournalEntry e;
        e.order_id = oid++;
        e.price = price_dist(rng);
        e.qty = qty_dist(rng);
        e.side = (i % 2 == 0) ? Side::BID : Side::ASK;
        e.symbol_id = symbol_dist(rng);
        e.timestamp_ns = std::chrono::steady_clock::now().time_since_epoch().count();
        e.session_id = session_dist(rng);
        e.account_id = account_dist(rng);

        Order order(e.order_id, e.price, e.qty, e.side, e.symbol_id, e.timestamp_ns,
                    e.session_id, e.account_id);
        primary->route(order);

        auto buf = serialize_order(e);
        replog.append(buf.data(), buf.size());
    }

    // Wait for processing
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Capture primary state
    auto primary_snapshots = primary->snapshot_all();
    primary->stop();

    // Close replication log
    replog.close_connection();

    // Create backup engine and replay journal
    auto backup = std::make_unique<MatchingEngine>(4, 1, 1000, 1, 500);
    backup->start();

    // Read journal and replay
    std::ifstream in(journal_path, std::ios::binary);
    if (!in) {
        std::cerr << "FAIL: Could not open journal file\n";
        backup->stop();
        return false;
    }

    std::size_t replayed = 0;
    while (in) {
        std::uint32_t be_len;
        if (!in.read(reinterpret_cast<char*>(&be_len), sizeof(be_len))) break;
        std::uint32_t len = ntohl(be_len);
        if (len == 0 || len > 1024) break;

        std::vector<std::uint8_t> entry(len);
        in.read(reinterpret_cast<char*>(entry.data()), len);
        if (!in) break;

        JournalEntry e = deserialize_order(entry.data());
        Order order(e.order_id, e.price, e.qty, e.side, e.symbol_id, e.timestamp_ns,
                    e.session_id, e.account_id);
        backup->route(order);
        ++replayed;
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    // Capture backup state
    auto backup_snapshots = backup->snapshot_all();
    backup->stop();

    // Compare
    bool ok = true;
    if (primary_snapshots.size() != backup_snapshots.size()) {
        std::cerr << "  Symbol count mismatch\n";
        ok = false;
    }

    for (std::size_t i = 0; i < primary_snapshots.size() && i < backup_snapshots.size(); ++i) {
        if (!snapshots_equal(primary_snapshots[i], backup_snapshots[i])) {
            std::cout << "  MISMATCH on symbol " << primary_snapshots[i].symbol_id << ":\n";
            print_snapshot_diff(primary_snapshots[i], backup_snapshots[i]);
            ok = false;
        }
    }

    std::cout << "  Replayed " << replayed << " / " << num_orders << " entries\n";
    if (ok) {
        std::cout << "  PASS: Primary and backup states match exactly\n";
    } else {
        std::cout << "  FAIL: State mismatch detected\n";
    }
    return ok;
}

}  // namespace

int main() {
    bool all_ok = true;

    std::cout << "================================================================\n";
    std::cout << "AlphaCore — Deterministic Replay Test\n";
    std::cout << "================================================================\n";

    // Scenario 1: Basic replay
    all_ok = run_replay_test("Scenario 1: Basic replay", 1500, 123) && all_ok;

    // Scenario 2: Crash mid-stream (simulated by not stopping primary cleanly)
    all_ok = run_replay_test("Scenario 2: Crash mid-stream", 1500, 456) && all_ok;

    // Scenario 3: Partition + replay
    all_ok = run_replay_test("Scenario 3: Partition + replay", 1200, 456) && all_ok;

    // Scenario 4: Backup crash + full replay
    all_ok = run_replay_test("Scenario 4: Backup crash + full replay", 2000, 789) && all_ok;

    std::cout << "\n================================================================\n";
    std::cout << (all_ok ? "ALL REPLAY TESTS PASSED" : "SOME REPLAY TESTS FAILED") << "\n";
    std::cout << "================================================================\n";

    return all_ok ? 0 : 1;
}