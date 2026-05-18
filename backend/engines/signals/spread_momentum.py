from __future__ import annotations

import pandas as pd


class SpreadMomentum:
    def signal(self, spread_series: pd.Series, window: int = 10) -> float:
        if spread_series is None or len(spread_series) < 2:
            return 0.0
        s = spread_series.astype(float)
        w = max(1, int(window))
        if len(s) <= w:
            change = float(s.iloc[-1] - s.iloc[0])
        else:
            change = float(s.iloc[-1] - s.iloc[-1 - w])
        return float(-change)
