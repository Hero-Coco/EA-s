"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - SMC Detection Engine
=============================================================================
Detailed Smart Money Concepts (SMC) implementation (4/4 A-Grade Setup):
1. Swing High & Swing Low identification over rolling lookback (20 candles)
2. Liquidity Sweep Detection (wick breaks swing extreme, closes back inside)
3. Market Structure Shift (MSS) confirmation
4. Fair Value Gap (FVG) calculation (3-candle imbalance with min size filter)
5. Fibonacci Golden Pocket (0.50 - 0.786) Retracement Filter
6. FVG Mitigation & Engulfing Candlestick Trigger
=============================================================================
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
import pandas as pd
import numpy as np

import config


@dataclass
class FVGZone:
    """Represents a 3-candle Fair Value Gap."""
    direction: str       # "BULLISH" or "BEARISH"
    top: float           # Upper boundary of imbalance
    bottom: float        # Lower boundary of imbalance
    size: float          # top - bottom
    formed_bar_idx: int  # Bar index where FVG formed
    mitigated: bool = False


@dataclass
class SMCCandidate:
    """Tracks the state machine lifecycle of an active SMC setup."""
    direction: str            # "BUY" or "SELL"
    sweep_bar_idx: int
    sweep_level: float        # Swing low that was swept (for BUY) or swing high (for SELL)
    target_mss_level: float   # Level price must break to confirm MSS
    mss_confirmed: bool = False
    mss_bar_idx: Optional[int] = None
    fvg: Optional[FVGZone] = None
    fvg_mitigated: bool = False
    take_profit: float = 0.0
    stop_loss: float = 0.0


def calculate_swings(df: pd.DataFrame, lookback: int = config.SWING_LOOKBACK) -> Tuple[pd.Series, pd.Series]:
    """
    Computes rolling swing high and swing low series for the past N candles.
    Uses rolling window excluding the current candle.
    """
    swing_high = df['high'].shift(1).rolling(window=lookback).max()
    swing_low = df['low'].shift(1).rolling(window=lookback).min()
    return swing_high, swing_low


def detect_liquidity_sweep(
    df: pd.DataFrame,
    idx: int,
    swing_high: float,
    swing_low: float
) -> Optional[Tuple[str, float]]:
    """
    Concept 1: Liquidity Sweep Detection
    - Bullish Sweep: Price breaks below recent swing low and closes back above it.
    - Bearish Sweep: Price breaks above recent swing high and closes back below it.
    """
    candle = df.iloc[idx]
    c_high = candle['high']
    c_low = candle['low']
    c_close = candle['close']

    # Bullish Liquidity Sweep (Swept Sell-Side Liquidity)
    if c_low < swing_low and c_close > swing_low:
        return "BULLISH", swing_low

    # Bearish Liquidity Sweep (Swept Buy-Side Liquidity)
    if c_high > swing_high and c_close < swing_high:
        return "BEARISH", swing_high

    return None


def detect_fvg_at_bar(
    df: pd.DataFrame,
    idx: int,
    min_size_points: float = 10.0
) -> Optional[FVGZone]:
    """
    Concept 3: 3-Candle Fair Value Gap (FVG) Detection
    - Bullish FVG: Low of candle 3 (idx) > High of candle 1 (idx-2)
      Imbalance zone = [High of candle 1, Low of candle 3]
    - Bearish FVG: High of candle 3 (idx) < Low of candle 1 (idx-2)
      Imbalance zone = [High of candle 3, Low of candle 1]
    """
    if idx < 2:
        return None

    c1 = df.iloc[idx - 2]
    c3 = df.iloc[idx]

    # Bullish FVG
    if c3['low'] > c1['high']:
        gap_size = c3['low'] - c1['high']
        if gap_size >= min_size_points:
            return FVGZone(
                direction="BULLISH",
                top=c3['low'],
                bottom=c1['high'],
                size=gap_size,
                formed_bar_idx=idx
            )

    # Bearish FVG
    elif c3['high'] < c1['low']:
        gap_size = c1['low'] - c3['high']
        if gap_size >= min_size_points:
            return FVGZone(
                direction="BEARISH",
                top=c1['low'],
                bottom=c3['high'],
                size=gap_size,
                formed_bar_idx=idx
            )

    return None


def is_in_fib_golden_pocket(
    direction: str,
    price: float,
    origin_level: float,
    impulse_extreme: float,
    min_fib: float = 0.50,
    max_fib: float = 0.786
) -> bool:
    """
    Concept 4 (from Video): Fibonacci Golden Pocket Retracement
    Ensures trade is taken at a DISCOUNT (for Buy) or PREMIUM (for Sell),
    rather than buying at expensive prices above 0.50.

    - For BUY:
      Leg from origin_level (low) to impulse_extreme (high).
      Retracement distance = impulse_extreme - price.
      Ratio = (impulse_extreme - price) / (impulse_extreme - origin_level).
      Must be >= 0.50 (i.e. at or below the 50% equilibrium line).

    - For SELL:
      Leg from origin_level (high) to impulse_extreme (low).
      Retracement distance = price - impulse_extreme.
      Ratio = (price - impulse_extreme) / (origin_level - impulse_extreme).
      Must be >= 0.50 (i.e. at or above the 50% equilibrium line).
    """
    total_range = abs(impulse_extreme - origin_level)
    if total_range <= 0:
        return False

    if direction.upper() == "BUY":
        retrace = impulse_extreme - price
        ratio = retrace / total_range
        return min_fib <= ratio <= max_fib

    elif direction.upper() == "SELL":
        retrace = price - impulse_extreme
        ratio = retrace / total_range
        return min_fib <= ratio <= max_fib

    return False


def is_engulfing_inside_fvg(
    df: pd.DataFrame,
    idx: int,
    fvg: FVGZone
) -> bool:
    """
    Concept 3 Entry Trigger:
    Detects if current candle is an engulfing candle inside the FVG zone.
    - Bullish Engulfing inside Bullish FVG:
      * Current candle green (close > open)
      * Low or Open dips into or touches FVG zone
      * Bullish body completely engulfs previous candle body
    - Bearish Engulfing inside Bearish FVG:
      * Current candle red (close < open)
      * High or Open touches FVG zone
      * Bearish body completely engulfs previous candle body
    """
    if idx < 1:
        return False

    curr = df.iloc[idx]
    prev = df.iloc[idx - 1]

    # Check if current candle touches or is within FVG zone
    touches_fvg = not (curr['low'] > fvg.top or curr['high'] < fvg.bottom)
    if not touches_fvg:
        return False

    if fvg.direction == "BULLISH":
        if curr['close'] > curr['open']:
            curr_body = curr['close'] - curr['open']
            prev_body = abs(prev['close'] - prev['open'])
            if curr['close'] >= max(prev['open'], prev['close']) and curr_body >= prev_body:
                return True

    elif fvg.direction == "BEARISH":
        if curr['close'] < curr['open']:
            curr_body = curr['open'] - curr['close']
            prev_body = abs(prev['close'] - prev['open'])
            if curr['close'] <= min(prev['open'], prev['close']) and curr_body >= prev_body:
                return True

    return False
