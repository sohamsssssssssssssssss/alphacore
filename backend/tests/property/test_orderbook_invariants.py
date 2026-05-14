from hypothesis import given
from hypothesis import strategies as st


@given(st.floats(min_value=0.01, max_value=1_000_000), st.floats(min_value=0.01, max_value=1_000_000))
def test_orderbook_spread_non_negative(bid, ask):
    hi = max(bid, ask)
    lo = min(bid, ask)
    assert hi - lo >= 0
