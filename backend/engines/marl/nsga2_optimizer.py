from __future__ import annotations

import numpy as np
import pandas as pd

from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.optimize import minimize


def max_drawdown(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peaks = np.maximum.accumulate(equity)
    dd = (peaks - equity) / np.where(peaks == 0.0, 1.0, peaks)
    return float(np.max(dd)) if dd.size else 0.0


def sharpe(returns: np.ndarray, ann_factor: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    s = float(np.std(r))
    if s == 0.0:
        return 0.0
    return float(np.mean(r) / s * np.sqrt(float(ann_factor)))


class _WeightProblem(Problem):
    def __init__(self, optimizer: "Nsga2Optimizer", returns_matrix: np.ndarray):
        self.optimizer = optimizer
        self.returns_matrix = returns_matrix
        n_vars = len(optimizer.signal_names)
        super().__init__(n_var=n_vars, n_obj=2, n_constr=0, xl=0.0, xu=1.0)

    def _evaluate(self, X, out, *args, **kwargs):
        F = np.zeros((X.shape[0], 2), dtype=float)
        for i in range(X.shape[0]):
            w = np.asarray(X[i], dtype=float)
            s = np.sum(w)
            if s <= 0:
                w = np.ones_like(w) / len(w)
            else:
                w = w / s
            f1, f2 = self.optimizer._evaluate(w, self.returns_matrix)
            F[i, 0] = f1
            F[i, 1] = f2
        out["F"] = F


class Nsga2Optimizer:
    def __init__(self, signal_names: list[str], population_size: int = 50, n_generations: int = 100):
        self.signal_names = signal_names
        self.population_size = int(population_size)
        self.n_generations = int(n_generations)

    def _evaluate(self, weights: np.ndarray, returns_matrix: np.ndarray) -> tuple[float, float]:
        w = np.asarray(weights, dtype=float)
        s = float(np.sum(w))
        if s <= 0.0:
            w = np.ones_like(w) / len(w)
        else:
            w = w / s
        combined_returns = np.asarray(w @ returns_matrix, dtype=float)
        sratio = sharpe(combined_returns)
        mdd = max_drawdown(combined_returns)
        return float(-sratio), float(mdd)

    def run(self, returns_matrix: np.ndarray) -> pd.DataFrame:
        rm = np.asarray(returns_matrix, dtype=float)
        if rm.ndim != 2:
            raise ValueError("returns_matrix must be 2D")
        if rm.shape[0] != len(self.signal_names):
            raise ValueError("returns_matrix first dimension must match number of signals")

        problem = _WeightProblem(self, rm)
        algo = NSGA2(pop_size=self.population_size)
        res = minimize(problem, algo, ("n_gen", self.n_generations), seed=42, verbose=False)

        X = np.asarray(res.X, dtype=float)
        F = np.asarray(res.F, dtype=float)
        if X.ndim == 1:
            X = X.reshape(1, -1)
            F = F.reshape(1, -1)

        rows = []
        for i in range(X.shape[0]):
            w = X[i]
            s = float(np.sum(w))
            w = w / s if s > 0 else np.ones_like(w) / len(w)

            row = {f"weight_{name}": float(w[j]) for j, name in enumerate(self.signal_names)}
            row["sharpe"] = float(-F[i, 0])
            row["max_drawdown"] = float(F[i, 1])
            rows.append(row)

        return pd.DataFrame(rows)

    def plot_pareto(self, pareto_df: pd.DataFrame) -> None:
        if pareto_df.empty:
            print("(empty pareto front)")
            return

        s = pareto_df["sharpe"].to_numpy(dtype=float)
        d = pareto_df["max_drawdown"].to_numpy(dtype=float)

        s_min, s_max = float(np.min(s)), float(np.max(s))
        d_min, d_max = float(np.min(d)), float(np.max(d))
        width = 40

        print("Pareto Front (Sharpe vs Max Drawdown)")
        for i in range(len(pareto_df)):
            s_norm = 0.0 if s_max == s_min else (s[i] - s_min) / (s_max - s_min)
            d_norm = 0.0 if d_max == d_min else (d[i] - d_min) / (d_max - d_min)
            pos = int(round(s_norm * (width - 1)))
            line = [" "] * width
            line[pos] = "*"
            print(f"{''.join(line)} | sharpe={s[i]:.4f} mdd={d[i]:.4f} d_norm={d_norm:.2f}")
