from __future__ import annotations

import pandas as pd


class VolumeSurge:
    def signal(self, volume_series: pd.Series, window: int = 20) -> float:
        if volume_series is None or len(volume_series) == 0:
            return 0.0
        s = volume_series.astype(float)
        w = max(1, int(window))
        rolling_mean = float(s.rolling(w, min_periods=1).mean().iloc[-1])
        current = float(s.iloc[-1])
        if rolling_mean == 0.0:
            return 0.0
        ratio = current / rolling_mean
        return float(ratio - 1.0)
