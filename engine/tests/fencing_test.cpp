// Epoch-fencing tests for the protocol in specs/tla_engine_models/PrimaryBackup.tla.
// Partitions are modelled by a UDP relay between the heartbeat endpoints that
// can drop everything (cut) and later forward again (heal).

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <string>
#include <thread>
#include <vector>

#include "../src/heartbeat.hpp"
#include "../src/replication.hpp"

namespace {

bool wait_for(const std::function<bool()>& cond, int ms = 3000) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(ms);
    while (std::chrono::steady_clock::now() < deadline) {
        if (cond()) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    return cond();
}

bool check(const char* name, bool ok) {
    std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", name);
    return ok;
}

// Forwards datagrams from the primary side to backup_port, and replies from
// backup_port back to the last primary-side sender. cut=true drops both ways.
class UdpRelay {
public:
    explicit UdpRelay(std::uint16_t backup_port) : backup_port_(backup_port) {
        fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        ::bind(fd_, reinterpret_cast<sockaddr*>(&a), sizeof(a));
        socklen_t len = sizeof(a);
        ::getsockname(fd_, reinterpret_cast<sockaddr*>(&a), &len);
        port_ = ntohs(a.sin_port);
        timeval tv{0, 20 * 1000};
        ::setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        thread_ = std::thread([this] { run(); });
    }
    ~UdpRelay() {
        running_ = false;
        thread_.join();
        ::close(fd_);
    }
    std::uint16_t port() const { return port_; }
    std::atomic<bool> cut{false};

private:
    void run() {
        sockaddr_in primary{};
        bool have_primary = false;
        while (running_) {
            std::uint8_t buf[64];
            sockaddr_in src{};
            socklen_t slen = sizeof(src);
            const ssize_t n = ::recvfrom(fd_, buf, sizeof(buf), 0, reinterpret_cast<sockaddr*>(&src), &slen);
            if (n <= 0 || cut) continue;
            if (ntohs(src.sin_port) == backup_port_) {
                if (have_primary)
                    ::sendto(fd_, buf, n, 0, reinterpret_cast<sockaddr*>(&primary), sizeof(primary));
            } else {
                primary = src;
                have_primary = true;
                sockaddr_in dst{};
                dst.sin_family = AF_INET;
                dst.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                dst.sin_port = htons(backup_port_);
                ::sendto(fd_, buf, n, 0, reinterpret_cast<sockaddr*>(&dst), sizeof(dst));
            }
        }
    }

    std::uint16_t backup_port_;
    std::uint16_t port_ = 0;
    int fd_ = -1;
    std::atomic<bool> running_{true};
    std::thread thread_;
};

bool connect_retry(ReplicationLog& log, std::uint16_t port) {
    return wait_for([&] { return log.connect_to_backup("127.0.0.1", port); });
}

bool append_n(ReplicationLog& log, int n) {
    bool all = true;
    for (int i = 0; i < n; ++i) {
        std::uint8_t payload[16];
        std::memset(payload, i, sizeof(payload));
        all = log.append(payload, sizeof(payload)) && all;
    }
    return all;
}

// 1. After the backup promotes, entries from the old primary's epoch are rejected.
bool stale_entry_rejected_after_promotion() {
    std::puts("Test 1: stale entry rejected after promotion");
    LeaderLease a(0), b(1);
    a.promote();
    std::atomic<int> applied{0};
    BackupReceiver rx(b);
    rx.set_apply_handler([&](const std::vector<std::uint8_t>&) { applied.fetch_add(1); });
    rx.listen(19811);
    wait_for([&] { return rx.is_listening(); });
    ReplicationLog log("/tmp/alphacore_fencing_t1.bin", a);
    bool ok = check("primary connects", connect_retry(log, 19811));
    ok &= check("5 entries appended at epoch 2", append_n(log, 5));
    ok &= check("5 entries applied", wait_for([&] { return applied.load() == 5; }));

    UdpRelay relay(19821);
    HeartbeatMonitor hb_a(a), hb_b(b);
    std::atomic<bool> b_promoted{false};
    hb_b.set_promote_callback([&] { b_promoted = true; });
    hb_b.start_backup(19821);
    hb_a.start_primary("127.0.0.1", relay.port());
    ok &= check("backup saw epoch 2", wait_for([&] { return b.max_seen() == 2; }));
    relay.cut = true;  // heartbeat partition; the TCP log link stays up
    ok &= check("backup promoted to owned epoch 3", wait_for([&] { return b_promoted.load(); }) && b.epoch() == 3);
    ok &= check("old primary still believes it is current (no quorum)", a.is_current());
    ok &= check("old primary appends 5 more at epoch 2", append_n(log, 5));
    ok &= check("all 5 stale entries rejected", wait_for([&] { return rx.rejected_stale() == 5; }));
    ok &= check("none applied", applied.load() == 5);
    hb_a.stop();
    hb_b.stop();
    log.close_connection();
    rx.stop();
    std::remove("/tmp/alphacore_fencing_t1.bin");
    return ok;
}

// 2. Both nodes are primary in different epochs during a partition; on heal the
//    old primary steps itself down and its appends are refused.
bool old_primary_steps_down_on_heal() {
    std::puts("Test 2: old primary steps down on heal");
    LeaderLease a(0), b(1);
    a.promote();
    UdpRelay relay(19822);
    HeartbeatMonitor hb_a(a), hb_b(b);
    hb_b.set_promote_callback([] {});
    hb_b.start_backup(19822);
    hb_a.start_primary("127.0.0.1", relay.port());
    bool ok = check("backup saw epoch 2", wait_for([&] { return b.max_seen() == 2; }));
    relay.cut = true;
    ok &= check("backup promoted during partition", wait_for([&] { return hb_b.promoted(); }));
    ok &= check("dual primaries in different epochs (2 vs 3)",
                a.is_primary() && b.is_primary() && a.epoch() == 2 && b.epoch() == 3);
    relay.cut = false;
    ok &= check("old primary stepped down after heal", wait_for([&] { return hb_a.stepped_down(); }));
    ok &= check("old primary learned epoch 3, new primary unaffected",
                !a.is_primary() && a.max_seen() == 3 && b.is_primary() && !hb_b.stepped_down());
    ReplicationLog log("/tmp/alphacore_fencing_t2.bin", a);
    std::uint8_t payload[8] = {};
    ok &= check("append refused once fenced", !log.append(payload, sizeof(payload)));
    hb_a.stop();
    hb_b.stop();
    std::remove("/tmp/alphacore_fencing_t2.bin");
    return ok;
}

// 3. Equal epochs: owned epochs make them impossible between distinct nodes, and
//    should_step_down uses >= so an equal epoch still fences.
bool equal_epoch_tie() {
    std::puts("Test 3: equal-epoch tie");
    bool ok = true;
    bool disjoint = true;
    for (std::uint64_t m = 0; m < 64; ++m) {
        LeaderLease x(0), y(1);
        x.accept(m);
        y.accept(m);
        const std::uint64_t ex = x.promote(), ey = y.promote();
        disjoint = disjoint && ex != ey && ex > m && ey > m && ex % 2 == 0 && ey % 2 == 1 &&
                   ex <= m + 2 && ey <= m + 2;
    }
    ok &= check("promotions from the same max_seen never collide (m = 0..63)", disjoint);
    LeaderLease p(0);
    p.promote();  // epoch 2
    ok &= check("should_step_down(equal epoch) is true", p.should_step_down(2));
    ok &= check("should_step_down(older epoch) is false", !p.should_step_down(1));
    ok &= check("accepting an equal epoch fences the primary", p.accept(2) && !p.is_primary());
    LeaderLease q(1);
    q.accept(4);
    ok &= check("stale epoch rejected and does not lower max_seen", !q.accept(3) && q.max_seen() == 4);
    return ok;
}

// 4. A node restarts with a fresh (stale) in-memory lease while the peer is
//    primary at a newer epoch. It may promote during a partition, but cannot
//    collide, its writes are rejected, and it steps down on heal.
bool restart_with_stale_epoch() {
    std::puts("Test 4: restart with stale epoch");
    LeaderLease b(1);
    b.accept(2);
    b.promote();  // peer is primary at epoch 3
    LeaderLease a(0);  // restarted node: epoch 0, max_seen 0 (state lost)
    std::atomic<int> applied{0};
    BackupReceiver rx(b);
    rx.set_apply_handler([&](const std::vector<std::uint8_t>&) { applied.fetch_add(1); });
    rx.listen(19814);
    wait_for([&] { return rx.is_listening(); });

    UdpRelay relay(19824);
    HeartbeatMonitor hb_a(a), hb_b(b);
    hb_a.set_promote_callback([] {});
    relay.cut = true;  // restarted into a partition
    hb_a.start_backup(19824);
    hb_b.start_primary("127.0.0.1", relay.port());
    bool ok = check("restarted node promoted to 2", wait_for([&] { return hb_a.promoted(); }) && a.epoch() == 2);
    ok &= check("no same-epoch collision (2 vs 3)", a.epoch() != b.epoch() && b.is_primary());
    ReplicationLog log("/tmp/alphacore_fencing_t4.bin", a);
    ok &= check("restarted node connects to peer", connect_retry(log, 19814));
    ok &= check("restarted node appends at epoch 2", append_n(log, 3));
    ok &= check("peer rejects all 3", wait_for([&] { return rx.rejected_stale() == 3; }) && applied.load() == 0);
    ok &= check("peer stays primary (2 < 3)", b.is_primary() && !hb_b.stepped_down());
    relay.cut = false;
    ok &= check("restarted node steps down on heal", wait_for([&] { return hb_a.stepped_down(); }));
    ok &= check("restarted node learned epoch 3", !a.is_primary() && a.max_seen() == 3 && !hb_a.promoted());
    hb_a.stop();
    hb_b.stop();
    log.close_connection();
    rx.stop();
    std::remove("/tmp/alphacore_fencing_t4.bin");
    return ok;
}

}  // namespace

int main() {
    std::signal(SIGPIPE, SIG_IGN);
    bool ok = true;
    ok &= stale_entry_rejected_after_promotion();
    ok &= old_primary_steps_down_on_heal();
    ok &= equal_epoch_tie();
    ok &= restart_with_stale_epoch();
    std::puts(ok ? "ALL FENCING TESTS PASSED" : "SOME FENCING TESTS FAILED");
    return ok ? 0 : 1;
}
