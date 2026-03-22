"""
Filters — runs the full checklist against indicator results and
Polymarket mispricing. Returns a FilterResult with pass/fail per filter.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from config import Config
from signals.indicators import IndicatorResult

logger = logging.getLogger("filters")


@dataclass
class FilterResult:
    # Individual filter outcomes
    atr_expanded: bool = False
    vwap_clear: bool = False
    ema_aligned: bool = False
    ema_diverging: bool = False
    macd_accelerating: bool = False
    volume_confirmed: bool = False
    body_committed: bool = False
    chainlink_spread_ok: bool = False
    rsi_signal: bool = False
    bb_compressed: bool = False
    polymarket_mispriced: bool = False

    # Mispricing detail
    model_prob: float = 0.0
    market_prob: float = 0.0
    edge: float = 0.0

    # Summary
    filters_passed: int = 0
    filters_total: int = 10  # 8 original + RSI + BB
    failed_reasons: list = field(default_factory=list)

    # Final decision
    is_priority_window: bool = False
    signal: bool = False
    signal_tier: str = "SKIP"       # STRONG_TRADE, TRADE, or SKIP
    direction: str = "UNCLEAR"
    size_pct: float = 0.0


def run_filters(
    indicators: IndicatorResult,
    yes_price: float,           # Polymarket UP price (0.0 - 1.0)
    chainlink_spread_ok: bool,
    chainlink_spread: float,
    is_priority_window: bool
) -> FilterResult:
    """
    Runs all 8 filters. Tier 1 (priority) needs 6/8. Tier 3 needs 8/8.
    """
    result = FilterResult(is_priority_window=is_priority_window)
    failed = []

    # ── 1. ATR expanded ─────────────────────────────────────────────────
    result.atr_expanded = indicators.atr_expanded
    if not result.atr_expanded:
        failed.append(f"ATR flat ({indicators.current_atr:.1f} ≤ avg {indicators.avg_atr_20:.1f})")

    # ── 2. VWAP clear bias ──────────────────────────────────────────────
    result.vwap_clear = indicators.vwap_signal is not None
    if not result.vwap_clear:
        vwap_diff = abs(indicators.current_price - indicators.vwap) / indicators.vwap
        failed.append(f"Price inside VWAP band ({vwap_diff:.3%})")

    # ── 3. EMA aligned ──────────────────────────────────────────────────
    result.ema_aligned = (
        indicators.ema_signal is not None and
        indicators.vwap_signal == indicators.ema_signal  # must agree with VWAP bias
    )
    if not result.ema_aligned:
        failed.append(
            f"EMA not aligned with VWAP "
            f"(EMA9={indicators.ema9:.0f} EMA21={indicators.ema21:.0f})"
        )

    # ── 4. EMA diverging ────────────────────────────────────────────────
    result.ema_diverging = indicators.ema_diverging
    if not result.ema_diverging:
        failed.append("EMA gap converging (momentum fading)")

    # ── 5. MACD accelerating ────────────────────────────────────────────
    result.macd_accelerating = indicators.macd_accelerating
    if not result.macd_accelerating:
        failed.append(
            f"MACD histogram not accelerating "
            f"(prev={indicators.macd_histogram_prev:.4f} "
            f"curr={indicators.macd_histogram_curr:.4f})"
        )

    # ── 6. Volume confirmed ─────────────────────────────────────────────
    result.volume_confirmed = indicators.volume_confirmed
    if not result.volume_confirmed:
        failed.append(f"Volume weak ({indicators.volume_ratio:.2f}x avg, need ≥1.3x)")

    # ── 7. Body committed ───────────────────────────────────────────────
    result.body_committed = indicators.body_committed
    if not result.body_committed:
        failed.append(f"Candle indecision (body ratio {indicators.body_ratio:.2f}, need ≥0.6)")

    # ── 8. Chainlink spread OK ──────────────────────────────────────────
    result.chainlink_spread_ok = chainlink_spread_ok
    if not result.chainlink_spread_ok:
        failed.append(f"Chainlink divergence too high ({chainlink_spread:.3%})")

    # ── 9. RSI(8) aligned with direction ───────────────────────────────
    result.rsi_signal = indicators.rsi_signal is not None
    if result.rsi_signal:
        # Must agree with the majority direction vote
        rsi_matches = (
            (indicators.direction == "UP" and indicators.rsi_signal is True) or
            (indicators.direction == "DOWN" and indicators.rsi_signal is False)
        )
        result.rsi_signal = rsi_matches
    if not result.rsi_signal:
        failed.append(f"RSI(8) conflicting ({indicators.rsi8:.1f}, direction={indicators.direction})")

    # ── 10. BB width compressed ─────────────────────────────────────────
    result.bb_compressed = indicators.bb_compressed
    if not result.bb_compressed:
        failed.append(
            f"BB not compressed (width rank {indicators.bb_width_pct_rank:.0%}, need ≤85%)"
        )

    # ── Count passes ────────────────────────────────────────────────────
    passed = sum([
        result.atr_expanded,
        result.vwap_clear,
        result.ema_aligned,
        result.ema_diverging,
        result.macd_accelerating,
        result.volume_confirmed,
        result.body_committed,
        result.chainlink_spread_ok,
        result.rsi_signal,
        result.bb_compressed,
    ])
    result.filters_passed = passed
    result.failed_reasons = failed

    # ── Mispricing check ────────────────────────────────────────────────
    direction = indicators.direction
    confidence = indicators.confidence  # 0.0 - 1.0

    # Model probability = confidence of directional signal
    # If UP: model_prob = confidence (prob of UP resolving)
    # If DOWN: model_prob = confidence (prob of DOWN resolving) → compare against no_price
    if direction == "UP":
        model_prob = 0.5 + (confidence - 0.5) * 0.7  # scale to reasonable range
        market_prob = yes_price
    elif direction == "DOWN":
        model_prob = 0.5 + (confidence - 0.5) * 0.7
        market_prob = 1 - yes_price  # DOWN = NO price
    else:
        model_prob = 0.5
        market_prob = yes_price

    edge = model_prob - market_prob
    result.model_prob = round(model_prob, 4)
    result.market_prob = round(market_prob, 4)
    result.edge = round(edge, 4)
    result.polymarket_mispriced = edge >= Config.EDGE_THRESHOLD

    if not result.polymarket_mispriced:
        failed.append(
            f"No mispricing (model={model_prob:.0%} market={market_prob:.0%} "
            f"edge={edge:.0%} < {Config.EDGE_THRESHOLD:.0%})"
        )

    # ── Final decision ───────────────────────────────────────────────────
    min_filters = (
        Config.TIER_1_MIN_FILTERS if is_priority_window
        else Config.TIER_3_MIN_FILTERS
    )
    technical_ok = passed >= min_filters

    # ── Tiered signal system ─────────────────────────────────────────────
    # STRONG_TRADE: edge > 30% — never miss these regardless of filters
    # TRADE:        edge > 15% + 6/10 filters passed
    # SKIP:         everything else

    if edge >= 0.30 and direction != "UNCLEAR":
        signal_tier = "STRONG_TRADE"
        result.signal = True
    elif edge >= 0.15 and passed >= 6 and direction != "UNCLEAR":
        signal_tier = "TRADE"
        result.signal = True
    elif technical_ok and result.polymarket_mispriced and direction != "UNCLEAR":
        signal_tier = "TRADE"
        result.signal = True
    else:
        signal_tier = "SKIP"
        result.signal = False

    result.direction = direction
    result.signal_tier = signal_tier
    result.size_pct = (
        Config.TIER_1_SIZE_PCT if is_priority_window
        else Config.TIER_3_SIZE_PCT
    )

    # Reduce size for non-strong signals
    if signal_tier == "TRADE" and not is_priority_window:
        result.size_pct = result.size_pct * 0.75  # 4.5% instead of 6%

    logger.info(
        f"Filters: {passed}/10 passed | edge={edge:.2%} | "
        f"tier={signal_tier} | dir={direction}"
    )

    return result
