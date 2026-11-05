"""
=============================================================================
MAPSAR-Trend Bot v1.0 - Strategy & Parabolic SAR Trailing Engine
=============================================================================
Ported from MQL5 ExpertMAPSAR.mq5 (Magic 14598):
- Signal: 12 SMA (Shift=6)
- Trailing Stop: Parabolic SAR (Step=0.02, Maximum=0.2)
=============================================================================
"""

import logging
import math
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

import config
from mt5_manager import MT5Manager


def calculate_parabolic_sar(
    df: pd.DataFrame,
    step: float = config.SAR_STEP,
    maximum: float = config.SAR_MAXIMUM
) -> pd.Series:
    """Calculates Welles Wilder's Parabolic SAR matching MetaTrader 5 indicator."""
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    sar = np.zeros(n)

    if n < 3:
        return pd.Series(sar, index=df.index)

    # Initial direction based on first 2 bars
    is_bull = highs[1] >= highs[0]
    af = step
    ep = highs[1] if is_bull else lows[1]
    sar[0] = lows[0] if is_bull else highs[0]
    sar[1] = lows[0] if is_bull else highs[0]

    for i in range(2, n):
        prev_sar = sar[i - 1]

        if is_bull:
            curr_sar = prev_sar + af * (ep - prev_sar)
            # Rule: Bull SAR cannot be higher than low of previous 2 bars
            curr_sar = min(curr_sar, lows[i - 1], lows[i - 2])

            if lows[i] < curr_sar:
                # Reverse to Bear
                is_bull = False
                curr_sar = ep
                af = step
                ep = lows[i]
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + step, maximum)

        else:  # Bearish
            curr_sar = prev_sar + af * (ep - prev_sar)
            # Rule: Bear SAR cannot be lower than high of previous 2 bars
            curr_sar = max(curr_sar, highs[i - 1], highs[i - 2])

            if highs[i] > curr_sar:
                # Reverse to Bull
                is_bull = True
                curr_sar = ep
                af = step
                ep = highs[i]
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + step, maximum)

        sar[i] = curr_sar

    return pd.Series(sar, index=df.index)


class MAPSARStrategy:
    """12 SMA Shift=6 entry with Parabolic SAR trailing stop."""

    def __init__(
        self,
        target_name: str,
        mt5_mgr: MT5Manager,
        logger: Optional[logging.Logger] = None
    ):
        self.target_name = target_name
        self.mt5_mgr = mt5_mgr
        self.logger = logger or logging.getLogger("MAPSAR")
        self.profile = config.TARGET_PROFILES[target_name]
        self.symbol: Optional[str] = None
        self.magic_number = self.profile["magic_number"]
        self.timeframe = self.profile["timeframe"]
        self.last_processed_candle_time: Optional[pd.Timestamp] = None

    def initialize(self) -> bool:
        self.symbol = self.mt5_mgr.resolve_symbol(self.target_name)
        return self.symbol is not None

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # 12 SMA Shift=6
        df['signal_ma'] = df['close'].rolling(window=config.SIGNAL_MA_PERIOD).mean().shift(config.SIGNAL_MA_SHIFT)
        # Parabolic SAR
        df['sar'] = calculate_parabolic_sar(df, step=config.SAR_STEP, maximum=config.SAR_MAXIMUM)
        return df

    def evaluate_signals(self, df: pd.DataFrame) -> Tuple[Optional[str], float, float]:
        if len(df) < config.SIGNAL_MA_PERIOD + config.SIGNAL_MA_SHIFT + 5:
            return None, 0.0, 0.0

        df_ind = self.calculate_indicators(df)
        bar1 = df_ind.iloc[-2]
        bar2 = df_ind.iloc[-3]

        c1, c2 = bar1['close'], bar2['close']
        s_ma1, s_ma2 = bar1['signal_ma'], bar2['signal_ma']
        sar1 = bar1['sar']

        if pd.isna(s_ma1) or pd.isna(s_ma2) or pd.isna(sar1):
            return None, 0.0, 0.0

        signal = None
        if c2 <= s_ma2 and c1 > s_ma1:
            signal = "BUY"
        elif c2 >= s_ma2 and c1 < s_ma1:
            signal = "SELL"

        return signal, float(s_ma1), float(sar1)

    def manage_trailing_stop(self, position: Any, df: pd.DataFrame) -> None:
        """
        Manages Trailing Stop based on user rules:
        - Initial SL = Fixed 2.5% of entry price (Risk distance R = entry_price * 0.025)
        - Starts trailing when trade reaches 1:1 R:R (profit >= 1.0 * R)
        - At 1:1 R:R -> SL moves to Break-Even (entry_price)
        - For every 0.5 R of further favorable move -> SL moves up by 0.5 R
        """
        info = self.mt5_mgr.get_symbol_info(self.symbol)
        if not info:
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return

        digits = info.digits
        point = info.point
        stops_level = info.trade_stops_level * point

        pos_type = position.type
        pos_sl = position.sl
        pos_open = position.price_open
        ticket = position.ticket

        # 1. Calculate Risk Distance R (2.5% of entry open price)
        r = pos_open * (config.INITIAL_SL_PERCENT / 100.0)
        trail_start_dist = config.TRAIL_START_R * r
        trail_step_dist = config.TRAIL_STEP_R * r

        if pos_type == 0:  # ORDER_TYPE_BUY
            profit = tick.bid - pos_open
            # Check if trade reached at least 1:1 R:R
            if profit >= trail_start_dist:
                n_steps = math.floor((profit - trail_start_dist) / trail_step_dist)
                target_sl = round(pos_open + (n_steps * trail_step_dist), digits)
                level = tick.bid - stops_level

                if target_sl > pos_sl and target_sl < level:
                    rr_ratio = profit / r
                    self.logger.info(
                        f"[{self.target_name}] 1:1+ R:R Trailing Stop BUY #{ticket} (R:R {rr_ratio:.2f}): "
                        f"Old SL: {pos_sl:.{digits}f} -> New SL: {target_sl:.{digits}f} (Bid: {tick.bid})"
                    )
                    self.mt5_mgr.modify_position_sltp(ticket, self.symbol, sl=target_sl, tp=position.tp)

        elif pos_type == 1:  # ORDER_TYPE_SELL
            profit = pos_open - tick.ask
            # Check if trade reached at least 1:1 R:R
            if profit >= trail_start_dist:
                n_steps = math.floor((profit - trail_start_dist) / trail_step_dist)
                target_sl = round(pos_open - (n_steps * trail_step_dist), digits)
                level = tick.ask + stops_level

                if (pos_sl == 0.0 or target_sl < pos_sl) and target_sl > level:
                    rr_ratio = profit / r
                    self.logger.info(
                        f"[{self.target_name}] 1:1+ R:R Trailing Stop SELL #{ticket} (R:R {rr_ratio:.2f}): "
                        f"Old SL: {pos_sl:.{digits}f} -> New SL: {target_sl:.{digits}f} (Ask: {tick.ask})"
                    )
                    self.mt5_mgr.modify_position_sltp(ticket, self.symbol, sl=target_sl, tp=position.tp)

    def on_candle_close(self, df: pd.DataFrame) -> None:
        completed_candle_time = df['time'].iloc[-2]
        signal, s_ma1, sar1 = self.evaluate_signals(df)
        active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)

        # 1. Update trailing stops for active positions first
        for pos in active_positions:
            self.manage_trailing_stop(pos, df)

        # 2. Check for new trade or reversal signal
        if signal is not None:
            self.logger.info(
                f"[{self.target_name}] New Signal: {signal} at {completed_candle_time} | "
                f"Shifted 12 SMA: {s_ma1:.2f} | Parabolic SAR: {sar1:.2f}"
            )

            # Reversal
            for pos in active_positions:
                is_buy = (pos.type == 0)
                if (signal == "BUY" and not is_buy) or (signal == "SELL" and is_buy):
                    self.logger.info(f"[{self.target_name}] Signal reversal: Closing #{pos.ticket} before opening {signal}")
                    self.mt5_mgr.close_position(pos)

            active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
            already_open = any(
                (pos.type == 0 and signal == "BUY") or (pos.type == 1 and signal == "SELL")
                for pos in active_positions
            )

            if not already_open:
                tick = mt5.symbol_info_tick(self.symbol)
                current_price = tick.ask if signal == "BUY" else tick.bid

                # Fixed 2.5% initial Stop Loss (Risk unit R = entry_price * 0.025)
                r_dist = current_price * (config.INITIAL_SL_PERCENT / 100.0)
                initial_sl = (current_price - r_dist) if signal == "BUY" else (current_price + r_dist)

                lot = self.mt5_mgr.calculate_lot_size(
                    symbol=self.symbol,
                    sl_distance_price=r_dist,
                    target_key=self.target_name
                )

                self.logger.info(
                    f"[{self.target_name}] Executing {signal} | Lot: {lot} | "
                    f"Entry: {current_price:.2f} | Fixed 2.5% Initial SL: {initial_sl:.2f} (R: {r_dist:.2f}) | Magic: {self.magic_number}"
                )
                self.mt5_mgr.open_position(
                    symbol=self.symbol,
                    order_type=signal,
                    volume=lot,
                    sl=initial_sl,
                    tp=0.0,
                    magic=self.magic_number,
                    comment="ExpertMAPSAR v1.0"
                )

    def recover_existing_positions(self, df: pd.DataFrame) -> None:
        """
        State Recovery: Detects and resumes managing any existing trade opened earlier
        if the bot was stopped and restarted.
        """
        existing_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
        if existing_positions:
            for pos in existing_positions:
                pos_dir = "BUY" if pos.type == 0 else "SELL"
                r = pos.price_open * (config.INITIAL_SL_PERCENT / 100.0)
                self.logger.info(
                    f"[{self.target_name}] STATE RECOVERY: Adopted existing {pos_dir} position #{pos.ticket} "
                    f"@ {pos.price_open:.2f} | Current SL: {pos.sl:.2f} (R = {r:.2f}). "
                    f"Resuming active 1:1 R:R trailing management..."
                )
                self.manage_trailing_stop(pos, df)

    def poll(self) -> None:
        if not self.symbol:
            return

        df = self.mt5_mgr.get_rates(self.symbol, self.timeframe, n_bars=100)
        if df is None or len(df) < 20:
            return

        completed_candle_time = df['time'].iloc[-2]
        if self.last_processed_candle_time is None:
            self.last_processed_candle_time = completed_candle_time
            self.logger.info(f"[{self.target_name}] Synchronized to {completed_candle_time}. Awaiting next close...")
            # State recovery on startup
            self.recover_existing_positions(df)
            return

        if completed_candle_time > self.last_processed_candle_time:
            self.logger.info(f"[{self.target_name}] Bar closed at {completed_candle_time}. Evaluating...")
            self.on_candle_close(df)
            self.last_processed_candle_time = completed_candle_time

