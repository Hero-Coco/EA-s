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
        """Trailing Stop logic using Parabolic SAR from CTrailingPSAR."""
        df_ind = self.calculate_indicators(df)
        bar1 = df_ind.iloc[-2]
        sar1 = bar1['sar']
        if pd.isna(sar1):
            return

        info = self.mt5_mgr.get_symbol_info(self.symbol)
        tick = mt5.symbol_info_tick(self.symbol)
        if not info or not tick:
            return

        digits = info.digits
        point = info.point
        stops_level = info.trade_stops_level * point
        spread = info.spread * point

        pos_type = position.type
        pos_sl = position.sl
        pos_open = position.price_open
        ticket = position.ticket

        if pos_type == 0:  # BUY
            base = pos_open if pos_sl == 0.0 else pos_sl
            level = tick.bid - stops_level
            new_sl = round(sar1, digits)

            if new_sl > base and new_sl < level:
                self.logger.info(
                    f"[{self.target_name}] Parabolic SAR Trailing BUY #{ticket}: "
                    f"Old SL: {pos_sl} -> New SL: {new_sl} (SAR: {sar1:.2f})"
                )
                self.mt5_mgr.modify_position_sltp(ticket, self.symbol, sl=new_sl, tp=position.tp)

        elif pos_type == 1:  # SELL
            base = pos_open if pos_sl == 0.0 else pos_sl
            level = tick.ask + stops_level
            new_sl = round(sar1 + spread, digits)

            if (pos_sl == 0.0 or new_sl < base) and new_sl > level:
                self.logger.info(
                    f"[{self.target_name}] Parabolic SAR Trailing SELL #{ticket}: "
                    f"Old SL: {pos_sl} -> New SL: {new_sl} (SAR: {sar1:.2f})"
                )
                self.mt5_mgr.modify_position_sltp(ticket, self.symbol, sl=new_sl, tp=position.tp)

    def on_candle_close(self, df: pd.DataFrame) -> None:
        completed_candle_time = df['time'].iloc[-2]
        signal, s_ma1, sar1 = self.evaluate_signals(df)
        active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)

        for pos in active_positions:
            self.manage_trailing_stop(pos, df)

        if signal is not None:
            self.logger.info(
                f"[{self.target_name}] New Signal: {signal} at {completed_candle_time} | "
                f"Shifted 12 SMA: {s_ma1:.2f} | Parabolic SAR: {sar1:.2f}"
            )

            # Reversal
            for pos in active_positions:
                is_buy = (pos.type == 0)
                if (signal == "BUY" and not is_buy) or (signal == "SELL" and is_buy):
                    self.logger.info(f"[{self.target_name}] Reversal: Closing #{pos.ticket}")
                    self.mt5_mgr.close_position(pos)

            active_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
            already_open = any(
                (pos.type == 0 and signal == "BUY") or (pos.type == 1 and signal == "SELL")
                for pos in active_positions
            )

            if not already_open:
                initial_sl = sar1
                tick = mt5.symbol_info_tick(self.symbol)
                current_price = tick.ask if signal == "BUY" else tick.bid
                sl_distance = abs(current_price - initial_sl)

                lot = self.mt5_mgr.calculate_lot_size(
                    symbol=self.symbol,
                    sl_distance_price=sl_distance,
                    target_key=self.target_name
                )

                self.logger.info(
                    f"[{self.target_name}] Executing {signal} | Lot: {lot} | "
                    f"Initial SL (Parabolic SAR): {initial_sl:.2f}"
                )
                self.mt5_mgr.open_position(
                    symbol=self.symbol,
                    order_type=signal,
                    volume=lot,
                    sl=initial_sl,
                    tp=0.0,
                    magic=self.magic_number,
                    comment="MAPSAR-Trend Bot v1.0"
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
            self.logger.info(f"[{self.target_name}] Synchronized to {completed_candle_time}. Awaiting next close...")
            for pos in self.mt5_mgr.get_open_positions(self.symbol, self.magic_number):
                self.manage_trailing_stop(pos, df)
            return

        if completed_candle_time > self.last_processed_candle_time:
            self.logger.info(f"[{self.target_name}] Bar closed at {completed_candle_time}. Evaluating...")
            self.on_candle_close(df)
            self.last_processed_candle_time = completed_candle_time
