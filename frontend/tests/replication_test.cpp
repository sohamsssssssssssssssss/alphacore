#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "../src/heartbeat.hpp"
#include "../src/replication.hpp"

int main() {
    bool all_ok = true;
    constexpr std::uint16_t kReplPort = 19101;
    constexpr std::uint16_t kHbPort = 19201;

    std::atomic<int> received{0};
    BackupReceiver backup;
    backup.set_apply_handler([&received](const std::vector<std::uint8_t>&) {
        received.fetch_add(1, std::memory_order_acq_rel);
    });
    backup.listen(kReplPort);
    for (int i = 0; i < 100 && !backup.is_listening(); ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    ReplicationLog primary("/tmp/alphacore_journal.bin");
    bool connected = false;
    for (int i = 0; i < 100; ++i) {
        if (primary.connect_to_backup("127.0.0.1", kReplPort)) {
            connected = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    if (!connected) {
        std::puts("FAIL: primary connect_to_backup");
        backup.stop();
        return 1;
    }

    for (int i = 0; i < 100; ++i) {
        std::uint8_t payload[16];
        std::memcpy(payload, &i, sizeof(i));
        std::memset(payload + sizeof(i), 0xA5, sizeof(payload) - sizeof(i));
        primary.append(payload, sizeof(payload));
    }

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (std::chrono::steady_clock::now() < deadline) {
        if (received.load(std::memory_order_acquire) == 100) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    if (received.load(std::memory_order_acquire) == 100) {
        std::puts("PASS: backup received all 100 log entries");
    } else {
        std::printf("FAIL: backup received %d/100 log entries\n", received.load());
        all_ok = false;
    }

    LeaderLease primary_lease;
    LeaderLease backup_lease;

    HeartbeatMonitor hb_primary(primary_lease);
    HeartbeatMonitor hb_backup(backup_lease);

    std::atomic<bool> promoted{false};
    hb_backup.set_promote_callback([&promoted]() {
        promoted.store(true, std::memory_order_release);
    });

    if (!hb_backup.start_backup(kHbPort) || !hb_primary.start_primary("127.0.0.1", kHbPort)) {
        std::puts("FAIL: heartbeat startup");
        primary.close_connection();
        backup.stop();
        return 1;
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(350));
    hb_primary.stop();

    const auto promote_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (std::chrono::steady_clock::now() < promote_deadline) {
        if (promoted.load(std::memory_order_acquire) || hb_backup.promoted()) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    if (promoted.load(std::memory_order_acquire) || hb_backup.promoted()) {
        std::puts("PASS: promote triggered after missed heartbeats");
    } else {
        std::puts("FAIL: promote not triggered after missed heartbeats");
        all_ok = false;
    }

    hb_backup.stop();
    primary.close_connection();
    backup.stop();

    return all_ok ? 0 : 1;
}
