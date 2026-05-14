from engines.flow_engine import flow_engine


def test_flow_engine_has_compute_method():
    assert hasattr(flow_engine, "update") or hasattr(flow_engine, "get_current_flow")
