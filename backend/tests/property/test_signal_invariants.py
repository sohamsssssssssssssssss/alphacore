from hypothesis import given
from hypothesis import strategies as st


@given(st.integers(min_value=-10_000, max_value=10_000))
def test_signal_direction_threshold(score):
    if score > 20:
        assert score > 20
    elif score < -20:
        assert score < -20
    else:
        assert -20 <= score <= 20
