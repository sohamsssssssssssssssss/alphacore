#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

// Epoch fencing per specs/tla_engine_models/PrimaryBackup.tla (2 nodes, ids 0 and 1).
// Epoch e is owned by node e % 2, so two distinct nodes can never hold the same
// epoch. promote() takes the smallest owned epoch > max_seen. State is in memory
// only: restart safety is not covered (see specs/REPLICATION_FINDING.md).
class LeaderLease {
public:
    explicit LeaderLease(std::uint32_t node_id = 0);  // throws if node_id > 1

    std::uint32_t node_id() const;
    std::uint64_t epoch() const;
    std::uint64_t max_seen() const;
    bool is_primary() const;
    bool is_current() const;  // primary and no newer epoch seen

    std::uint64_t promote();
    // Rule (e): a primary steps down on any epoch >= its own from another node.
    bool should_step_down(std::uint64_t other_epoch) const;
    // Rules (a), (d), (e) for a message from the other node: returns false and
    // changes nothing if other_epoch < max_seen; otherwise records it and steps
    // down if should_step_down(other_epoch).
    bool accept(std::uint64_t other_epoch);

private:
    bool should_step_down_locked(std::uint64_t other_epoch) const;

    mutable std::mutex mu_;
    const std::uint32_t node_id_;
    std::uint64_t epoch_;
    std::uint64_t max_seen_;
    bool primary_;
};

// Heartbeat wire format v1: 16 bytes, big-endian
//   [u32 version = 1][u32 sender node_id][u64 sender epoch]
// Packets of any other size/version, or from this node's own id, are ignored.
// (v0, before fencing, was 8 bytes: [u32 epoch][u32 timestamp].)
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
    bool promoted() const;      // currently acting as primary after a promotion
    bool stepped_down() const;  // fenced by a newer epoch at least once

private:
    void primary_loop();
    void backup_loop();
    void default_promote();

    LeaderLease& lease_;
    std::atomic<bool> running_primary_;
    std::atomic<bool> running_backup_;
    std::atomic<bool> promoted_;
    std::atomic<bool> stepped_down_;

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
