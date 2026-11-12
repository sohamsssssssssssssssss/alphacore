#include "replication.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

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

}  // namespace

ReplicationLog::ReplicationLog(const std::string& journal_path)
    : journal_path_(journal_path),
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

bool ReplicationLog::send_frame_locked(const std::uint8_t* entry, std::size_t len) {
    if (sock_fd_ < 0) {
        return false;
    }

    const std::uint32_t be_len = htonl(static_cast<std::uint32_t>(len));
    if (!send_all(sock_fd_, reinterpret_cast<const std::uint8_t*>(&be_len), sizeof(be_len))) {
        ::close(sock_fd_);
        sock_fd_ = -1;
        return false;
    }
    if (!send_all(sock_fd_, entry, len)) {
        ::close(sock_fd_);
        sock_fd_ = -1;
        return false;
    }
    return true;
}

void ReplicationLog::flush_buffered_locked() {
    while (!buffered_.empty() && sock_fd_ >= 0) {
        const auto& e = buffered_.front();
        if (!send_frame_locked(e.data(), e.size())) {
            return;
        }
        buffered_.pop_front();
    }
}

void ReplicationLog::append(const std::uint8_t* entry, std::size_t len) {
    if (entry == nullptr || len == 0) {
        return;
    }

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
    if (!send_frame_locked(entry, len)) {
        buffered_.emplace_back(entry, entry + len);
    }
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

BackupReceiver::BackupReceiver()
    : running_(false),
      listening_ready_(false),
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

    if (conn_fd_ >= 0) {
        ::shutdown(conn_fd_, SHUT_RDWR);
        ::close(conn_fd_);
        conn_fd_ = -1;
    }
    if (listen_fd_ >= 0) {
        ::shutdown(listen_fd_, SHUT_RDWR);
        ::close(listen_fd_);
        listen_fd_ = -1;
    }
    if (thread_.joinable()) {
        thread_.join();
    }
}

bool BackupReceiver::is_listening() const {
    return listening_ready_.load(std::memory_order_acquire);
}

bool BackupReceiver::recv_exact(int fd, std::uint8_t* out, std::size_t len) {
    std::size_t off = 0;
    while (off < len && running_.load(std::memory_order_acquire)) {
        const ssize_t n = ::recv(fd, out + off, len - off, 0);
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
        sockaddr_in caddr{};
        socklen_t clen = sizeof(caddr);
        conn_fd_ = ::accept(listen_fd_, reinterpret_cast<sockaddr*>(&caddr), &clen);
        if (conn_fd_ < 0) {
            if (!running_.load(std::memory_order_acquire)) {
                break;
            }
            continue;
        }

        while (running_.load(std::memory_order_acquire)) {
            std::uint32_t be_len = 0;
            if (!recv_exact(conn_fd_, reinterpret_cast<std::uint8_t*>(&be_len), sizeof(be_len))) {
                break;
            }
            const std::uint32_t len = ntohl(be_len);
            std::vector<std::uint8_t> entry(len);
            if (!recv_exact(conn_fd_, entry.data(), len)) {
                break;
            }
            apply_entry(entry);
        }

        ::close(conn_fd_);
        conn_fd_ = -1;
    }
}
