#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <new>
#include <type_traits>

#include "fault_injector.hpp"

template <typename T, std::size_t N = 1'000'000>
class Pool {
    static_assert(N > 0, "Pool size N must be greater than 0");

public:
    Pool() noexcept(std::is_nothrow_constructible_v<T>) : top_(N) {
        for (std::size_t i = 0; i < N; ++i) {
            free_stack_[i] = N - 1 - i;
        }
    }

    template <typename... Args>
    T* acquire(Args&&... args) noexcept(std::is_nothrow_constructible_v<T, Args...>) {
#ifdef ALPHACORE_FAULT_INJECT
        if (alphacore::FaultInjector::get().should_inject(alphacore::FaultType::POOL_EXHAUSTION)) {
            return nullptr;
        }
#endif

        if (top_ == 0) {
            return nullptr;
        }

        const std::size_t idx = free_stack_[--top_];
        T* ptr = &storage_[idx];
        ptr->~T();
        new (ptr) T(static_cast<Args&&>(args)...);
        return ptr;
    }

    void release(T* ptr) noexcept {
        if (ptr == nullptr) {
            return;
        }

        const auto base = reinterpret_cast<std::uintptr_t>(&storage_[0]);
        const auto addr = reinterpret_cast<std::uintptr_t>(ptr);
        const auto end = reinterpret_cast<std::uintptr_t>(&storage_[N - 1]) + sizeof(T);

        if (addr < base || addr >= end) {
            return;
        }

        const std::size_t idx = static_cast<std::size_t>(ptr - &storage_[0]);
        free_stack_[top_++] = idx;
    }

    [[nodiscard]] constexpr std::size_t capacity() const noexcept { return N; }
    [[nodiscard]] std::size_t available() const noexcept { return top_; }

private:
    alignas(T) std::array<T, N> storage_{};
    std::array<std::size_t, N> free_stack_{};
    std::size_t top_;
};
