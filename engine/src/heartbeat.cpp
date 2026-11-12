#include "heartbeat.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstring>

namespace {

std::uint32_t now_ns_low32() {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
    return static_cast<std::uint32_t>(ns & 0xffffffffu);
}

}  // namespace

LeaderLease::LeaderLease() : epoch_(1) {}

std::uint64_t LeaderLease::epoch() const {
    return epoch_.load(std::memory_order_acquire);
}

std::uint64_t LeaderLease::promote() {
    return epoch_.fetch_add(1, std::memory_order_acq_rel) + 1;
}

bool LeaderLease::should_step_down(std::uint64_t backup_epoch) const {
    return backup_epoch > epoch();
}

HeartbeatMonitor::HeartbeatMonitor(LeaderLease& lease)
    : lease_(lease),
      running_primary_(false),
      running_backup_(false),
      promoted_(false),
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

    timeval tv{};
    tv.tv_sec = 0;
    tv.tv_usec = 100 * 1000;
    ::setsockopt(backup_fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    listen_port_ = listen_port;
    promoted_.store(false, std::memory_order_release);
    running_backup_.store(true, std::memory_order_release);
    backup_thread_ = std::thread(&HeartbeatMonitor::backup_loop, this);
    return true;
}

void HeartbeatMonitor::stop() {
    running_primary_.store(false, std::memory_order_release);
    running_backup_.store(false, std::memory_order_release);

    if (primary_fd_ >= 0) {
        ::close(primary_fd_);
        primary_fd_ = -1;
    }
    if (backup_fd_ >= 0) {
        ::close(backup_fd_);
        backup_fd_ = -1;
    }

    if (primary_thread_.joinable()) {
        primary_thread_.join();
    }
    if (backup_thread_.joinable()) {
        backup_thread_.join();
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

    std::uint32_t pkt[2];
    pkt[0] = htonl(static_cast<std::uint32_t>(lease_.epoch()));
    pkt[1] = htonl(now_ns_low32());
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

void HeartbeatMonitor::primary_loop() {
    while (running_primary_.load(std::memory_order_acquire)) {
        (void)send_heartbeat();
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
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
    std::uint64_t last_primary_epoch = 0;
    int misses = 0;

    while (running_backup_.load(std::memory_order_acquire)) {
        std::uint32_t pkt[2] = {0, 0};
        sockaddr_in src{};
        socklen_t slen = sizeof(src);

        const ssize_t n = ::recvfrom(backup_fd_, pkt, sizeof(pkt), 0,
                                     reinterpret_cast<sockaddr*>(&src), &slen);

        if (n == static_cast<ssize_t>(sizeof(pkt))) {
            last_primary_epoch = ntohl(pkt[0]);
            misses = 0;
            continue;
        }

        ++misses;
        if (misses >= 3 && !promoted_.load(std::memory_order_acquire)) {
            if (lease_.epoch() >= last_primary_epoch) {
                (void)lease_.promote();
                promoted_.store(true, std::memory_order_release);
                if (promote_cb_) {
                    promote_cb_();
                } else {
                    default_promote();
                }
            }
        }
    }
}
