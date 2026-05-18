import numpy as np

from engines.marl.nsga2_optimizer import Nsga2Optimizer


def test_nsga2_optimizer_outputs_valid_pareto_df():
    rng = np.random.default_rng(123)
    n_signals = 11
    n_periods = 252

    returns_matrix = rng.normal(0.0005, 0.01, size=(n_signals, n_periods))
    signal_names = [f"signal_{i+1}" for i in range(n_signals)]

    opt = Nsga2Optimizer(signal_names=signal_names, population_size=10, n_generations=5)
    pareto_df = opt.run(returns_matrix)

    assert "sharpe" in pareto_df.columns
    assert "max_drawdown" in pareto_df.columns

    weight_cols = [f"weight_{name}" for name in signal_names]
    sums = pareto_df[weight_cols].sum(axis=1).to_numpy()
    assert np.all(np.abs(sums - 1.0) <= 1e-6)

    assert not pareto_df["sharpe"].isna().any()
