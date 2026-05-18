#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>

#include "../src/itch_parser.hpp"

namespace {

inline void write_be_u32(std::uint8_t* p, std::uint32_t v) {
    p[0] = static_cast<std::uint8_t>((v >> 24u) & 0xffu);
    p[1] = static_cast<std::uint8_t>((v >> 16u) & 0xffu);
    p[2] = static_cast<std::uint8_t>((v >> 8u) & 0xffu);
    p[3] = static_cast<std::uint8_t>(v & 0xffu);
}

inline void write_be_u64(std::uint8_t* p, std::uint64_t v) {
    p[0] = static_cast<std::uint8_t>((v >> 56u) & 0xffu);
    p[1] = static_cast<std::uint8_t>((v >> 48u) & 0xffu);
    p[2] = static_cast<std::uint8_t>((v >> 40u) & 0xffu);
    p[3] = static_cast<std::uint8_t>((v >> 32u) & 0xffu);
    p[4] = static_cast<std::uint8_t>((v >> 24u) & 0xffu);
    p[5] = static_cast<std::uint8_t>((v >> 16u) & 0xffu);
    p[6] = static_cast<std::uint8_t>((v >> 8u) & 0xffu);
    p[7] = static_cast<std::uint8_t>(v & 0xffu);
}

class NullHandler final : public itch::MessageHandler {
public:
    void on_add(const itch::AddMessage& msg) override {
        checksum ^= (msg.order_id + static_cast<std::uint64_t>(msg.price) + msg.qty + msg.symbol_id);
    }

    void on_modify(const itch::ModifyMessage& msg) override {
        checksum ^= (msg.order_id + static_cast<std::uint64_t>(msg.new_price) + msg.new_qty);
    }

    void on_delete(const itch::DeleteMessage& msg) override {
        checksum ^= msg.order_id;
    }

    void on_trade(const itch::TradeMessage& msg) override {
        checksum ^= (msg.buy_order_id + msg.sell_order_id + static_cast<std::uint64_t>(msg.price) + msg.qty);
    }

    std::uint64_t checksum{0};
};

}  // namespace

int main() {
    constexpr std::size_t kMessages = 100'000'000;
    constexpr std::size_t kMsgSize = itch::ItchParser::kAddSize;
    constexpr std::size_t kBytes = kMessages * kMsgSize;

    std::unique_ptr<std::uint8_t[]> data(new (std::nothrow) std::uint8_t[kBytes]);
    if (!data) {
        std::fprintf(stderr, "failed to allocate %zu bytes\n", kBytes);
        return 1;
    }

    for (std::size_t i = 0; i < kMessages; ++i) {
        std::uint8_t* p = data.get() + (i * kMsgSize);
        p[0] = static_cast<std::uint8_t>('A');
        write_be_u64(p + 1, static_cast<std::uint64_t>(i + 1));
        write_be_u64(p + 9, static_cast<std::uint64_t>(1'000'000'000ull + i));
        write_be_u32(p + 17, static_cast<std::uint32_t>(i % 2048));
        p[21] = (i & 1u) ? static_cast<std::uint8_t>('S') : static_cast<std::uint8_t>('B');
        write_be_u64(p + 22, static_cast<std::uint64_t>(10'000 + (i % 1'000)));
        write_be_u32(p + 30, static_cast<std::uint32_t>(100 + (i % 50)));
    }

    itch::ItchParser parser;
    NullHandler handler;

    const auto t0 = std::chrono::steady_clock::now();
    const std::size_t consumed = parser.parse(data.get(), kBytes, handler);
    const auto t1 = std::chrono::steady_clock::now();

    if (consumed != kBytes) {
        std::fprintf(stderr, "parse consumed %zu/%zu bytes\n", consumed, kBytes);
        return 2;
    }

    const double elapsed_ns = static_cast<double>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count());
    const double ns_per_msg = elapsed_ns / static_cast<double>(kMessages);

    std::printf("ITCH parse: %.2f ns/msg over 100M messages\n", ns_per_msg);
    std::fprintf(stderr, "checksum=%llu\n", static_cast<unsigned long long>(handler.checksum));
    return 0;
}
