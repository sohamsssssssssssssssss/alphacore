import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("reproduce", Path(__file__).parents[1] / "reproduce.py")
reproduce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reproduce)


def test_metric_values_selects_nested_actual_metrics():
    source = {"timestamp": 100, "arm_a": {"sharpe": 1.25, "ci": [-0.1, 2.0], "net_pnl": -10, "total_trades": 3, "returns": [1, 2], "reliable": True}}
    assert reproduce.metric_values(source) == {"arm_a.sharpe": 1.25, "arm_a.ci.0": -0.1, "arm_a.ci.1": 2.0, "arm_a.net_pnl": -10, "arm_a.total_trades": 3}


def test_missing_metric_is_not_a_match():
    assert reproduce.metric_values({"sharpe": 0.0}) != reproduce.metric_values({})


def test_all_attempts_remaining_targets_and_reports_failure(monkeypatch, tmp_path):
    calls = []
    names = ["fetch-data", "engine-build", "engine-test", "engine-bench", "tla", "py-test", "experiments"]
    def target(name):
        calls.append(name)
        return int(name == "tla")
    monkeypatch.setattr(reproduce, "SCRATCH", tmp_path)
    monkeypatch.setattr(reproduce, "TARGETS", {name: lambda name=name: target(name) for name in names})
    monkeypatch.setattr(reproduce.sys, "argv", ["reproduce.py", "all"])
    assert reproduce.main() == 1
    assert calls == names
