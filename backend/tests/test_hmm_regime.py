import numpy as np
import pandas as pd

from engines.marl.hmm_regime import HmmRegimeDetector


def _synthetic_df(n: int = 1000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for i in range(n):
        block = (i // 200) % 2
        if block == 0:
            rows.append(
                {
                    "flow_imbalance": rng.normal(0.8, 0.1),
                    "spread_bps": rng.normal(4.0, 0.5),
                    "realized_vol": rng.normal(0.8, 0.1),
                    "iceberg_count": rng.normal(5.0, 1.0),
                    "spoof_score": rng.normal(20.0, 5.0),
                }
            )
        else:
            rows.append(
                {
                    "flow_imbalance": rng.normal(0.1, 0.1),
                    "spread_bps": rng.normal(10.0, 0.8),
                    "realized_vol": rng.normal(2.0, 0.2),
                    "iceberg_count": rng.normal(1.0, 0.5),
                    "spoof_score": rng.normal(60.0, 8.0),
                }
            )
    return pd.DataFrame(rows)


def test_predict_length_1000():
    df = _synthetic_df(1000)
    det = HmmRegimeDetector(n_states=4)
    det.fit(df)
    states = det.predict(df)
    assert len(states) == 1000


def test_predicted_states_in_range():
    df = _synthetic_df(1000)
    det = HmmRegimeDetector(n_states=4)
    det.fit(df)
    states = det.predict(df)
    assert np.all((states >= 0) & (states <= 3))


def test_label_states_has_4_keys():
    df = _synthetic_df(1000)
    det = HmmRegimeDetector(n_states=4)
    det.fit(df)
    labels = det.label_states(df)
    assert isinstance(labels, dict)
    assert set(labels.keys()) == {0, 1, 2, 3}


def test_get_current_regime_returns_string():
    df = _synthetic_df(1000)
    det = HmmRegimeDetector(n_states=4)
    det.fit(df)
    regime = det.get_current_regime(df.iloc[-1])
    assert isinstance(regime, str)
