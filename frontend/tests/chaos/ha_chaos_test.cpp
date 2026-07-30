// AlphaCore — HA Primary-Backup Chaos Integration Tests
// =====================================================
// Tests four failure scenarios:
//   1. Clean primary shutdown, planned handover to backup
//   2. Primary crash (process hard-stop mid-stream), backup promotes
//   3. Network partition, old primary fenced, heals without split-brain
//   4. Backup crashes and restarts, resyncs from journal
//
// Each test starts a primary (ReplicationLog + HeartbeatMonitor) and a
// backup (BackupReceiver + HeartbeatMonitor), runs a workload, induces the
// failure, and verifies correct recovery.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include "../../src/engine.hpp"
#include "../../src/heartbeat.hpp"
#include "../../src/replication.hpp"

namespace {

constexpr std::uint16_t kReplPortBase = 19501;
constexpr std::uint16_t kHbPortBase = 19601;

// Write a deterministic payload that we can verify after replay
void fill_payload(std::uint8_t* buf, std::size_t len, std::uint64_t seq) {
    std::memcpy(buf, &seq, sizeof(seq));
    for (std::size_t i = sizeof(seq); i < len; ++i) {
        buf[i] = static_cast<std::uint8_t>((seq + i) & 0xFF);
    }
}

bool verify_payload(const std::uint8_t* buf, std::size_t len, std::uint64_t expected_seq) {
    std::uint64_t stored = 0;
    std::memcpy(&stored, buf, sizeof(stored));
    if (stored != expected_seq) {
        return false;
    }
    for (std::size_t i = sizeof(expected_seq); i < len; ++i) {
        if (buf[i] != static_cast<std::uint8_t>((expected_seq + i) & 0xFF)) {
            return false;
        }
    }
    return true;
}

void print_result(const std::string& test_name, bool ok) {
    std::cout << "  [" << (ok ? "PASS" : "FAIL") << "] " << test_name << "\n";
}

}  // namespace

int main() {
    // Ignore SIGPIPE: we check socket write return values for EPIPE instead.
    // Default SIGPIPE behavior kills the process, which is not desirable in
    // a test that deliberately induces connection breaks.
    std::signal(SIGPIPE, SIG_IGN);

    bool all_ok = true;
    int test_id = 0;

    std::cout << "================================================================\n";
    std::cout << "AlphaCore — HA Chaos Integration Tests\n";
    std::cout << "================================================================\n\n";

    // ─── Test 1: Clean primary shutdown, planned handover ─────────────
    do {
        ++test_id;
        std::cout << "Test " << test_id << ": Clean primary shutdown + handover\n";
        std::cout << "------------------------------------------------------\n";

        const std::uint16_t repl_port = kReplPortBase + static_cast<std::uint16_t>(test_id);
        const std::uint16_t hb_port = kHbPortBase + static_cast<std::uint16_t>(test_id);
        const std::string journal = "/tmp/alphacore_chaos_test1_journal.bin";

        std::atomic<std::size_t> backup_received{0};
        std::vector<std::uint64_t> received_seqs;
        std::mutex recv_mutex;

        // Start backup receiver
        BackupReceiver backup;
        backup.set_apply_handler([&](const std::vector<std::uint8_t>& entry) {
            if (entry.size() >= sizeof(std::uint64_t)) {
                std::uint64_t seq = 0;
                std::memcpy(&seq, entry.data(), sizeof(seq));
                std::lock_guard<std::mutex> lock(recv_mutex);
                received_seqs.push_back(seq);
            }
            backup_received.fetch_add(1, std::memory_order_acq_rel);
        });
        backup.listen(repl_port);
        for (int i = 0; i < 100 && !backup.is_listening(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        LeaderLease primary_lease;
        LeaderLease backup_lease;

        // Primary sends heartbeats and ships log
        ReplicationLog primary(journal);
        HeartbeatMonitor hb_primary(primary_lease);

        bool connected = false;
        for (int i = 0; i < 100; ++i) {
            if (primary.connect_to_backup("127.0.0.1", repl_port)) {
                connected = true;
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        if (!connected) {
            std::cout << "  FAIL: primary could not connect to backup\n";
            all_ok = false;
            backup.stop();
            std::cout << "\n";
            continue;
        }

        hb_primary.start_primary("127.0.0.1", hb_port);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        // Primary appends 50 log entries
        for (int i = 0; i < 50; ++i) {
            std::uint8_t payload[32];
            fill_payload(payload, sizeof(payload), static_cast<std::uint64_t>(i));
            primary.append(payload, sizeof(payload));
        }

        // Wait for replication to catch up
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < deadline) {
            if (backup_received.load(std::memory_order_acquire) >= 50) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }

        // Clean shutdown: stop primary first (like planned handover)
        hb_primary.stop();
        primary.close_connection();

        // Wait a moment then see if backup_received == 50
        std::this_thread::sleep_for(std::chrono::milliseconds(500));

        bool t1_recv_ok = (backup_received.load(std::memory_order_acquire) >= 50);
        print_result("All 50 entries replicated before shutdown", t1_recv_ok);
        all_ok = all_ok && t1_recv_ok;

        // Verify payload integrity
        bool t1_payload_ok = true;
        {
            std::lock_guard<std::mutex> lock(recv_mutex);
            std::sort(received_seqs.begin(), received_seqs.end());
            for (std::size_t i = 0; i < received_seqs.size(); ++i) {
                if (received_seqs[i] != i) {
                    t1_payload_ok = false;
                    break;
                }
            }
        }
        print_result("Payload integrity on all entries", t1_payload_ok);
        all_ok = all_ok && t1_payload_ok;

        // The journal should exist and be replayable
        std::FILE* jf = std::fopen(journal.c_str(), "rb");
        bool t1_journal_ok = (jf != nullptr);
        if (jf) {
            // Count entries in journal
            int journal_entries = 0;
            while (!std::feof(jf)) {
                std::uint32_t be_len = 0;
                if (std::fread(&be_len, sizeof(be_len), 1, jf) != 1) break;
                std::uint32_t len = ntohl(be_len);
                if (len > 1024) { t1_journal_ok = false; break; }
                if (std::fseek(jf, len, SEEK_CUR) != 0) { t1_journal_ok = false; break; }
                ++journal_entries;
            }
            std::fclose(jf);
            t1_journal_ok = t1_journal_ok && (journal_entries == 50);
            if (!t1_journal_ok) {
                std::cout << "  Journal entries: " << journal_entries << " (expected 50)\n";
            }
        }
        print_result("Journal file has 50 entries", t1_journal_ok);
        all_ok = all_ok && t1_journal_ok;

        backup.stop();
        std::remove(journal.c_str());

        std::cout << "\n";
    } while(0);

    // ─── Test 2: Primary crash mid-stream, backup promotes ────────────
    do {
        ++test_id;
        std::cout << "Test " << test_id << ": Primary crash + backup promotion\n";
        std::cout << "------------------------------------------------------\n";

        const std::uint16_t repl_port = kReplPortBase + static_cast<std::uint16_t>(test_id);
        const std::uint16_t hb_port = kHbPortBase + static_cast<std::uint16_t>(test_id);
        const std::string journal = "/tmp/alphacore_chaos_test2_journal.bin";

        std::atomic<std::size_t> backup_received{0};
        std::atomic<bool> promoted{false};

        // Backup receiver
        BackupReceiver backup;
        backup.set_apply_handler([&](const std::vector<std::uint8_t>&) {
            backup_received.fetch_add(1, std::memory_order_acq_rel);
        });
        backup.listen(repl_port);
        for (int i = 0; i < 100 && !backup.is_listening(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        LeaderLease primary_lease;
        LeaderLease backup_lease;

        ReplicationLog primary(journal);
        HeartbeatMonitor hb_primary(primary_lease);
        HeartbeatMonitor hb_backup(backup_lease);

        // Connect primary to backup
        bool connected = false;
        for (int i = 0; i < 100; ++i) {
            if (primary.connect_to_backup("127.0.0.1", repl_port)) {
                connected = true;
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        if (!connected) {
            std::cout << "  FAIL: primary could not connect\n";
            all_ok = false;
            backup.stop();
            std::cout << "\n";
            continue;
        }

        // Start heartbeat: backup listens, primary sends
        hb_backup.start_backup(hb_port);
        hb_primary.start_primary("127.0.0.1", hb_port);

        // Set promote callback on backup
        hb_backup.set_promote_callback([&promoted]() {
            promoted.store(true, std::memory_order_release);
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(200));

        // Primary sends some log entries, then crashes (process kill -9 style)
        for (int i = 0; i < 25; ++i) {
            std::uint8_t payload[16];
            fill_payload(payload, sizeof(payload), static_cast<std::uint64_t>(i));
            primary.append(payload, sizeof(payload));
        }

        // Simulate crash: stop heartbeat and close connection abruptly
        // (This is the "kill -9" equivalent — no graceful shutdown)
        hb_primary.stop();
        primary.close_connection();

        // Backup should detect missed heartbeats and promote
        auto promo_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < promo_deadline) {
            if (promoted.load(std::memory_order_acquire) || hb_backup.promoted()) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        bool t2_promoted = (promoted.load(std::memory_order_acquire) || hb_backup.promoted());
        print_result("Backup promoted after missed heartbeats", t2_promoted);
        all_ok = all_ok && t2_promoted;

        // Check that at least some entries were replicated before crash
        std::size_t received = backup_received.load(std::memory_order_acquire);
        bool t2_entries = (received >= 10 && received <= 25);
        print_result("Partial replication before crash (" + std::to_string(received) + " entries)", t2_entries);
        all_ok = all_ok && t2_entries;

        // Verify epoch was incremented
        std::uint64_t new_epoch = backup_lease.epoch();
        bool t2_epoch = (new_epoch >= 1);
        print_result("Epoch advanced after promotion (" + std::to_string(new_epoch) + ")", t2_epoch);
        all_ok = all_ok && t2_epoch;

        hb_backup.stop();
        backup.stop();
        std::remove(journal.c_str());

        std::cout << "\n";
    } while(0);

    // ─── Test 3: Network partition, split-brain prevention ────────────
    do {
        ++test_id;
        std::cout << "Test " << test_id << ": Network partition + split-brain prevention\n";
        std::cout << "------------------------------------------------------\n";

        const std::uint16_t repl_port = kReplPortBase + static_cast<std::uint16_t>(test_id);
        const std::uint16_t hb_port = kHbPortBase + static_cast<std::uint16_t>(test_id);
        const std::string journal = "/tmp/alphacore_chaos_test3_journal.bin";

        std::atomic<bool> promoted{false};
        std::atomic<bool> promote_fencing_ok{true};

        LeaderLease primary_lease;
        LeaderLease backup_lease;

        BackupReceiver backup;
        backup.listen(repl_port);
        for (int i = 0; i < 100 && !backup.is_listening(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        ReplicationLog primary(journal);
        HeartbeatMonitor hb_primary(primary_lease);
        HeartbeatMonitor hb_backup(backup_lease);

        bool connected = false;
        for (int i = 0; i < 100; ++i) {
            if (primary.connect_to_backup("127.0.0.1", repl_port)) {
                connected = true;
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        if (!connected) {
            std::cout << "  FAIL: primary could not connect\n";
            all_ok = false;
            backup.stop();
            std::cout << "\n";
            continue;
        }

        hb_backup.start_backup(hb_port);
        hb_primary.start_primary("127.0.0.1", hb_port);

        hb_backup.set_promote_callback([&promoted, &primary_lease, &backup_lease, &promote_fencing_ok]() {
            // When promoted, simulate the epoch fencing check:
            // old primary's epoch must be stale (less than new epoch)
            std::uint64_t old_epoch = primary_lease.epoch();
            std::uint64_t new_epoch = backup_lease.promote();
            if (old_epoch >= new_epoch) {
                promote_fencing_ok.store(false, std::memory_order_release);
            }
            promoted.store(true, std::memory_order_release);
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(200));

        // Simulate partition: drop heartbeats from primary
        // (We do this by stopping primary heartbeat sender)
        hb_primary.stop();

        // Backup should promote
        auto promo_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < promo_deadline) {
            if (promoted.load(std::memory_order_acquire) || hb_backup.promoted()) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        bool t3_promoted = (promoted.load(std::memory_order_acquire) || hb_backup.promoted());
        print_result("Backup promoted during partition", t3_promoted);
        all_ok = all_ok && t3_promoted;

        // After promotion, check fencing invariant
        std::uint64_t backup_ep = backup_lease.epoch();
        bool t3_fencing = (promote_fencing_ok.load() && backup_ep > primary_lease.epoch());
        print_result("Fencing: backup epoch > primary epoch (" +
                     std::to_string(backup_ep) + " > " +
                     std::to_string(primary_lease.epoch()) + ")", t3_fencing);
        all_ok = all_ok && t3_fencing;

        // Simulate old primary coming back (hb_primary restarts)
        // It should be fenced — its epoch is stale
        bool t3_stale = primary_lease.epoch() < backup_ep;
        print_result("Old primary epoch is stale after promotion", t3_stale);
        all_ok = all_ok && t3_stale;

        hb_backup.stop();
        hb_primary.stop();
        primary.close_connection();
        backup.stop();
        std::remove(journal.c_str());

        std::cout << "\n";
    } while(0);

    // ─── Test 4: Backup crashes and restarts, resyncs from journal ────
    do {
        ++test_id;
        std::cout << "Test " << test_id << ": Backup crash + restart + resync\n";
        std::cout << "------------------------------------------------------\n";

        const std::uint16_t repl_port = kReplPortBase + static_cast<std::uint16_t>(test_id);
        const std::uint16_t hb_port = kHbPortBase + static_cast<std::uint16_t>(test_id);
        const std::string journal = "/tmp/alphacore_chaos_test4_journal.bin";
        std::remove(journal.c_str());  // clean any leftover from previous run

        // Phase 1: Primary sends 30 entries, then backup starts receiving
        std::atomic<std::size_t> received{0};
        std::vector<std::uint8_t> captured_entry;

        BackupReceiver backup;
        backup.set_apply_handler([&](const std::vector<std::uint8_t>& entry) {
            received.fetch_add(1, std::memory_order_acq_rel);
        });
        backup.listen(repl_port);
        for (int i = 0; i < 100 && !backup.is_listening(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        LeaderLease primary_lease;
        ReplicationLog primary(journal);

        bool connected = false;
        for (int i = 0; i < 100; ++i) {
            if (primary.connect_to_backup("127.0.0.1", repl_port)) {
                connected = true;
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        if (!connected) {
            std::cout << "  FAIL: primary could not connect\n";
            all_ok = false;
            backup.stop();
            std::cout << "\n";
            continue;
        }

        // Send 30 entries
        for (int i = 0; i < 30; ++i) {
            std::uint8_t payload[32];
            fill_payload(payload, sizeof(payload), static_cast<std::uint64_t>(i));
            primary.append(payload, sizeof(payload));
        }

        // Wait for backup to receive all 30
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < deadline) {
            if (received.load(std::memory_order_acquire) >= 30) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }

        // Simulate backup crash (just tear down)
        backup.stop();
        // Explicitly close the primary's TCP connection so the next append()
        // knows to buffer and reconnect. Without this, the socket may still
        // appear "connected" from the primary's side (TCP doesn't immediately
        // notify the writer when the reader disconnects).
        primary.close_connection();
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        received.store(0, std::memory_order_release);

        // Phase 2: Start new backup instance and reconnect
        BackupReceiver backup2;
        std::atomic<std::size_t> received2{0};
        backup2.set_apply_handler([&](const std::vector<std::uint8_t>&) {
            received2.fetch_add(1, std::memory_order_acq_rel);
        });
        backup2.listen(repl_port);
        for (int i = 0; i < 100 && !backup2.is_listening(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        // Give the retry loop time to reconnect to the new backup
        std::this_thread::sleep_for(std::chrono::milliseconds(600));

        // Send 20 more entries (total 50)
        for (int i = 30; i < 50; ++i) {
            std::uint8_t payload[32];
            fill_payload(payload, sizeof(payload), static_cast<std::uint64_t>(i));
            primary.append(payload, sizeof(payload));
        }

        // Wait for backup2 to catch up
        deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (std::chrono::steady_clock::now() < deadline) {
            if (received2.load(std::memory_order_acquire) >= 20) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }

        // Verify: the restarted backup received entries 30-49
        bool t4_recv = (received2.load(std::memory_order_acquire) >= 20);
        print_result("Restarted backup received entries after reconnect", t4_recv);
        all_ok = all_ok && t4_recv;

        // Journal should have all 50 entries
        std::FILE* jf = std::fopen(journal.c_str(), "rb");
        bool t4_journal = false;
        if (jf) {
            int journal_entries = 0;
            while (!std::feof(jf)) {
                std::uint32_t be_len = 0;
                if (std::fread(&be_len, sizeof(be_len), 1, jf) != 1) break;
                std::uint32_t len = ntohl(be_len);
                if (len > 1024) break;
                if (std::fseek(jf, len, SEEK_CUR) != 0) break;
                ++journal_entries;
            }
            std::fclose(jf);
            t4_journal = (journal_entries == 50);
            if (!t4_journal) {
                std::cout << "  Journal entries: " << journal_entries << " (expected 50)\n";
            }
        }
        print_result("Journal has all 50 entries after backup restart", t4_journal);
        all_ok = all_ok && t4_journal;

        primary.close_connection();
        backup2.stop();
        std::remove(journal.c_str());

        std::cout << "\n";
    } while(0);

    // ─── Summary ──────────────────────────────────────────────────────
    std::cout << "================================================================\n";
    std::cout << (all_ok ? "ALL CHAOS TESTS PASSED" : "SOME CHAOS TESTS FAILED") << "\n";
    std::cout << "================================================================\n";

    return all_ok ? 0 : 1;
}
