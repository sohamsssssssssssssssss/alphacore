#include "heartbeat.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstring>
#include <stdexcept>

namespace {

constexpr std::uint32_t kHeartbeatVersion = 1;
constexpr std::size_t kHeartbeatBytes = 16;

void put_be(std::uint8_t* out, std::uint64_t v, int bytes) {
    for (int i = bytes - 1; i >= 0; --i) {
        out[i] = static_cast<std::uint8_t>(v & 0xffu);
        v >>= 8;
    }
}

std::uint64_t get_be(const std::uint8_t* in, int bytes) {
    std::uint64_t v = 0;
    for (int i = 0; i < bytes; ++i) {
        v = (v << 8) | in[i];
    }
    return v;
}

void encode_heartbeat(std::uint8_t* pkt, std::uint32_t node_id, std::uint64_t epoch) {
    put_be(pkt, kHeartbeatVersion, 4);
    put_be(pkt + 4, node_id, 4);
    put_be(pkt + 8, epoch, 8);
}

// Returns true for a valid v1 heartbeat from the other node.
bool decode_heartbeat(const std::uint8_t* pkt, ssize_t n, std::uint32_t self, std::uint64_t& epoch) {
    if (n != static_cast<ssize_t>(kHeartbeatBytes) || get_be(pkt, 4) != kHeartbeatVersion ||
        get_be(pkt + 4, 4) == self) {
        return false;
    }
    epoch = get_be(pkt + 8, 8);
    return true;
}

void set_recv_timeout(int fd, int ms) {
    timeval tv{};
    tv.tv_sec = 0;
    tv.tv_usec = ms * 1000;
    ::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
}

}  // namespace

LeaderLease::LeaderLease(std::uint32_t node_id)
    : node_id_(node_id), epoch_(0), max_seen_(0), primary_(false) {
    if (node_id > 1) {
        throw std::invalid_argument("LeaderLease supports two nodes: node_id must be 0 or 1");
    }
}

std::uint32_t LeaderLease::node_id() const {
    return node_id_;
}

std::uint64_t LeaderLease::epoch() const {
    std::lock_guard<std::mutex> lock(mu_);
    return epoch_;
}

std::uint64_t LeaderLease::max_seen() const {
    std::lock_guard<std::mutex> lock(mu_);
    return max_seen_;
}

bool LeaderLease::is_primary() const {
    std::lock_guard<std::mutex> lock(mu_);
    return primary_;
}

bool LeaderLease::is_current() const {
    std::lock_guard<std::mutex> lock(mu_);
    return primary_ && epoch_ == max_seen_;
}

std::uint64_t LeaderLease::promote() {
    std::lock_guard<std::mutex> lock(mu_);
    std::uint64_t next = max_seen_ + 1;
    if (next % 2 != node_id_) {
        ++next;
    }
    epoch_ = next;
    max_seen_ = next;
    primary_ = true;
    return next;
}

bool LeaderLease::should_step_down_locked(std::uint64_t other_epoch) const {
    return primary_ && other_epoch >= epoch_;
}

bool LeaderLease::should_step_down(std::uint64_t other_epoch) const {
    std::lock_guard<std::mutex> lock(mu_);
    return should_step_down_locked(other_epoch);
}

bool LeaderLease::accept(std::uint64_t other_epoch) {
    std::lock_guard<std::mutex> lock(mu_);
    if (other_epoch < max_seen_) {
        return false;
    }
    max_seen_ = other_epoch;
    if (should_step_down_locked(other_epoch)) {
        primary_ = false;
    }
    return true;
}

HeartbeatMonitor::HeartbeatMonitor(LeaderLease& lease)
    : lease_(lease),
      running_primary_(false),
      running_backup_(false),
      promoted_(false),
      stepped_down_(false),
      primary_thread_(),
      backup_thread_(),
      backup_host_("127.0.0.1"),
      backup_port_(0),
      listen_port_(0),
      primary_fd_(-1),
      backup_fd_(-1),
      promoted_gateway_fd_(-1),
      promote_cb_() {}

HeartbeatMonitor::~HeartbeatMonitor() {
    stop();
}

bool HeartbeatMonitor::start_primary(const std::string& backup_host, std::uint16_t backup_port) {
    if (running_primary_.load(std::memory_order_acquire)) {
        return true;
    }

    primary_fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (primary_fd_ < 0) {
        return false;
    }
    // The receive timeout paces the loop and lets it read epoch notifications.
    set_recv_timeout(primary_fd_, 100);

    backup_host_ = backup_host;
    backup_port_ = backup_port;
    running_primary_.store(true, std::memory_order_release);
    primary_thread_ = std::thread(&HeartbeatMonitor::primary_loop, this);
    return true;
}

bool HeartbeatMonitor::start_backup(std::uint16_t listen_port) {
    if (running_backup_.load(std::memory_order_acquire)) {
        return true;
    }

    backup_fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (backup_fd_ < 0) {
        return false;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(listen_port);

    if (::bind(backup_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(backup_fd_);
        backup_fd_ = -1;
        return false;
    }

    set_recv_timeout(backup_fd_, 100);

    listen_port_ = listen_port;
    promoted_.store(false, std::memory_order_release);
    running_backup_.store(true, std::memory_order_release);
    backup_thread_ = std::thread(&HeartbeatMonitor::backup_loop, this);
    return true;
}

void HeartbeatMonitor::stop() {
    running_primary_.store(false, std::memory_order_release);
    running_backup_.store(false, std::memory_order_release);

    // Join before closing: the loops use the fds and exit within one receive timeout.
    if (primary_thread_.joinable()) {
        primary_thread_.join();
    }
    if (backup_thread_.joinable()) {
        backup_thread_.join();
    }

    if (primary_fd_ >= 0) {
        ::close(primary_fd_);
        primary_fd_ = -1;
    }
    if (backup_fd_ >= 0) {
        ::close(backup_fd_);
        backup_fd_ = -1;
    }
    if (promoted_gateway_fd_ >= 0) {
        ::close(promoted_gateway_fd_);
        promoted_gateway_fd_ = -1;
    }
}

bool HeartbeatMonitor::send_heartbeat() {
    if (primary_fd_ < 0 || backup_port_ == 0) {
        return false;
    }

    sockaddr_in dst{};
    dst.sin_family = AF_INET;
    dst.sin_port = htons(backup_port_);
    if (::inet_pton(AF_INET, backup_host_.c_str(), &dst.sin_addr) != 1) {
        return false;
    }

    std::uint8_t pkt[kHeartbeatBytes];
    encode_heartbeat(pkt, lease_.node_id(), lease_.epoch());
    const ssize_t n = ::sendto(primary_fd_, pkt, sizeof(pkt), 0,
                               reinterpret_cast<sockaddr*>(&dst), sizeof(dst));
    return n == static_cast<ssize_t>(sizeof(pkt));
}

void HeartbeatMonitor::set_promote_callback(std::function<void()> cb) {
    promote_cb_ = std::move(cb);
}

bool HeartbeatMonitor::promoted() const {
    return promoted_.load(std::memory_order_acquire);
}

bool HeartbeatMonitor::stepped_down() const {
    return stepped_down_.load(std::memory_order_acquire);
}

void HeartbeatMonitor::primary_loop() {
    while (running_primary_.load(std::memory_order_acquire)) {
        if (!lease_.is_primary()) {
            // Fenced: stop advertising the old epoch.
            stepped_down_.store(true, std::memory_order_release);
            return;
        }
        (void)send_heartbeat();

        std::uint8_t pkt[kHeartbeatBytes];
        const ssize_t n = ::recvfrom(primary_fd_, pkt, sizeof(pkt), 0, nullptr, nullptr);
        std::uint64_t other_epoch = 0;
        if (decode_heartbeat(pkt, n, lease_.node_id(), other_epoch)) {
            (void)lease_.accept(other_epoch);  // steps down per rule (e)
        }
    }
}

void HeartbeatMonitor::default_promote() {
    if (promoted_gateway_fd_ >= 0) {
        return;
    }

    promoted_gateway_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (promoted_gateway_fd_ < 0) {
        return;
    }

    int one = 1;
    ::setsockopt(promoted_gateway_fd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(9000);

    if (::bind(promoted_gateway_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 ||
        ::listen(promoted_gateway_fd_, 16) != 0) {
        ::close(promoted_gateway_fd_);
        promoted_gateway_fd_ = -1;
    }
}

void HeartbeatMonitor::backup_loop() {
    int misses = 0;
    sockaddr_in peer{};
    bool have_peer = false;

    while (running_backup_.load(std::memory_order_acquire)) {
        std::uint8_t pkt[kHeartbeatBytes];
        sockaddr_in src{};
        socklen_t slen = sizeof(src);

        const ssize_t n = ::recvfrom(backup_fd_, pkt, sizeof(pkt), 0,
                                     reinterpret_cast<sockaddr*>(&src), &slen);

        std::uint64_t other_epoch = 0;
        if (decode_heartbeat(pkt, n, lease_.node_id(), other_epoch)) {
            peer = src;  // latest address, so a restarted old primary is still reachable
            have_peer = true;
            const bool fresh = lease_.accept(other_epoch);
            if (promoted_.load(std::memory_order_acquire) && !lease_.is_primary()) {
                promoted_.store(false, std::memory_order_release);
                stepped_down_.store(true, std::memory_order_release);
            }
            if (fresh) {
                misses = 0;
            }
        } else {
            ++misses;
            if (misses >= 3 && !lease_.is_primary()) {
                (void)lease_.promote();
                promoted_.store(true, std::memory_order_release);
                if (promote_cb_) {
                    promote_cb_();
                } else {
                    default_promote();
                }
            }
        }

        // As primary, our heartbeat to the last known peer is its epoch notification.
        if (have_peer && lease_.is_primary()) {
            std::uint8_t out[kHeartbeatBytes];
            encode_heartbeat(out, lease_.node_id(), lease_.epoch());
            (void)::sendto(backup_fd_, out, sizeof(out), 0,
                           reinterpret_cast<sockaddr*>(&peer), sizeof(peer));
        }
    }
}
