from hypothesis import given
from hypothesis import strategies as st


@given(st.floats(min_value=0, max_value=1_000_000))
def test_iceberg_non_negative_volume(volume):
    assert volume >= 0
