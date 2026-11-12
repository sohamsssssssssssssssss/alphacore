import alphacore_cpp as ac


def main() -> int:
    eng = ac.MatchingEngine(4)
    eng.start()

    bid = ac.Order()
    bid.order_id = 1
    bid.symbol_id = 42
    bid.price = 10000
    bid.qty = 10
    bid.side = 'B'
    bid.timestamp_ns = 1

    ask = ac.Order()
    ask.order_id = 2
    ask.symbol_id = 42
    ask.price = 10000
    ask.qty = 10
    ask.side = 'S'
    ask.timestamp_ns = 2

    eng.submit(bid)
    eng.submit(ask)

    trade = None
    for _ in range(10000):
        trade = eng.pop_trade()
        if trade is not None:
            break

    eng.stop()

    if trade is None:
        print("FAIL: no trade returned")
        return 1

    if trade.qty == 10 and trade.price == 10000:
        print("PASS: trade returned")
        return 0

    print("FAIL: unexpected trade values")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
