#include "gateway.hpp"

#include <chrono>
#include <cstring>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#ifdef __linux__
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

Gateway::Gateway(MatchingEngine& engine, std::uint16_t port)
    : engine_(engine), port_(port), running_(false), thread_() {}

Gateway::~Gateway() {
    stop();
}

void Gateway::start() {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
        return;
    }
    thread_ = std::thread(&Gateway::run, this);
}

void Gateway::stop() {
    bool expected = true;
    if (!running_.compare_exchange_strong(expected, false, std::memory_order_acq_rel)) {
        return;
    }
    if (thread_.joinable()) {
        thread_.join();
    }
}

#ifdef __linux__
namespace {

struct ConnState {
    int fd;
    std::string buffer;
};

struct OrderMeta {
    int fd;
    std::string cl_ord_id;
    Side side;
};

bool set_nonblocking(int fd) {
    const int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) {
        return false;
    }
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

std::vector<std::string> split_fix_fields(const std::string& msg) {
    std::vector<std::string> fields;
    std::size_t start = 0;
    while (start < msg.size()) {
        const std::size_t pos = msg.find('\x01', start);
        if (pos == std::string::npos) {
            break;
        }
        if (pos > start) {
            fields.push_back(msg.substr(start, pos - start));
        }
        start = pos + 1;
    }
    return fields;
}

bool parse_new_order(const std::string& msg,
                     std::string& cl_ord_id,
                     Side& side,
                     std::uint32_t& qty,
                     std::int64_t& price,
                     std::uint32_t& symbol_id) {
    bool has_msg_type = false;
    bool has_cl_ord_id = false;
    bool has_side = false;
    bool has_qty = false;
    bool has_price = false;
    bool has_symbol = false;
    std::string symbol;

    for (const auto& field : split_fix_fields(msg)) {
        const auto eq = field.find('=');
        if (eq == std::string::npos) {
            continue;
        }
        const std::string tag = field.substr(0, eq);
        const std::string val = field.substr(eq + 1);

        if (tag == "35") {
            has_msg_type = (val == "D");
        } else if (tag == "11") {
            cl_ord_id = val;
            has_cl_ord_id = !cl_ord_id.empty();
        } else if (tag == "54") {
            if (val == "1") {
                side = Side::BID;
                has_side = true;
            } else if (val == "2") {
                side = Side::ASK;
                has_side = true;
            }
        } else if (tag == "38") {
            qty = static_cast<std::uint32_t>(std::stoul(val));
            has_qty = true;
        } else if (tag == "44") {
            price = static_cast<std::int64_t>(std::stoll(val));
            has_price = true;
        } else if (tag == "55") {
            symbol = val;
            has_symbol = !symbol.empty();
        }
    }

    if (!(has_msg_type && has_cl_ord_id && has_side && has_qty && has_price && has_symbol)) {
        return false;
    }

    symbol_id = static_cast<std::uint32_t>(std::hash<std::string>{}(symbol));
    return true;
}

std::string build_exec_report(const std::string& cl_ord_id, Side side, std::uint32_t qty, std::int64_t px) {
    std::string fix;
    fix.reserve(128);
    fix += "35=8\x01";
    fix += "11=" + cl_ord_id + "\x01";
    fix += "54=";
    fix += (side == Side::BID ? "1\x01" : "2\x01");
    fix += "32=" + std::to_string(qty) + "\x01";
    fix += "31=" + std::to_string(px) + "\x01";
    fix += "39=2\x01";
    return fix;
}

}  // namespace

void Gateway::run() {
    int server_fd = -1;
    int epoll_fd = -1;
    std::unordered_map<int, ConnState> conns;
    std::unordered_map<std::uint64_t, OrderMeta> order_meta;
    std::uint64_t next_order_id = 1;

    server_fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        return;
    }

    int one = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    if (!set_nonblocking(server_fd)) {
        ::close(server_fd);
        return;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port_);

    if (::bind(server_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(server_fd);
        return;
    }

    if (::listen(server_fd, 256) != 0) {
        ::close(server_fd);
        return;
    }

    epoll_fd = epoll_create1(0);
    if (epoll_fd < 0) {
        ::close(server_fd);
        return;
    }

    epoll_event ev{};
    ev.events = EPOLLIN;
    ev.data.fd = server_fd;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, server_fd, &ev) != 0) {
        ::close(epoll_fd);
        ::close(server_fd);
        return;
    }

    std::vector<epoll_event> events(128);

    while (running_.load(std::memory_order_acquire)) {
        Trade tr{};
        while (engine_.pop_trade(tr)) {
            auto send_fill = [&](std::uint64_t oid) {
                auto it = order_meta.find(oid);
                if (it == order_meta.end()) {
                    return;
                }
                const std::string msg = build_exec_report(it->second.cl_ord_id, it->second.side, tr.qty, tr.price);
                (void)::send(it->second.fd, msg.data(), msg.size(), 0);
                order_meta.erase(it);
            };
            send_fill(tr.buy_order_id);
            send_fill(tr.sell_order_id);
        }

        const int n = epoll_wait(epoll_fd, events.data(), static_cast<int>(events.size()), 20);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }

        for (int i = 0; i < n; ++i) {
            const int fd = events[static_cast<std::size_t>(i)].data.fd;

            if (fd == server_fd) {
                for (;;) {
                    sockaddr_in caddr{};
                    socklen_t clen = sizeof(caddr);
                    const int cfd = ::accept(server_fd, reinterpret_cast<sockaddr*>(&caddr), &clen);
                    if (cfd < 0) {
                        if (errno == EAGAIN || errno == EWOULDBLOCK) {
                            break;
                        }
                        break;
                    }
                    if (!set_nonblocking(cfd)) {
                        ::close(cfd);
                        continue;
                    }
                    epoll_event cev{};
                    cev.events = EPOLLIN;
                    cev.data.fd = cfd;
                    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, cfd, &cev) != 0) {
                        ::close(cfd);
                        continue;
                    }
                    conns[cfd] = ConnState{cfd, ""};
                }
                continue;
            }

            auto cit = conns.find(fd);
            if (cit == conns.end()) {
                continue;
            }

            bool close_conn = false;
            for (;;) {
                char buf[4096];
                const ssize_t r = ::recv(fd, buf, sizeof(buf), 0);
                if (r > 0) {
                    cit->second.buffer.append(buf, static_cast<std::size_t>(r));
                    continue;
                }
                if (r == 0) {
                    close_conn = true;
                    break;
                }
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    break;
                }
                close_conn = true;
                break;
            }

            std::size_t msg_end = std::string::npos;
            while ((msg_end = cit->second.buffer.find("10=")) != std::string::npos) {
                const std::size_t soh_after_10 = cit->second.buffer.find('\x01', msg_end);
                if (soh_after_10 == std::string::npos) {
                    break;
                }

                const std::string one_msg = cit->second.buffer.substr(0, soh_after_10 + 1);
                cit->second.buffer.erase(0, soh_after_10 + 1);

                std::string cl_ord_id;
                Side side = Side::BID;
                std::uint32_t qty = 0;
                std::int64_t price = 0;
                std::uint32_t symbol_id = 0;
                if (!parse_new_order(one_msg, cl_ord_id, side, qty, price, symbol_id)) {
                    continue;
                }

                const std::uint64_t oid = next_order_id++;
                order_meta.emplace(oid, OrderMeta{fd, cl_ord_id, side});
                engine_.route(Order(oid, price, qty, side, symbol_id));
            }

            if (close_conn) {
                epoll_ctl(epoll_fd, EPOLL_CTL_DEL, fd, nullptr);
                ::close(fd);
                conns.erase(fd);
            }
        }
    }

    for (auto& kv : conns) {
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, kv.first, nullptr);
        ::close(kv.first);
    }
    ::close(epoll_fd);
    ::close(server_fd);
}

#else

void Gateway::run() {
    while (running_.load(std::memory_order_acquire)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}

#endif
