from hypothesis import given
from hypothesis import strategies as st


@given(st.integers(min_value=0, max_value=100))
def test_spoof_score_bounds(score):
    assert 0 <= score <= 100
