#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <string>
#include <thread>

class LeaderLease {
public:
    LeaderLease();

    std::uint64_t epoch() const;
    std::uint64_t promote();
    bool should_step_down(std::uint64_t backup_epoch) const;

private:
    std::atomic<std::uint64_t> epoch_;
};

class HeartbeatMonitor {
public:
    explicit HeartbeatMonitor(LeaderLease& lease);
    ~HeartbeatMonitor();

    HeartbeatMonitor(const HeartbeatMonitor&) = delete;
    HeartbeatMonitor& operator=(const HeartbeatMonitor&) = delete;

    bool start_primary(const std::string& backup_host, std::uint16_t backup_port);
    bool start_backup(std::uint16_t listen_port);
    void stop();

    bool send_heartbeat();
    void set_promote_callback(std::function<void()> cb);
    bool promoted() const;

private:
    void primary_loop();
    void backup_loop();
    void default_promote();

    LeaderLease& lease_;
    std::atomic<bool> running_primary_;
    std::atomic<bool> running_backup_;
    std::atomic<bool> promoted_;

    std::thread primary_thread_;
    std::thread backup_thread_;

    std::string backup_host_;
    std::uint16_t backup_port_;
    std::uint16_t listen_port_;

    int primary_fd_;
    int backup_fd_;
    int promoted_gateway_fd_;

    std::function<void()> promote_cb_;
};
