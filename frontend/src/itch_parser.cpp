#include "itch_parser.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <vector>

#include "engine.hpp"
#include "flat_price_map.hpp"

namespace itch {
namespace {

inline std::uint32_t read_be_u32(const std::uint8_t* p) {
    return (static_cast<std::uint32_t>(p[0]) << 24u) |
           (static_cast<std::uint32_t>(p[1]) << 16u) |
           (static_cast<std::uint32_t>(p[2]) << 8u) |
           static_cast<std::uint32_t>(p[3]);
}

inline std::uint64_t read_be_u64(const std::uint8_t* p) {
    return (static_cast<std::uint64_t>(p[0]) << 56u) |
           (static_cast<std::uint64_t>(p[1]) << 48u) |
           (static_cast<std::uint64_t>(p[2]) << 40u) |
           (static_cast<std::uint64_t>(p[3]) << 32u) |
           (static_cast<std::uint64_t>(p[4]) << 24u) |
           (static_cast<std::uint64_t>(p[5]) << 16u) |
           (static_cast<std::uint64_t>(p[6]) << 8u) |
           static_cast<std::uint64_t>(p[7]);
}

}  // namespace

std::size_t ItchParser::parse(const std::uint8_t* buf, std::size_t len, MessageHandler& handler) const {
    if (buf == nullptr || len == 0) {
        return 0;
    }

    std::size_t off = 0;
    while (off < len) {
        const char type = static_cast<char>(buf[off]);
        std::size_t msg_size = 0;

        switch (type) {
            case 'A': msg_size = kAddSize; break;
            case 'M': msg_size = kModifySize; break;
            case 'D': msg_size = kDeleteSize; break;
            case 'T': msg_size = kTradeSize; break;
            default: return off;
        }

        if (len - off < msg_size) {
            return off;
        }

        const std::uint8_t* p = buf + off + 1;
        if (type == 'A') {
            AddMessage msg{};
            msg.order_id = read_be_u64(p);
            msg.timestamp_ns = read_be_u64(p + 8);
            msg.symbol_id = read_be_u32(p + 16);
            msg.side = static_cast<char>(p[20]);
            msg.price = static_cast<std::int64_t>(read_be_u64(p + 21));
            msg.qty = read_be_u32(p + 29);
            handler.on_add(msg);
        } else if (type == 'M') {
            ModifyMessage msg{};
            msg.order_id = read_be_u64(p);
            msg.timestamp_ns = read_be_u64(p + 8);
            msg.new_qty = read_be_u32(p + 16);
            msg.new_price = static_cast<std::int64_t>(read_be_u64(p + 20));
            handler.on_modify(msg);
        } else if (type == 'D') {
            DeleteMessage msg{};
            msg.order_id = read_be_u64(p);
            msg.timestamp_ns = read_be_u64(p + 8);
            handler.on_delete(msg);
        } else {
            TradeMessage msg{};
            msg.buy_order_id = read_be_u64(p);
            msg.sell_order_id = read_be_u64(p + 8);
            msg.timestamp_ns = read_be_u64(p + 16);
            msg.price = static_cast<std::int64_t>(read_be_u64(p + 24));
            msg.qty = read_be_u32(p + 32);
            handler.on_trade(msg);
        }

        off += msg_size;
    }

    return off;
}

class ItchReplayer::EngineHandler final : public MessageHandler {
public:
    explicit EngineHandler(MatchingEngine& engine) : engine_(engine), count_(0) {}

    void on_add(const AddMessage& msg) override {
        const Side side = (msg.side == 'S') ? Side::ASK : Side::BID;
        Order order(msg.order_id, msg.price, msg.qty, side, msg.symbol_id);
        engine_.route(order);
        ++count_;
    }

    void on_modify(const ModifyMessage&) override { ++count_; }
    void on_delete(const DeleteMessage&) override { ++count_; }
    void on_trade(const TradeMessage&) override { ++count_; }

    std::size_t count() const { return count_; }

private:
    MatchingEngine& engine_;
    std::size_t count_;
};

ItchReplayer::ItchReplayer(MatchingEngine& engine) : engine_(engine) {}

bool ItchReplayer::replay_file(const std::string& path, std::size_t chunk_size) {
    return replay_file_count(path, chunk_size) > 0;
}

std::size_t ItchReplayer::replay_file_count(const std::string& path, std::size_t chunk_size) {
    if (chunk_size < ItchParser::kTradeSize) {
        chunk_size = ItchParser::kTradeSize;
    }

    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }

    ItchParser parser;
    EngineHandler handler(engine_);

    std::vector<std::uint8_t> buf(chunk_size + ItchParser::kTradeSize);
    std::size_t carry = 0;
    while (in) {
        in.read(reinterpret_cast<char*>(buf.data() + carry),
                static_cast<std::streamsize>(chunk_size));
        const std::streamsize got = in.gcount();
        if (got <= 0) {
            break;
        }

        const std::size_t total = carry + static_cast<std::size_t>(got);
        const std::size_t consumed = parser.parse(buf.data(), total, handler);
        carry = total - consumed;
        if (carry > 0) {
            std::copy(buf.begin() + static_cast<std::ptrdiff_t>(consumed),
                      buf.begin() + static_cast<std::ptrdiff_t>(total),
                      buf.begin());
        }
    }

    if (carry != 0) {
        return 0;
    }
    return handler.count();
}

}  // namespace itch
