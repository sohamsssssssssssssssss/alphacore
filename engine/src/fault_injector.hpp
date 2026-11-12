#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <cstdlib>

namespace alphacore {

enum class FaultType : std::uint8_t {
    JOURNAL_SHORT_WRITE = 0,
    JOURNAL_BIT_FLIP,
    FSYNC_FAILURE,
    POOL_EXHAUSTION,
    QUEUE_FULL,
    GATEWAY_FRAGMENTATION,
    DB_CONNECTION_DROP,
    FEED_INTERRUPTION,
    BROKER_TIMEOUT,
    PARTIAL_FILL_CRASH,
    COUNT
};

class FaultInjector {
public:
    static FaultInjector& get() {
        static FaultInjector instance;
        return instance;
    }

    void enable(FaultType fault) noexcept {
#ifdef ALPHACORE_FAULT_INJECT
        active_mask_.fetch_or(bit_for(fault), std::memory_order_relaxed);
#else
        (void)fault;
#endif
    }

    void disable(FaultType fault) noexcept {
#ifdef ALPHACORE_FAULT_INJECT
        active_mask_.fetch_and(~bit_for(fault), std::memory_order_relaxed);
#else
        (void)fault;
#endif
    }

    [[nodiscard]] bool should_inject(FaultType fault) const noexcept {
#ifdef ALPHACORE_FAULT_INJECT
        return (active_mask_.load(std::memory_order_relaxed) & bit_for(fault)) != 0;
#else
        (void)fault;
        return false;
#endif
    }

private:
    FaultInjector() noexcept : active_mask_(0) {
#ifdef ALPHACORE_FAULT_INJECT
        for (std::size_t i = 0; i < fault_env_names_.size(); ++i) {
            const char* value = std::getenv(fault_env_names_[i]);
            if (value != nullptr && value[0] == '1' && value[1] == '\0') {
                active_mask_.fetch_or(static_cast<std::uint32_t>(1u << i), std::memory_order_relaxed);
            }
        }
#endif
    }

    static constexpr std::uint32_t bit_for(FaultType fault) noexcept {
        return static_cast<std::uint32_t>(1u << static_cast<std::uint8_t>(fault));
    }

#ifdef ALPHACORE_FAULT_INJECT
    static constexpr std::array<const char*, static_cast<std::size_t>(FaultType::COUNT)> fault_env_names_ = {
        "OB_FAULT_JOURNAL_SHORT_WRITE",
        "OB_FAULT_JOURNAL_BIT_FLIP",
        "OB_FAULT_FSYNC_FAILURE",
        "OB_FAULT_POOL_EXHAUSTION",
        "OB_FAULT_QUEUE_FULL",
        "OB_FAULT_GATEWAY_FRAGMENTATION",
        "OB_FAULT_DB_CONNECTION_DROP",
        "OB_FAULT_FEED_INTERRUPTION",
        "OB_FAULT_BROKER_TIMEOUT",
        "OB_FAULT_PARTIAL_FILL_CRASH",
    };
#endif

    std::atomic<std::uint32_t> active_mask_;
};

/*
Suggested call sites for the other 8 faults:
1) JOURNAL_SHORT_WRITE: journal append/write path before final buffer flush.
2) JOURNAL_BIT_FLIP: right after journal buffer serialization, before checksum.
3) FSYNC_FAILURE: immediately before/around fsync()/fdatasync() syscall.
4) GATEWAY_FRAGMENTATION: FIX/TCP gateway recv path to split frame across reads.
5) DB_CONNECTION_DROP: DB writer path after begin/prepare, before commit.
6) FEED_INTERRUPTION: market data ingest loop to stop reads mid-session.
7) BROKER_TIMEOUT: execution adapter around broker API request/response wait.
8) PARTIAL_FILL_CRASH: matching/OMS fill handling after first partial fill event.
*/

}  // namespace alphacore
