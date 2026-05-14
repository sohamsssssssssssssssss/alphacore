from data.nse_fetcher import NSEFetcher


def test_nse_fetcher_symbols_uppercase():
    fetcher = NSEFetcher(["reliance", "tcs"])
    assert fetcher.symbols == ["RELIANCE", "TCS"]
