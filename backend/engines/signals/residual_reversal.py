from __future__ import annotations

import numpy as np
import pandas as pd


class ResidualReversal:
    def signal(self, stock_returns: pd.Series, market_returns: pd.Series, lookback: int = 5) -> float:
        if stock_returns is None or market_returns is None:
            return 0.0
        lb = max(2, int(lookback))
        n = min(len(stock_returns), len(market_returns), lb)
        if n < 2:
            return 0.0

        y = stock_returns.astype(float).iloc[-n:].to_numpy()
        x = market_returns.astype(float).iloc[-n:].to_numpy()
        var_x = float(np.var(x))
        beta = 0.0 if var_x == 0.0 else float(np.cov(x, y, bias=True)[0, 1] / var_x)
        residual = y - beta * x
        residual_return = float(np.sum(residual))
        return float(-residual_return)
