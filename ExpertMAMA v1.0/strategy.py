"""
=============================================================================
Shifted-MA Trend Master v1.0 - Strategy Logic & Indicator Engine
=============================================================================
Replicates the exact mathematical behavior of MQL5 ExpertMAMA:
- Signal MA (12 SMA, Shift=6): Smooth trend breakout and trend following
- Trailing MA (12 SMA, Shift=0): Dynamic bar-by-bar trailing stop
- Bar-by-bar execution on completed candle close (no tick noise)
- Position reversal on opposite signal
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


class ShiftedMAStrategy:
    """Implements the Shifted-MA Trend Following and Dynamic Trailing Stop strategy."""

    def __init__(
        self,
        target_name: str,
        mt5_mgr: MT5Manager,
        logger: Optional[logging.Logger] = None
    ):
        self.target_name = target_name
        self.mt5_mgr = mt5_mgr
        self.logger = logger or logging.getLogger("ShiftedMA")
        self.profile = config.TARGET_PROFILES[target_name]
        self.symbol: Optional[str] = None
        self.magic_number = self.profile["magic_number"]
        self.timeframe = self.profile["timeframe"]
        self.last_processed_candle_time: Optional[pd.Timestamp] = None

    def initialize(self) -> bool:
        """Resolves broker symbol mapping."""
        self.symbol = self.mt5_mgr.resolve_symbol(self.target_name)
        if not self.symbol:
            self.logger.error(f"[{self.target_name}] Could not resolve broker symbol.")
            return False
        return True

    @staticmethod
    def calculate_indicators(
        df: pd.DataFrame,
        signal_period: int = config.SIGNAL_MA_PERIOD,
        signal_shift: int = config.SIGNAL_MA_SHIFT,
        trailing_period: int = config.TRAILING_MA_PERIOD,
        trailing_shift: int = config.TRAILING_MA_SHIFT
    ) -> pd.DataFrame:
        """
        Calculates Signal MA and Trailing MA matching MQL5 CSignalMA and CTrailingMA.
        In MQL5, a positive shift (shift=6) moves the MA curve forward, meaning bar i
        reads the MA calculated at bar (i + shift).
        """
        df = df.copy()

        # Unshifted 12 SMA (used for Trailing Stop)
        df['sma_unshifted'] = df['close'].rolling(window=trailing_period).mean()
        if trailing_shift > 0:
            df['trailing_ma'] = df['sma_unshifted'].shift(trailing_shift)
        else:
            df['trailing_ma'] = df['sma_unshifted']

        # Shifted 12 SMA (used for Signal Entry)
        # Shift 6 in pandas: shift forward by 6 bars
        df['signal_ma'] = df['close'].rolling(window=signal_period).mean().shift(signal_shift)

        return df

    def evaluate_signals(self, df: pd.DataFrame) -> Tuple[Optional[str], float, float]:
        """
        Evaluates signals on completed bar 1 (index -2):
        - BUY: Close crosses above Shifted MA
        - SELL: Close crosses below Shifted MA
        Returns: (signal_direction, signal_ma_val, trailing_ma_val)
        """
        if len(df) < config.SIGNAL_MA_PERIOD + config.SIGNAL_MA_SHIFT + 5:
            return None, 0.0, 0.0

        df_ind = self.calculate_indicators(df)

        # Bar 1 (completed bar) is at iloc[-2]
        # Bar 2 (previous completed bar) is at iloc[-3]
        bar1 = df_ind.iloc[-2]
        bar2 = df_ind.iloc[-3]

        c1, c2 = bar1['close'], bar2['close']
        s_ma1, s_ma2 = bar1['signal_ma'], bar2['signal_ma']
        t_ma1 = bar1['trailing_ma']

        if pd.isna(s_ma1) or pd.isna(s_ma2) or pd.isna(t_ma1):
            return None, 0.0, 0.0

        signal = None

        # Bullish Cross: Close crosses above Shifted 12 SMA
        if c2 <= s_ma2 and c1 > s_ma1:
            signal = "BUY"

        # Bearish Cross: Close crosses below Shifted 12 SMA
        elif c2 >= s_ma2 and c1 < s_ma1:
            signal = "SELL"

        return signal, float(s_ma1), float(t_ma1)

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
        """Called once per new candle close."""
        completed_candle_time = df['time'].iloc[-2]
        c1 = df['close'].iloc[-2]

        signal, s_ma1, t_ma1 = self.evaluate_signals(df)
        active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)

        # 1. Update trailing stops for active positions first
        for pos in active_positions:
            self.manage_trailing_stop(pos, df)

        # 2. Check for new trade or reversal signal
        if signal is not None:
            self.logger.info(
                f"[{self.target_name}] New Signal: {signal} at {completed_candle_time} | "
                f"Close: {c1:.2f} | Shifted 12 SMA: {s_ma1:.2f} | Trailing 12 SMA: {t_ma1:.2f}"
            )

            # Handle existing opposite positions (Reversal)
            for pos in active_positions:
                is_buy = (pos.type == 0)
                if (signal == "BUY" and not is_buy) or (signal == "SELL" and is_buy):
                    self.logger.info(f"[{self.target_name}] Signal reversal: Closing #{pos.ticket} before opening {signal}")
                    self.mt5_mgr.close_position(pos)

            # Refresh positions after potential close
            active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)

            # Open new trade if no position in this direction
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

                # Calculate lot size (Dynamic or Fallback)
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
                    tp=0.0,  # Open profit run; trailed via 1:1 R:R rule
                    magic=self.magic_number,
                    comment="ExpertMAMA v1.0"
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
        """Checks for new closed bar, recovers existing trades, and manages trailing stop."""
        if not self.symbol:
            return

        df = self.mt5_mgr.get_rates(self.symbol, self.timeframe, n_bars=100)
        if df is None or len(df) < 20:
            return

        # Continuous Trailing Stop Check on every poll tick for existing positions
        active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
        for pos in active_positions:
            self.manage_trailing_stop(pos, df)

        # Check if a new bar has closed
        completed_candle_time = df['time'].iloc[-2]
        if self.last_processed_candle_time is None:
            self.last_processed_candle_time = completed_candle_time
            self.logger.info(
                f"[{self.target_name}] Synchronized to latest closed candle: {completed_candle_time}. "
                f"Scanning for existing trades..."
            )
            self.recover_existing_positions(df)
            return

        if completed_candle_time > self.last_processed_candle_time:
            self.logger.info(f"[{self.target_name}] Bar closed at {completed_candle_time}. Running evaluation...")
            self.on_candle_close(df)
            self.last_processed_candle_time = completed_candle_time
