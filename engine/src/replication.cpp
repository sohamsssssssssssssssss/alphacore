#include "replication.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <poll.h>
#include <sys/time.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <fstream>

namespace {

bool send_all(int fd, const std::uint8_t* data, std::size_t len) {
    std::size_t off = 0;
    while (off < len) {
        const ssize_t n = ::send(fd, data + off, len - off, 0);
        if (n <= 0) {
            return false;
        }
        off += static_cast<std::size_t>(n);
    }
    return true;
}

constexpr std::size_t kFrameHeaderBytes = 4 + 2 + 8;

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

}  // namespace

ReplicationLog::ReplicationLog(const std::string& journal_path, LeaderLease& lease)
    : journal_path_(journal_path),
      lease_(lease),
      backup_host_("127.0.0.1"),
      backup_port_(0),
      sock_fd_(-1),
      running_(true),
      retry_thread_(),
      mu_(),
      buffered_() {
    retry_thread_ = std::thread(&ReplicationLog::retry_loop, this);
}

ReplicationLog::~ReplicationLog() {
    running_.store(false, std::memory_order_release);
    if (retry_thread_.joinable()) {
        retry_thread_.join();
    }
    close_connection();
}

bool ReplicationLog::connect_to_backup(const std::string& host, std::uint16_t port) {
    std::lock_guard<std::mutex> lock(mu_);
    backup_host_ = host;
    backup_port_ = port;
    if (sock_fd_ >= 0) {
        ::close(sock_fd_);
        sock_fd_ = -1;
    }
    return connect_locked();
}

void ReplicationLog::close_connection() {
    std::lock_guard<std::mutex> lock(mu_);
    if (sock_fd_ >= 0) {
        ::close(sock_fd_);
        sock_fd_ = -1;
    }
}

bool ReplicationLog::connect_locked() {
    if (backup_port_ == 0) {
        return false;
    }

    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return false;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(backup_port_);
    if (::inet_pton(AF_INET, backup_host_.c_str(), &addr.sin_addr) != 1) {
        ::close(fd);
        return false;
    }

    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(fd);
        return false;
    }

    sock_fd_ = fd;
    flush_buffered_locked();
    return true;
}

bool ReplicationLog::send_frame_locked(const std::vector<std::uint8_t>& frame) {
    if (sock_fd_ < 0) {
        return false;
    }
    if (!send_all(sock_fd_, frame.data(), frame.size())) {
        ::close(sock_fd_);
        sock_fd_ = -1;
        return false;
    }
    return true;
}

void ReplicationLog::flush_buffered_locked() {
    while (!buffered_.empty() && sock_fd_ >= 0) {
        if (!send_frame_locked(buffered_.front())) {
            return;
        }
        buffered_.pop_front();
    }
}

bool ReplicationLog::append(const std::uint8_t* entry, std::size_t len) {
    if (entry == nullptr || len == 0 || len > kMaxEntryBytes) {
        return false;
    }
    // Buffered frames keep the epoch they were appended under, so a receiver
    // that has since seen a newer epoch rejects them after a heal.
    const std::uint64_t epoch = lease_.epoch();
    if (!lease_.is_current()) {
        return false;
    }
    std::vector<std::uint8_t> frame(kFrameHeaderBytes + len);
    put_be(frame.data(), len, 4);
    put_be(frame.data() + 4, kReplicationFrameVersion, 2);
    put_be(frame.data() + 6, epoch, 8);
    std::memcpy(frame.data() + kFrameHeaderBytes, entry, len);

    {
        std::ofstream out(journal_path_, std::ios::binary | std::ios::app);
        if (out) {
            const std::uint32_t be_len = htonl(static_cast<std::uint32_t>(len));
            out.write(reinterpret_cast<const char*>(&be_len), sizeof(be_len));
            out.write(reinterpret_cast<const char*>(entry), static_cast<std::streamsize>(len));
            out.flush();
        }
    }

    std::lock_guard<std::mutex> lock(mu_);
    if (!send_frame_locked(frame)) {
        buffered_.push_back(std::move(frame));
    }
    return true;
}

void ReplicationLog::retry_loop() {
    while (running_.load(std::memory_order_acquire)) {
        {
            std::lock_guard<std::mutex> lock(mu_);
            if (sock_fd_ < 0) {
                (void)connect_locked();
            } else {
                flush_buffered_locked();
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
}

BackupReceiver::BackupReceiver(LeaderLease& lease)
    : lease_(lease),
      running_(false),
      listening_ready_(false),
      rejected_stale_(0),
      thread_(),
      apply_handler_(),
      apply_mu_(),
      listen_fd_(-1),
      conn_fd_(-1) {}

BackupReceiver::~BackupReceiver() {
    stop();
}

void BackupReceiver::set_apply_handler(std::function<void(const std::vector<std::uint8_t>&)> handler) {
    std::lock_guard<std::mutex> lock(apply_mu_);
    apply_handler_ = std::move(handler);
}

void BackupReceiver::listen(std::uint16_t port) {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
        return;
    }
    thread_ = std::thread(&BackupReceiver::run, this, port);
}

void BackupReceiver::stop() {
    running_.store(false, std::memory_order_release);
    listening_ready_.store(false, std::memory_order_release);

    // Only the receiver thread uses the fds; it wakes every 100 ms to see
    // running_ == false, so join first and close afterwards (no cross-thread close).
    if (thread_.joinable()) {
        thread_.join();
    }
    for (int* fd : {&conn_fd_, &listen_fd_}) {
        if (*fd >= 0) {
            ::close(*fd);
            *fd = -1;
        }
    }
}

bool BackupReceiver::is_listening() const {
    return listening_ready_.load(std::memory_order_acquire);
}

std::size_t BackupReceiver::rejected_stale() const {
    return rejected_stale_.load(std::memory_order_acquire);
}

bool BackupReceiver::recv_exact(int fd, std::uint8_t* out, std::size_t len) {
    std::size_t off = 0;
    while (off < len && running_.load(std::memory_order_acquire)) {
        const ssize_t n = ::recv(fd, out + off, len - off, 0);
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
            continue;  // receive timeout: re-check running_
        }
        if (n <= 0) {
            return false;
        }
        off += static_cast<std::size_t>(n);
    }
    return off == len;
}

void BackupReceiver::apply_entry(const std::vector<std::uint8_t>& entry) {
    std::function<void(const std::vector<std::uint8_t>&)> cb;
    {
        std::lock_guard<std::mutex> lock(apply_mu_);
        cb = apply_handler_;
    }
    if (cb) {
        cb(entry);
    }
}

void BackupReceiver::run(std::uint16_t port) {
    listen_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd_ < 0) {
        running_.store(false, std::memory_order_release);
        return;
    }

    int one = 1;
    ::setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);

    if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 ||
        ::listen(listen_fd_, 1) != 0) {
        ::close(listen_fd_);
        listen_fd_ = -1;
        running_.store(false, std::memory_order_release);
        return;
    }
    listening_ready_.store(true, std::memory_order_release);

    while (running_.load(std::memory_order_acquire)) {
        pollfd pfd{listen_fd_, POLLIN, 0};
        if (::poll(&pfd, 1, 100) <= 0) {
            continue;  // timeout: re-check running_
        }
        sockaddr_in caddr{};
        socklen_t clen = sizeof(caddr);
        conn_fd_ = ::accept(listen_fd_, reinterpret_cast<sockaddr*>(&caddr), &clen);
        if (conn_fd_ < 0) {
            continue;
        }
        timeval tv{};
        tv.tv_usec = 100 * 1000;
        ::setsockopt(conn_fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        while (running_.load(std::memory_order_acquire)) {
            std::uint8_t header[kFrameHeaderBytes];
            if (!recv_exact(conn_fd_, header, sizeof(header))) {
                break;
            }
            const auto len = static_cast<std::uint32_t>(get_be(header, 4));
            if (get_be(header + 4, 2) != kReplicationFrameVersion || len > kMaxEntryBytes) {
                break;  // unknown version or oversized frame: drop the connection
            }
            const std::uint64_t epoch = get_be(header + 6, 8);
            std::vector<std::uint8_t> entry(len);
            if (!recv_exact(conn_fd_, entry.data(), len)) {
                break;
            }
            if (!lease_.accept(epoch)) {  // rule (d): epoch < max_seen
                rejected_stale_.fetch_add(1, std::memory_order_acq_rel);
                continue;
            }
            apply_entry(entry);
        }

        ::close(conn_fd_);
        conn_fd_ = -1;
    }
}
