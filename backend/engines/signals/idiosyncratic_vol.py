from __future__ import annotations

import numpy as np
import pandas as pd


class IdiosyncraticVol:
    def signal(self, stock_returns: pd.Series, market_returns: pd.Series, window: int = 20) -> float:
        if stock_returns is None or market_returns is None:
            return 0.0
        n = min(len(stock_returns), len(market_returns), max(2, int(window)))
        if n < 2:
            return 0.0

        y = stock_returns.astype(float).iloc[-n:].to_numpy()
        x = market_returns.astype(float).iloc[-n:].to_numpy()
        x_mean = float(np.mean(x))
        y_mean = float(np.mean(y))
        var_x = float(np.var(x))
        beta = 0.0 if var_x == 0.0 else float(np.cov(x, y, bias=True)[0, 1] / var_x)
        alpha = y_mean - beta * x_mean
        residuals = y - (alpha + beta * x)
        return float(np.std(residuals))
