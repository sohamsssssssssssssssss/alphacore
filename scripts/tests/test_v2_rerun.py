import importlib.util
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('rerun_v2', Path(__file__).parents[1] / 'rerun_v2.py')
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)


def test_v2_metric_pair_has_matching_rf_and_preserves_seed():
    returns = [.012, -.008, .025, -.017, .006, .019, -.004, .031, -.013, .008]
    point, ci = v2.consistent_metrics(returns, 12, 100, 3, 17)
    assert ci['sharpe'] == pytest.approx(point, rel=1e-14)
    assert ci['n_bootstrap'] == 100
    assert point == pytest.approx(v2.compute_sharpe(returns, periods_per_year=12, risk_free=.065), rel=1e-14)


def test_holdout_keeps_calendar_cut_instead_of_revised_row_count():
    panel = v2.pd.DataFrame({'value': [1, 2, 3]}, index=v2.pd.to_datetime(['2025-01-30', '2025-01-31', '2025-02-03']))
    assert list(v2.held_out(panel).index) == list(panel.index[1:])


@pytest.mark.parametrize('artifact', sorted((v2.ROOT / 'research/v2').glob('*.json')), ids=lambda p: p.stem)
def test_committed_v2_numbers_recompute_from_their_raw_returns(artifact):
    import json
    record = json.loads(artifact.read_text())
    if 'returns' not in record:
        assert record['status'] == 'not reproducible: source data no longer obtainable'
        return
    params = record['metric_definition']
    assert params['annual_risk_free'] == .065
    point, ci = v2.consistent_metrics(record['returns'], params['periods_per_year'],
                                     params['n_bootstrap'], params['mean_block_length'], params['seed'])
    assert point == pytest.approx(record['v2_sharpe'], rel=1e-12, abs=1e-12)
    assert [ci['ci_lower'], ci['ci_upper']] == pytest.approx(record['v2_ci'], rel=1e-12, abs=1e-12)
    assert params['zero_rf_annual_risk_free'] == 0.0
    point0, ci0 = v2.consistent_metrics(record['returns'], params['periods_per_year'], params['n_bootstrap'],
                                       params['mean_block_length'], params['seed'], risk_free=0.0)
    assert point0 == pytest.approx(record['v2_sharpe_zero_rf'], rel=1e-12, abs=1e-12)
    assert [ci0['ci_lower'], ci0['ci_upper']] == pytest.approx(record['v2_ci_zero_rf'], rel=1e-12, abs=1e-12)
    primary_ci = record['v2_ci_zero_rf'] if record['primary_convention'] == v2.ZERO_RF else record['v2_ci']
    assert record['primary_convention'] == (v2.EXCESS if artifact.stem == 'k12_basket' else v2.ZERO_RF)
    assert record['primary_positive_ci'] == (primary_ci[0] > 0)
    assert record['deployed_fraction']['code']


def test_zero_rf_differs_from_excess_only_by_rf():
    returns = [.012, -.008, .025, -.017, .006, .019, -.004, .031, -.013, .008]
    point0, ci0 = v2.consistent_metrics(returns, 12, 100, 3, 17, risk_free=0.0)
    assert ci0['sharpe'] == pytest.approx(point0, rel=1e-14)
    assert point0 > v2.consistent_metrics(returns, 12, 100, 3, 17)[0]
