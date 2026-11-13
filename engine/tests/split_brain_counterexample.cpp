#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <thread>
#include "../src/heartbeat.hpp"

int main() {
    // Packet sink models a partition: the live primary cannot reach the backup.
    int sink = ::socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = 0;
    if (sink < 0 || ::bind(sink, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) return 2;
    socklen_t size = sizeof(addr);
    if (::getsockname(sink, reinterpret_cast<sockaddr*>(&addr), &size) != 0) return 2;
    LeaderLease primary_lease, backup_lease;
    primary_lease.promote(); // A prior failover left the live primary at epoch 2.
    HeartbeatMonitor primary(primary_lease), backup(backup_lease);
    std::atomic<bool> backup_serving{false};
    backup.set_promote_callback([&] { backup_serving.store(true); });
    if (!primary.start_primary("127.0.0.1", ntohs(addr.sin_port)) || !backup.start_backup(0)) return 2;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!backup_serving.load() && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    const bool collision = backup_serving.load() && primary_lease.epoch() == backup_lease.epoch();
    std::printf("live primary epoch=%llu; promoted backup epoch=%llu; same-epoch collision=%s\n",
                static_cast<unsigned long long>(primary_lease.epoch()),
                static_cast<unsigned long long>(backup_lease.epoch()), collision ? "YES" : "no");
    primary.stop(); backup.stop(); ::close(sink);
    if (!backup_serving.load()) { std::puts("ERROR: timeout did not reproduce promotion"); return 2; }
    if (collision) { std::puts("FAIL: SinglePrimaryPerEpoch"); return 1; }
    return 0;
}
