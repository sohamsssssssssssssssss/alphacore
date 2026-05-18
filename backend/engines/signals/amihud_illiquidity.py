from __future__ import annotations

import numpy as np
import pandas as pd


class AmihudIlliquidity:
    def signal(self, returns: pd.Series, volume: pd.Series, window: int = 20) -> float:
        if returns is None or volume is None or len(returns) == 0 or len(volume) == 0:
            return 0.0
        n = min(len(returns), len(volume))
        r = returns.astype(float).iloc[-n:]
        v = volume.astype(float).iloc[-n:].replace(0.0, np.nan)
        ratio = (r.abs() / v).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        amihud = ratio.rolling(max(1, int(window)), min_periods=1).mean().iloc[-1]
        return float(amihud)
