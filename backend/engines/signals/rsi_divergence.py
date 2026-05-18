from __future__ import annotations

import numpy as np
import pandas as pd


class RsiDivergence:
    def _rsi(self, price: pd.Series, rsi_period: int) -> pd.Series:
        delta = price.diff().fillna(0.0)
        gain = delta.clip(lower=0.0)
        loss = (-delta.clip(upper=0.0))
        avg_gain = gain.rolling(rsi_period, min_periods=1).mean()
        avg_loss = loss.rolling(rsi_period, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    def signal(self, price: pd.Series, rsi_period: int = 14) -> float:
        if price is None or len(price) < max(6, rsi_period + 2):
            return 0.0

        p = price.astype(float)
        rsi = self._rsi(p, int(rsi_period))
        lookback = min(len(p), 30)

        p_win = p.iloc[-lookback:]
        r_win = rsi.iloc[-lookback:]

        peak1_idx = p_win.iloc[:-1].idxmax()
        peak2_idx = p_win.iloc[1:].idxmax()
        trough1_idx = p_win.iloc[:-1].idxmin()
        trough2_idx = p_win.iloc[1:].idxmin()

        if p_win.loc[peak2_idx] > p_win.loc[peak1_idx] and r_win.loc[peak2_idx] < r_win.loc[peak1_idx]:
            return float(-abs(r_win.loc[peak1_idx] - r_win.loc[peak2_idx]) / 100.0)

        if p_win.loc[trough2_idx] < p_win.loc[trough1_idx] and r_win.loc[trough2_idx] > r_win.loc[trough1_idx]:
            return float(abs(r_win.loc[trough2_idx] - r_win.loc[trough1_idx]) / 100.0)

        return 0.0
