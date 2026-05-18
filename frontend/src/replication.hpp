#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

class ReplicationLog {
public:
    explicit ReplicationLog(const std::string& journal_path);
    ~ReplicationLog();

    ReplicationLog(const ReplicationLog&) = delete;
    ReplicationLog& operator=(const ReplicationLog&) = delete;

    bool connect_to_backup(const std::string& host, std::uint16_t port);
    void append(const std::uint8_t* entry, std::size_t len);
    void close_connection();

private:
    bool connect_locked();
    bool send_frame_locked(const std::uint8_t* entry, std::size_t len);
    void flush_buffered_locked();
    void retry_loop();

    std::string journal_path_;
    std::string backup_host_;
    std::uint16_t backup_port_;

    int sock_fd_;
    std::atomic<bool> running_;
    std::thread retry_thread_;

    std::mutex mu_;
    std::deque<std::vector<std::uint8_t>> buffered_;
};

class BackupReceiver {
public:
    BackupReceiver();
    ~BackupReceiver();

    BackupReceiver(const BackupReceiver&) = delete;
    BackupReceiver& operator=(const BackupReceiver&) = delete;

    void listen(std::uint16_t port);
    void stop();
    bool is_listening() const;

    void set_apply_handler(std::function<void(const std::vector<std::uint8_t>&)> handler);
    virtual void apply_entry(const std::vector<std::uint8_t>& entry);

private:
    void run(std::uint16_t port);
    bool recv_exact(int fd, std::uint8_t* out, std::size_t len);

    std::atomic<bool> running_;
    std::atomic<bool> listening_ready_;
    std::thread thread_;
    std::function<void(const std::vector<std::uint8_t>&)> apply_handler_;
    std::mutex apply_mu_;
    int listen_fd_;
    int conn_fd_;
};
