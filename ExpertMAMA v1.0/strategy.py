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
        Replicates MQL5 CTrailingMA.CheckTrailingStop:
        - For BUY: new_sl = trailing_ma. If new_sl > base_sl and new_sl < Bid - StopLevel, update SL.
        - For SELL: new_sl = trailing_ma + spread. If new_sl < base_sl and new_sl > Ask + StopLevel, update SL.
        """
        if len(df) < config.TRAILING_MA_PERIOD + 5:
            return

        df_ind = self.calculate_indicators(df)
        bar1 = df_ind.iloc[-2]
        t_ma1 = bar1['trailing_ma']
        if pd.isna(t_ma1):
            return

        info = self.mt5_mgr.get_symbol_info(self.symbol)
        if not info:
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return

        digits = info.digits
        point = info.point
        stops_level = info.trade_stops_level * point
        spread = info.spread * point

        pos_type = position.type
        pos_sl = position.sl
        pos_open = position.price_open
        ticket = position.ticket

        if pos_type == 0:  # ORDER_TYPE_BUY
            base = pos_open if pos_sl == 0.0 else pos_sl
            level = tick.bid - stops_level
            new_sl = round(t_ma1, digits)

            # Move SL up only if it exceeds current SL and is below valid stops level
            if new_sl > base and new_sl < level:
                self.logger.info(
                    f"[{self.target_name}] Trailing MA update BUY #{ticket}: "
                    f"Old SL: {pos_sl:.{digits}f} -> New SL: {new_sl:.{digits}f} (Bid: {tick.bid})"
                )
                self.mt5_mgr.modify_position_sltp(ticket, self.symbol, sl=new_sl, tp=position.tp)

        elif pos_type == 1:  # ORDER_TYPE_SELL
            base = pos_open if pos_sl == 0.0 else pos_sl
            level = tick.ask + stops_level
            new_sl = round(t_ma1 + spread, digits)

            # Move SL down only if it is below current SL (or no SL set) and above valid stops level
            if (pos_sl == 0.0 or new_sl < base) and new_sl > level:
                self.logger.info(
                    f"[{self.target_name}] Trailing MA update SELL #{ticket}: "
                    f"Old SL: {pos_sl:.{digits}f} -> New SL: {new_sl:.{digits}f} (Ask: {tick.ask})"
                )
                self.mt5_mgr.modify_position_sltp(ticket, self.symbol, sl=new_sl, tp=position.tp)

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
                # Initial SL is set to the Trailing MA value (or fallback point distance)
                initial_sl = t_ma1
                tick = mt5.symbol_info_tick(self.symbol)
                current_price = tick.ask if signal == "BUY" else tick.bid
                sl_distance = abs(current_price - initial_sl)

                # Calculate lot size (Dynamic or Fallback)
                lot = self.mt5_mgr.calculate_lot_size(
                    symbol=self.symbol,
                    sl_distance_price=sl_distance,
                    target_key=self.target_name
                )

                self.logger.info(
                    f"[{self.target_name}] Executing {signal} | Lot: {lot} | "
                    f"Initial SL: {initial_sl:.2f} | Magic: {self.magic_number}"
                )
                self.mt5_mgr.open_position(
                    symbol=self.symbol,
                    order_type=signal,
                    volume=lot,
                    sl=initial_sl,
                    tp=0.0,  # Open profit run; closed via Trailing MA or Reversal
                    magic=self.magic_number,
                    comment="Shifted-MA Master v1.0"
                )

    def poll(self) -> None:
        """Checks for new closed bar and executes on_candle_close."""
        if not self.symbol:
            return

        df = self.mt5_mgr.get_rates(self.symbol, self.timeframe, n_bars=100)
        if df is None or len(df) < 20:
            return

        # Check if a new bar has closed
        completed_candle_time = df['time'].iloc[-2]
        if self.last_processed_candle_time is None:
            self.last_processed_candle_time = completed_candle_time
            self.logger.info(
                f"[{self.target_name}] Synchronized to latest closed candle: {completed_candle_time}. "
                f"Awaiting next candle close..."
            )
            # Update trailing stop on startup if position exists
            for pos in self.mt5_mgr.get_open_positions(self.symbol, self.magic_number):
                self.manage_trailing_stop(pos, df)
            return

        if completed_candle_time > self.last_processed_candle_time:
            self.logger.info(f"[{self.target_name}] Bar closed at {completed_candle_time}. Running evaluation...")
            self.on_candle_close(df)
            self.last_processed_candle_time = completed_candle_time
