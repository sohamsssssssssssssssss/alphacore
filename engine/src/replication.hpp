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

#include "heartbeat.hpp"

// Replication wire frame v1 (big-endian), one per log entry:
//   [u32 payload_len][u16 version = 1][u64 sender epoch][payload]
// v0 (before fencing) was [u32 payload_len][payload]. A receiver drops the
// connection on any other version or on payload_len > kMaxEntryBytes. The
// on-disk journal format is unchanged: [u32 payload_len][payload].
constexpr std::uint16_t kReplicationFrameVersion = 1;
constexpr std::uint32_t kMaxEntryBytes = 1u << 20;

class ReplicationLog {
public:
    ReplicationLog(const std::string& journal_path, LeaderLease& lease);
    ~ReplicationLog();

    ReplicationLog(const ReplicationLog&) = delete;
    ReplicationLog& operator=(const ReplicationLog&) = delete;

    bool connect_to_backup(const std::string& host, std::uint16_t port);
    // Refused (returns false, nothing journaled or sent) unless lease.is_current().
    bool append(const std::uint8_t* entry, std::size_t len);
    void close_connection();

private:
    bool connect_locked();
    bool send_frame_locked(const std::vector<std::uint8_t>& frame);
    void flush_buffered_locked();
    void retry_loop();

    std::string journal_path_;
    LeaderLease& lease_;
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
    explicit BackupReceiver(LeaderLease& lease);
    ~BackupReceiver();

    BackupReceiver(const BackupReceiver&) = delete;
    BackupReceiver& operator=(const BackupReceiver&) = delete;

    void listen(std::uint16_t port);
    void stop();
    bool is_listening() const;
    std::size_t rejected_stale() const;  // entries dropped under rule (d)

    void set_apply_handler(std::function<void(const std::vector<std::uint8_t>&)> handler);
    virtual void apply_entry(const std::vector<std::uint8_t>& entry);

private:
    void run(std::uint16_t port);
    bool recv_exact(int fd, std::uint8_t* out, std::size_t len);

    LeaderLease& lease_;
    std::atomic<bool> running_;
    std::atomic<bool> listening_ready_;
    std::atomic<std::size_t> rejected_stale_;
    std::thread thread_;
    std::function<void(const std::vector<std::uint8_t>&)> apply_handler_;
    std::mutex apply_mu_;
    int listen_fd_;  // used only by the receiver thread until stop() has joined it
    int conn_fd_;
};
