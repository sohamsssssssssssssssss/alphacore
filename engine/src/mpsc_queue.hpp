#pragma once

/*
Memory ordering in this queue:
- Producer writes payload into the claimed slot, then publishes the per-slot sequence
  with memory_order_release. That release makes all prior writes to the slot visible
  before the sequence update becomes visible.
- Consumer reads the per-slot sequence with memory_order_acquire. If it observes the
  expected sequence value, acquire synchronizes-with the producer's release, so the
  payload in that slot is fully initialized and safe to read.

False sharing:
- Producer-side indices and consumer-side index are heavily contended in opposite roles.
  If they share one cache line, each update causes cache invalidations on the other core,
  increasing coherence traffic and latency.
- alignas(64) places these states on separate cache lines, reducing needless bouncing.

Why multiple producers are safe:
- Producers reserve positions by CAS on a single atomic write ticket. Only one producer
  can claim a given position.
- After claiming, each producer writes only its own slot and then publishes readiness via
  the slot sequence atomic. Slots are consumed in order by one consumer, avoiding races.
*/

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#include <utility>

#include "fault_injector.hpp"

template <typename T, std::size_t N>
class MpscQueue {
    static_assert(N > 0, "N must be > 0");
    static_assert((N & (N - 1)) == 0, "N must be a power of 2");

    struct Cell {
        std::atomic<std::size_t> seq;
        T value;
    };

public:
    MpscQueue() : producer_{0}, consumer_{0} {
        for (std::size_t i = 0; i < N; ++i) {
            cells_[i].seq.store(i, std::memory_order_relaxed);
        }
    }

    MpscQueue(const MpscQueue&) = delete;
    MpscQueue& operator=(const MpscQueue&) = delete;

    bool push(const T& item) noexcept(std::is_nothrow_copy_assignable_v<T>) {
#ifdef ALPHACORE_FAULT_INJECT
        if (alphacore::FaultInjector::get().should_inject(alphacore::FaultType::QUEUE_FULL)) {
            return false;
        }
#endif

        std::size_t pos = producer_.write_ticket.load(std::memory_order_relaxed);

        for (;;) {
            Cell& cell = cells_[pos & mask_];
            const std::size_t seq = cell.seq.load(std::memory_order_acquire);
            const intptr_t dif = static_cast<intptr_t>(seq) - static_cast<intptr_t>(pos);

            if (dif == 0) {
                if (producer_.write_ticket.compare_exchange_weak(
                        pos, pos + 1, std::memory_order_relaxed, std::memory_order_relaxed)) {
                    cell.value = item;
                    cell.seq.store(pos + 1, std::memory_order_release);
                    return true;
                }
                continue;
            }

            if (dif < 0) {
                return false;
            }

            pos = producer_.write_ticket.load(std::memory_order_relaxed);
        }
    }

    bool push(T&& item) noexcept(std::is_nothrow_move_assignable_v<T>) {
#ifdef ALPHACORE_FAULT_INJECT
        if (alphacore::FaultInjector::get().should_inject(alphacore::FaultType::QUEUE_FULL)) {
            return false;
        }
#endif

        std::size_t pos = producer_.write_ticket.load(std::memory_order_relaxed);

        for (;;) {
            Cell& cell = cells_[pos & mask_];
            const std::size_t seq = cell.seq.load(std::memory_order_acquire);
            const intptr_t dif = static_cast<intptr_t>(seq) - static_cast<intptr_t>(pos);

            if (dif == 0) {
                if (producer_.write_ticket.compare_exchange_weak(
                        pos, pos + 1, std::memory_order_relaxed, std::memory_order_relaxed)) {
                    cell.value = std::move(item);
                    cell.seq.store(pos + 1, std::memory_order_release);
                    return true;
                }
                continue;
            }

            if (dif < 0) {
                return false;
            }

            pos = producer_.write_ticket.load(std::memory_order_relaxed);
        }
    }

    bool pop(T& out) noexcept(std::is_nothrow_copy_assignable_v<T>) {
        const std::size_t pos = consumer_.read_ticket.load(std::memory_order_relaxed);
        Cell& cell = cells_[pos & mask_];

        const std::size_t seq = cell.seq.load(std::memory_order_acquire);
        const intptr_t dif = static_cast<intptr_t>(seq) - static_cast<intptr_t>(pos + 1);

        if (dif != 0) {
            return false;
        }

        out = cell.value;
        cell.seq.store(pos + N, std::memory_order_release);
        consumer_.read_ticket.store(pos + 1, std::memory_order_relaxed);
        return true;
    }

private:
    static constexpr std::size_t mask_ = N - 1;

    std::array<Cell, N> cells_;

    struct alignas(64) ProducerState {
        std::atomic<std::size_t> write_ticket;
    };

    struct alignas(64) ConsumerState {
        std::atomic<std::size_t> read_ticket;
    };

    ProducerState producer_;
    char pad_[64];
    ConsumerState consumer_;
};
