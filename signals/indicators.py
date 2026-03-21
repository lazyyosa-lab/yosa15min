"""
Indicators — computes all technical metrics from candle DataFrame.
All calculations work on pandas DataFrames for speed and clarity.
"""

import logging
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from config import Config

logger = logging.getLogger("indicators")


@dataclass
class IndicatorResult:
    # Raw values
    current_price: float
    current_atr: float
    avg_atr_20: float
    vwap: float
    ema9: float
    ema21: float
    macd_histogram_prev: float
    macd_histogram_curr: float
    volume_ratio: float
    body_ratio: float
    rsi8: float
    bb_width_curr: float
    bb_width_pct_rank: float   # 0.0 - 1.0, where it sits vs last 20 values

    # Derived signals (True = bullish bias)
    atr_expanded: bool
    vwap_signal: Optional[bool]     # True=UP, False=DOWN, None=no clear bias
    ema_signal: Optional[bool]
    ema_diverging: bool
    macd_signal: Optional[bool]
    macd_accelerating: bool
    volume_confirmed: bool
    body_committed: bool
    rsi_signal: Optional[bool]      # True=UP (>50), False=DOWN (<50), None=exactly 50
    bb_compressed: bool             # True = width below 85th percentile = breakout building

    # Directional vote (majority of 3 signal indicators)
    direction: str                  # "UP" or "DOWN"
    confidence: float               # 0.0 - 1.0


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_rsi(series: pd.Series, period: int = 8) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))


def compute_bb_width(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return (upper - lower) / mid  # normalized width


def compute_vwap(df: pd.DataFrame) -> float:
    """
    Anchored VWAP from the first candle in the DataFrame.
    For the 9:00 window use candles from 8:30 onward ideally,
    but last 50 candles gives a good rolling anchor.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    vwap = cum_tp_vol / cum_vol
    return float(vwap.iloc[-1])


def compute_indicators(df: pd.DataFrame) -> Optional[IndicatorResult]:
    """
    Run all indicators on the candle DataFrame.
    Returns None if not enough data.
    """
    if len(df) < 30:
        logger.warning(f"Not enough candles: {len(df)}")
        return None

    try:
        current = df.iloc[-1]
        current_price = float(current["close"])

        # ATR
        atr_series = compute_atr(df)
        current_atr = float(atr_series.iloc[-1])
        avg_atr_20 = float(atr_series.iloc[-21:-1].mean())
        atr_expanded = current_atr > avg_atr_20

        # VWAP
        vwap = compute_vwap(df)
        vwap_diff_pct = (current_price - vwap) / vwap
        if abs(vwap_diff_pct) < Config.VWAP_BAND_PCT:
            vwap_signal = None  # inside band — no clear bias
        else:
            vwap_signal = vwap_diff_pct > 0  # True = price above VWAP = UP bias

        # EMAs
        ema9_series = compute_ema(df["close"], 9)
        ema21_series = compute_ema(df["close"], 21)
        ema9 = float(ema9_series.iloc[-1])
        ema21 = float(ema21_series.iloc[-1])
        ema9_prev = float(ema9_series.iloc[-2])
        ema21_prev = float(ema21_series.iloc[-2])

        ema_gap_curr = ema9 - ema21
        ema_gap_prev = ema9_prev - ema21_prev
        ema_diverging = abs(ema_gap_curr) > abs(ema_gap_prev)

        if ema_gap_curr > 0:
            ema_signal = True   # EMA9 above EMA21 = UP
        elif ema_gap_curr < 0:
            ema_signal = False  # DOWN
        else:
            ema_signal = None

        # MACD
        _, _, histogram = compute_macd(df["close"])
        macd_histogram_curr = float(histogram.iloc[-1])
        macd_histogram_prev = float(histogram.iloc[-2])

        # Accelerating = same sign AND growing in magnitude
        same_sign = (macd_histogram_curr > 0) == (macd_histogram_prev > 0)
        growing = abs(macd_histogram_curr) > abs(macd_histogram_prev)
        macd_accelerating = same_sign and growing

        if macd_histogram_curr > 0:
            macd_signal = True
        elif macd_histogram_curr < 0:
            macd_signal = False
        else:
            macd_signal = None

        # Volume ratio
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        current_vol = float(current["volume"])
        volume_ratio = current_vol / vol_avg if vol_avg > 0 else 0
        volume_confirmed = volume_ratio >= Config.VOLUME_RATIO_MIN

        # Body ratio (candle commitment)
        body = abs(current["close"] - current["open"])
        full_range = current["high"] - current["low"]
        body_ratio = body / full_range if full_range > 0 else 0
        body_committed = body_ratio >= Config.BODY_RATIO_MIN

        # RSI(8)
        rsi_series = compute_rsi(df["close"], period=8)
        rsi8 = float(rsi_series.iloc[-1])
        if rsi8 > 50:
            rsi_signal = True
        elif rsi8 < 50:
            rsi_signal = False
        else:
            rsi_signal = None

        # BB width compression
        bb_width_series = compute_bb_width(df["close"])
        bb_width_curr = float(bb_width_series.iloc[-1])
        recent_widths = bb_width_series.iloc[-20:].dropna()
        if len(recent_widths) >= 5:
            bb_width_pct_rank = float((recent_widths < bb_width_curr).mean())
            bb_compressed = bb_width_pct_rank <= 0.85  # below 85th percentile = compressed
        else:
            bb_width_pct_rank = 0.5
            bb_compressed = False

        # Direction — majority vote of 5 signal indicators (was 3)
        signals = [s for s in [vwap_signal, ema_signal, macd_signal, rsi_signal] if s is not None]
        if not signals:
            direction = "UNCLEAR"
            confidence = 0.0
        else:
            up_votes = sum(1 for s in signals if s)
            down_votes = len(signals) - up_votes
            if up_votes == down_votes:
                direction = "UNCLEAR"   # genuine tie — no majority
                confidence = 0.5
            elif up_votes > down_votes:
                direction = "UP"
                confidence = up_votes / len(signals)
            else:
                direction = "DOWN"
                confidence = down_votes / len(signals)

        return IndicatorResult(
            current_price=current_price,
            current_atr=current_atr,
            avg_atr_20=avg_atr_20,
            vwap=vwap,
            ema9=ema9,
            ema21=ema21,
            macd_histogram_prev=macd_histogram_prev,
            macd_histogram_curr=macd_histogram_curr,
            volume_ratio=volume_ratio,
            body_ratio=body_ratio,
            rsi8=rsi8,
            bb_width_curr=bb_width_curr,
            bb_width_pct_rank=bb_width_pct_rank,
            atr_expanded=atr_expanded,
            vwap_signal=vwap_signal,
            ema_signal=ema_signal,
            ema_diverging=ema_diverging,
            macd_signal=macd_signal,
            macd_accelerating=macd_accelerating,
            volume_confirmed=volume_confirmed,
            body_committed=body_committed,
            rsi_signal=rsi_signal,
            bb_compressed=bb_compressed,
            direction=direction,
            confidence=confidence
        )

    except Exception as e:
        logger.error(f"Indicator computation failed: {e}", exc_info=True)
        return None
