#include <cstdlib>
#include <iostream>

#include "../../src/fault_injector.hpp"
#include "../../src/mpsc_queue.hpp"
#include "../../src/pool.hpp"

int main() {
    int failures = 0;

    ::setenv("OB_FAULT_POOL_EXHAUSTION", "1", 1);
    ::setenv("OB_FAULT_QUEUE_FULL", "1", 1);

    auto& fi = alphacore::FaultInjector::get();

    Pool<int, 8> pool;
    int* p = pool.acquire(42);
    if (p == nullptr) {
        std::cout << "PASS: POOL_EXHAUSTION injection returns nullptr\n";
    } else {
        std::cout << "FAIL: POOL_EXHAUSTION injection did not return nullptr\n";
        ++failures;
    }

    MpscQueue<int, 8> q;
    const bool pushed = q.push(123);
    if (!pushed) {
        std::cout << "PASS: QUEUE_FULL injection returns false\n";
    } else {
        std::cout << "FAIL: QUEUE_FULL injection did not return false\n";
        ++failures;
    }

    return failures == 0 ? 0 : 1;
}
