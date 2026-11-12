#include <chrono>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>

#include "../src/engine.hpp"
#include "../src/gateway.hpp"

#ifdef __linux__
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

int main() {
#ifdef __linux__
    MatchingEngine engine(1, 1, 1000, 1);
    engine.start();

    Gateway gateway(engine, 19000);
    gateway.start();

    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    const int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        std::cout << "Gateway FIX roundtrip: FAIL\n";
        gateway.stop();
        engine.stop();
        return 1;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(19000);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(fd);
        std::cout << "Gateway FIX roundtrip: FAIL\n";
        gateway.stop();
        engine.stop();
        return 1;
    }

    const char soh = '\x01';
    std::string nos;
    nos += "8=FIX.4.4"; nos += soh;
    nos += "35=D"; nos += soh;
    nos += "11=ABC123"; nos += soh;
    nos += "54=1"; nos += soh;
    nos += "38=10"; nos += soh;
    nos += "44=100"; nos += soh;
    nos += "55=TEST"; nos += soh;
    nos += "10=000"; nos += soh;

    if (::send(fd, nos.data(), nos.size(), 0) < 0) {
        ::close(fd);
        std::cout << "Gateway FIX roundtrip: FAIL\n";
        gateway.stop();
        engine.stop();
        return 1;
    }

    // Make it cross so a fill is guaranteed.
    const char soh2 = '\x01';
    std::string contra;
    contra += "8=FIX.4.4"; contra += soh2;
    contra += "35=D"; contra += soh2;
    contra += "11=XYZ999"; contra += soh2;
    contra += "54=2"; contra += soh2;
    contra += "38=10"; contra += soh2;
    contra += "44=100"; contra += soh2;
    contra += "55=TEST"; contra += soh2;
    contra += "10=000"; contra += soh2;
    (void)::send(fd, contra.data(), contra.size(), 0);

    bool ok = false;
    std::string recv_buf;
    recv_buf.reserve(1024);

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (std::chrono::steady_clock::now() < deadline) {
        char buf[1024];
        const ssize_t n = ::recv(fd, buf, sizeof(buf), MSG_DONTWAIT);
        if (n > 0) {
            recv_buf.append(buf, static_cast<std::size_t>(n));
            if (recv_buf.find("35=8\x01") != std::string::npos && recv_buf.find("39=2\x01") != std::string::npos) {
                ok = true;
                break;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    ::close(fd);
    gateway.stop();
    engine.stop();

    std::cout << "Gateway FIX roundtrip: " << (ok ? "PASS" : "FAIL") << "\n";
    return ok ? 0 : 1;
#else
    std::cout << "Gateway FIX roundtrip: PASS (non-linux stub)\n";
    return 0;
#endif
}
