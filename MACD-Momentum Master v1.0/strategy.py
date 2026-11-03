"""
=============================================================================
MACD-Momentum Master v1.0 - Strategy & Signal Engine
=============================================================================
Replicates MQL5 built-in EA: ExpertMACD.mq5 (Magic 10981)
- Fast EMA: 12, Slow EMA: 24, Signal SMA/EMA: 9
- Signal Line and Zero-Line crossovers
- Dynamic SL/TP and signal reversal
=============================================================================
"""

import logging
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

import config
from mt5_manager import MT5Manager


class MACDStrategy:
    """MACD Momentum Trend and Crossover Strategy."""

    def __init__(
        self,
        target_name: str,
        mt5_mgr: MT5Manager,
        logger: Optional[logging.Logger] = None
    ):
        self.target_name = target_name
        self.mt5_mgr = mt5_mgr
        self.logger = logger or logging.getLogger("MACD")
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
        # Fast & Slow EMAs
        ema_fast = df['close'].ewm(span=config.MACD_FAST, adjust=False).mean()
        ema_slow = df['close'].ewm(span=config.MACD_SLOW, adjust=False).mean()

        df['macd_main'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd_main'].ewm(span=config.MACD_SIGNAL, adjust=False).mean()
        df['macd_hist'] = df['macd_main'] - df['macd_signal']

        return df

    def evaluate_signals(self, df: pd.DataFrame) -> Tuple[Optional[str], float, float]:
        if len(df) < config.MACD_SLOW + config.MACD_SIGNAL + 5:
            return None, 0.0, 0.0

        df_ind = self.calculate_indicators(df)
        bar1 = df_ind.iloc[-2]
        bar2 = df_ind.iloc[-3]

        m1, s1 = bar1['macd_main'], bar1['macd_signal']
        m2, s2 = bar2['macd_main'], bar2['macd_signal']

        if pd.isna(m1) or pd.isna(s1) or pd.isna(m2) or pd.isna(s2):
            return None, 0.0, 0.0

        signal = None

        # Bullish: MACD crosses above Signal Line OR crosses above Zero
        if (m2 <= s2 and m1 > s1) or (m2 <= 0.0 and m1 > 0.0):
            signal = "BUY"

        # Bearish: MACD crosses below Signal Line OR crosses below Zero
        elif (m2 >= s2 and m1 < s1) or (m2 >= 0.0 and m1 < 0.0):
            signal = "SELL"

        return signal, float(m1), float(s1)

    def on_candle_close(self, df: pd.DataFrame) -> None:
        completed_candle_time = df['time'].iloc[-2]
        signal, m1, s1 = self.evaluate_signals(df)
        active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)

        if signal is not None:
            self.logger.info(
                f"[{self.target_name}] MACD Signal: {signal} at {completed_candle_time} | "
                f"MACD Main: {m1:.4f} | Signal: {s1:.4f}"
            )

            # Reversal
            for pos in active_positions:
                is_buy = (pos.type == 0)
                if (signal == "BUY" and not is_buy) or (signal == "SELL" and is_buy):
                    self.logger.info(f"[{self.target_name}] MACD Reversal: Closing #{pos.ticket}")
                    self.mt5_mgr.close_position(pos)

            active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
            already_open = any(
                (pos.type == 0 and signal == "BUY") or (pos.type == 1 and signal == "SELL")
                for pos in active_positions
            )

            if not already_open:
                tick = mt5.symbol_info_tick(self.symbol)
                current_price = tick.ask if signal == "BUY" else tick.bid

                sl_pts = self.profile.get("sl_points", 20.0)
                tp_pts = self.profile.get("tp_points", 50.0)

                sl_price = (current_price - sl_pts) if signal == "BUY" else (current_price + sl_pts)
                tp_price = (current_price + tp_pts) if signal == "BUY" else (current_price - tp_pts)

                lot = self.mt5_mgr.calculate_lot_size(
                    symbol=self.symbol,
                    sl_distance_price=sl_pts,
                    target_key=self.target_name
                )

                self.logger.info(
                    f"[{self.target_name}] Executing MACD {signal} | Lot: {lot} | "
                    f"Entry: {current_price} | SL: {sl_price:.2f} | TP: {tp_price:.2f}"
                )
                self.mt5_mgr.open_position(
                    symbol=self.symbol,
                    order_type=signal,
                    volume=lot,
                    sl=sl_price,
                    tp=tp_price,
                    magic=self.magic_number,
                    comment="MACD-Momentum Master v1.0"
                )

    def poll(self) -> None:
        if not self.symbol:
            return

        df = self.mt5_mgr.get_rates(self.symbol, self.timeframe, n_bars=100)
        if df is None or len(df) < 20:
            return

        completed_candle_time = df['time'].iloc[-2]
        if self.last_processed_candle_time is None:
            self.last_processed_candle_time = completed_candle_time
            self.logger.info(f"[{self.target_name}] Synchronized to {completed_candle_time}.")
            return

        if completed_candle_time > self.last_processed_candle_time:
            self.logger.info(f"[{self.target_name}] Bar closed at {completed_candle_time}. Evaluating MACD...")
            self.on_candle_close(df)
            self.last_processed_candle_time = completed_candle_time
