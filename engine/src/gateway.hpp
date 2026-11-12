#pragma once

#include <atomic>
#include <cstdint>
#include <string>
#include <thread>

#include "engine.hpp"

class Gateway {
public:
    explicit Gateway(MatchingEngine& engine, std::uint16_t port = 9000);
    ~Gateway();

    Gateway(const Gateway&) = delete;
    Gateway& operator=(const Gateway&) = delete;

    void start();
    void stop();

private:
    void run();

    MatchingEngine& engine_;
    std::uint16_t port_;
    std::atomic<bool> running_;
    std::thread thread_;
};
