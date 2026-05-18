#include <cstdint>
#include <string>

#include <pybind11/pybind11.h>

#include "engine.hpp"
#include "flat_price_map.hpp"
#include "itch_parser.hpp"

namespace py = pybind11;

namespace {

char side_to_char(Side s) {
    return (s == Side::ASK) ? 'S' : 'B';
}

Side char_to_side(char c) {
    return (c == 'S') ? Side::ASK : Side::BID;
}

class PyItchReplayer {
public:
    PyItchReplayer(std::string filepath, MatchingEngine& engine)
        : filepath_(std::move(filepath)), replayer_(engine) {}

    int replay() {
        return static_cast<int>(replayer_.replay_file_count(filepath_));
    }

private:
    std::string filepath_;
    itch::ItchReplayer replayer_;
};

}  // namespace

PYBIND11_MODULE(alphacore_cpp, m) {
    py::class_<Order>(m, "Order")
        .def(py::init<>())
        .def_readwrite("order_id", &Order::order_id)
        .def_readwrite("symbol_id", &Order::symbol_id)
        .def_readwrite("price", &Order::price)
        .def_readwrite("qty", &Order::qty)
        .def_readwrite("timestamp_ns", &Order::timestamp_ns)
        .def_property(
            "side",
            [](const Order& o) { return std::string(1, side_to_char(o.side)); },
            [](Order& o, const std::string& v) {
                if (v.empty()) {
                    throw std::runtime_error("side must be 'B' or 'S'");
                }
                o.side = char_to_side(v[0]);
            });

    py::class_<Trade>(m, "Trade")
        .def(py::init<>())
        .def_readwrite("buy_order_id", &Trade::buy_order_id)
        .def_readwrite("sell_order_id", &Trade::sell_order_id)
        .def_readwrite("price", &Trade::price)
        .def_readwrite("qty", &Trade::qty)
        .def_readwrite("timestamp_ns", &Trade::timestamp_ns);

    py::class_<MatchingEngine>(m, "MatchingEngine")
        .def(py::init<std::size_t>(), py::arg("num_threads"))
        .def("start", &MatchingEngine::start)
        .def("stop", &MatchingEngine::stop)
        .def("submit", [](MatchingEngine& eng, const Order& o) {
            if (o.qty == 0) {
                throw std::runtime_error("qty must be > 0");
            }
            if (o.price <= 0) {
                throw std::runtime_error("price must be > 0");
            }
            eng.route(o);
        }, py::arg("order"))
        .def("pop_trade", [](MatchingEngine& eng) -> py::object {
            Trade t{};
            if (eng.pop_trade(t)) {
                return py::cast(t);
            }
            return py::none();
        });

    py::class_<PyItchReplayer>(m, "ItchReplayer")
        .def(py::init<std::string, MatchingEngine&>(), py::arg("filepath"), py::arg("engine"))
        .def("replay", &PyItchReplayer::replay);

    py::class_<FlatPriceMap>(m, "FlatPriceMap")
        .def(py::init<std::int64_t, std::int64_t, std::int64_t>(),
             py::arg("min_price"),
             py::arg("max_price"),
             py::arg("tick_size"))
        .def("best_bid", &FlatPriceMap::best_bid_price)
        .def("best_ask", &FlatPriceMap::best_ask_price);
}
