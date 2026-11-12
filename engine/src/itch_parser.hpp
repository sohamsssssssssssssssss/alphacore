#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

class MatchingEngine;

namespace itch {

struct AddMessage {
    std::uint64_t order_id;
    std::uint64_t timestamp_ns;
    std::uint32_t symbol_id;
    char side;
    std::int64_t price;
    std::uint32_t qty;
};

struct ModifyMessage {
    std::uint64_t order_id;
    std::uint64_t timestamp_ns;
    std::uint32_t new_qty;
    std::int64_t new_price;
};

struct DeleteMessage {
    std::uint64_t order_id;
    std::uint64_t timestamp_ns;
};

struct TradeMessage {
    std::uint64_t buy_order_id;
    std::uint64_t sell_order_id;
    std::uint64_t timestamp_ns;
    std::int64_t price;
    std::uint32_t qty;
};

class MessageHandler {
public:
    virtual ~MessageHandler() = default;

    virtual void on_add(const AddMessage& msg) = 0;
    virtual void on_modify(const ModifyMessage& msg) = 0;
    virtual void on_delete(const DeleteMessage& msg) = 0;
    virtual void on_trade(const TradeMessage& msg) = 0;
};

class ItchParser {
public:
    static constexpr std::size_t kAddSize = 34;
    static constexpr std::size_t kModifySize = 29;
    static constexpr std::size_t kDeleteSize = 17;
    static constexpr std::size_t kTradeSize = 37;

    std::size_t parse(const std::uint8_t* buf, std::size_t len, MessageHandler& handler) const;
};

class ItchReplayer {
public:
    explicit ItchReplayer(MatchingEngine& engine);

    bool replay_file(const std::string& path, std::size_t chunk_size = (1u << 20));
    std::size_t replay_file_count(const std::string& path, std::size_t chunk_size = (1u << 20));

private:
    class EngineHandler;

    MatchingEngine& engine_;
};

}  // namespace itch
