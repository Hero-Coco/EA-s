"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - Smart Money Concepts Strategy Logic
=============================================================================
Implementation of:
1. Liquidity Sweep Detection (20-candle swing extreme break & close back)
2. Market Structure Shift (MSS) Confirmation
3. Fair Value Gap (FVG) >= min points
4. FVG Mitigation & Engulfing Candle Trigger
5. SL: Beyond FVG | TP: Opposite liquidity pool | Max 2 trades/day
=============================================================================
"""

from datetime import datetime, date
from typing import Optional, Dict, Any, List
import pandas as pd
import MetaTrader5 as mt5

import config
from smc_detector import (
    calculate_swings,
    detect_liquidity_sweep,
    detect_fvg_at_bar,
    is_engulfing_inside_fvg,
    is_in_fib_golden_pocket,
    FVGZone,
    SMCCandidate
)
from mt5_manager import MT5Manager
from trade_logger import setup_logger, record_trade_to_csv
from chart_visualizer import plot_smc_setup


class SMCLiquidityStrategy:
    """Strategy instance handling SMC state machine for a single asset."""

    def __init__(self, target_name: str, broker_symbol: str, mt5_mgr: MT5Manager):
        self.target_name = target_name
        self.symbol = broker_symbol
        self.mt5_mgr = mt5_mgr
        self.logger = setup_logger(f"SMC_{target_name}")

        self.magic = config.MAGIC_NUMBERS.get(self.symbol, config.MAGIC_NUMBERS.get(target_name, 950101))
        self.profile = config.PAIR_PROFILES.get(target_name, config.PAIR_PROFILES.get("NIFTY", {}))

        # Daily state tracking
        self.current_trading_day: Optional[date] = None
        self.trades_count_today: int = 0
        self.active_ticket: Optional[int] = None
        self.active_trade_details: Optional[Dict[str, Any]] = None
        self.last_processed_candle_time: Optional[pd.Timestamp] = None

        # State Recovery on startup
        self.recover_existing_positions()

    def recover_existing_positions(self):
        """
        State Recovery: Scans MT5 for open positions matching MAGIC.
        Adopts existing positions into active tracking and increments trades_count_today
        to prevent duplicate entries on bot restart.
        """
        pos = self.mt5_mgr.get_open_position(self.symbol, self.magic)
        if pos:
            self.active_ticket = pos.ticket
            direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
            self.trades_count_today = 1
            self.active_trade_details = {
                "ticket": pos.ticket,
                "symbol": self.symbol,
                "direction": direction,
                "lot_size": pos.volume,
                "open_time": datetime.fromtimestamp(pos.time).strftime("%Y-%m-%d %H:%M:%S"),
                "open_price": pos.price_open,
                "sl_price": pos.sl,
                "tp_price": pos.tp,
                "fvg_top": 0.0,
                "fvg_bottom": 0.0,
                "fvg_size": 0.0,
                "pnl": 0.0,
                "exit_reason": "Active"
            }
            self.logger.info(
                f"[{self.target_name}] STATE RECOVERY: Adopted existing {direction} position "
                f"#{pos.ticket} @ {pos.price_open:.2f} (SL: {pos.sl:.2f}, TP: {pos.tp:.2f}, Volume: {pos.volume}). "
                f"Resuming active SL/TP monitoring..."
            )

    def reset_daily_state(self, current_date: date):
        """Resets daily trade counters on a new calendar day."""
        if self.current_trading_day != current_date:
            self.current_trading_day = current_date
            pos = self.mt5_mgr.get_open_position(self.symbol, self.magic)
            if pos is None:
                self.trades_count_today = 0
            self.logger.info(f"[{self.target_name}] New Day Initialized ({current_date}).")

    def monitor_active_position(self):
        """Checks if open position hit SL or TP in MT5."""
        if self.active_ticket is None:
            return

        pos = self.mt5_mgr.get_open_position(self.symbol, self.magic)
        if pos is None:
            # Position was closed
            self.logger.info(f"[{self.target_name}] Active position #{self.active_ticket} closed by SL or TP.")
            if self.active_trade_details:
                quote = self.mt5_mgr.get_market_quote(self.symbol)
                close_price = quote[0] if quote else self.active_trade_details['open_price']
                self.active_trade_details['close_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.active_trade_details['close_price'] = close_price
                self.active_trade_details['exit_reason'] = "SL/TP Hit"
                record_trade_to_csv(self.active_trade_details)
            self.active_ticket = None
            self.active_trade_details = None

    def evaluate_smc_setup(self, df: pd.DataFrame):
        """
        Scans recent bars to detect the 3 SMC concepts:
        1. Liquidity Sweep
        2. Market Structure Shift (MSS)
        3. Fair Value Gap (FVG) + Engulfing entry inside FVG
        """
        n_bars = len(df)
        if n_bars < config.SWING_LOOKBACK + 10:
            return

        min_fvg = self.profile.get("min_fvg_points", 10.0)
        sl_buffer = self.profile.get("sl_buffer_points", 2.0)
        min_rr = self.profile.get("min_rr_ratio", 1.5)

        swing_high_series, swing_low_series = calculate_swings(df, config.SWING_LOOKBACK)

        # Look back over recent bars (last 30 bars) for a valid setup lifecycle
        scan_start = max(config.SWING_LOOKBACK + 5, n_bars - 35)

        for i in range(scan_start, n_bars - 1):
            sh = swing_high_series.iloc[i]
            sl = swing_low_series.iloc[i]

            sweep_result = detect_liquidity_sweep(df, i, sh, sl)
            if sweep_result is None:
                continue

            sweep_type, sweep_level = sweep_result

            # -------------------------------------------------------------
            # Bullish Setup: Bullish Sweep -> MSS -> Bullish FVG -> Entry
            # -------------------------------------------------------------
            if sweep_type == "BULLISH":
                mss_found = False
                mss_bar = None
                mss_target = sh

                # Search forward from sweep for MSS (Close > swing_high)
                for j in range(i + 1, n_bars):
                    if df['close'].iloc[j] > mss_target:
                        mss_found = True
                        mss_bar = j
                        break

                if not mss_found:
                    continue

                # Search for Bullish FVG formed during or after sweep/MSS
                active_fvg = None
                for k in range(i, n_bars):
                    fvg = detect_fvg_at_bar(df, k, min_size_points=min_fvg)
                    if fvg and fvg.direction == "BULLISH":
                        active_fvg = fvg

                if active_fvg is None:
                    continue

                # Check if current closed candle (index n_bars - 1) is an engulfing candle inside the FVG
                trigger_idx = n_bars - 1
                if is_engulfing_inside_fvg(df, trigger_idx, active_fvg):
                    entry_price = float(df['close'].iloc[trigger_idx])
                    sl_price = active_fvg.bottom - sl_buffer
                    risk = entry_price - sl_price
                    if risk <= 0:
                        continue

                    # Target external liquidity pool (MSS swing high) or at least 1:1.5 R:R
                    mss_high = float(df['high'].iloc[i:n_bars].max())
                    tp_price = max(mss_high, entry_price + (risk * 1.5))
                    reward = tp_price - entry_price

                    # Piece 4 (from Video): Fibonacci Golden Pocket (0.50 - 0.786) Retracement Filter
                    if config.USE_FIBONACCI_FILTER:
                        if not is_in_fib_golden_pocket("BUY", entry_price, sweep_level, mss_high, config.FIB_MIN_RETRACEMENT, config.FIB_MAX_RETRACEMENT):
                            continue

                    if reward / risk >= min_rr:
                        self.logger.info("=" * 70)
                        self.logger.info(f"[{self.target_name}] SMC 4/4 A-GRADE BULLISH SETUP CONFIRMED!")
                        self.logger.info(f" 1. Liquidity Sweep at bar #{i} below {sweep_level:.2f}")
                        self.logger.info(f" 2. MSS confirmed at bar #{mss_bar} above {mss_target:.2f}")
                        self.logger.info(f" 3. Bullish FVG: [{active_fvg.bottom:.2f} - {active_fvg.top:.2f}] (Size: {active_fvg.size:.2f} pts)")
                        self.logger.info(f" 4. Fibonacci Golden Pocket (>= 50% discount) confirmed")
                        self.logger.info(f" -> Bullish Engulfing entry at {entry_price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f} (R:R {reward/risk:.2f})")
                        self.logger.info("=" * 70)

                        self._execute_order(
                            direction="BUY",
                            entry_price=entry_price,
                            sl_price=sl_price,
                            tp_price=tp_price,
                            fvg=active_fvg,
                            sh=sh,
                            sl=sl,
                            df_window=df.iloc[max(0, i - 10):trigger_idx + 1]
                        )
                        return

            # -------------------------------------------------------------
            # Bearish Setup: Bearish Sweep -> MSS -> Bearish FVG -> Entry
            # -------------------------------------------------------------
            elif sweep_type == "BEARISH":
                mss_found = False
                mss_bar = None
                mss_target = sl

                # Search forward from sweep for MSS (Close < swing_low)
                for j in range(i + 1, n_bars):
                    if df['close'].iloc[j] < mss_target:
                        mss_found = True
                        mss_bar = j
                        break

                if not mss_found:
                    continue

                # Search for Bearish FVG
                active_fvg = None
                for k in range(i, n_bars):
                    fvg = detect_fvg_at_bar(df, k, min_size_points=min_fvg)
                    if fvg and fvg.direction == "BEARISH":
                        active_fvg = fvg

                if active_fvg is None:
                    continue

                # Check if current closed candle is an engulfing candle inside the FVG
                trigger_idx = n_bars - 1
                if is_engulfing_inside_fvg(df, trigger_idx, active_fvg):
                    entry_price = float(df['close'].iloc[trigger_idx])
                    sl_price = active_fvg.top + sl_buffer
                    risk = sl_price - entry_price
                    if risk <= 0:
                        continue

                    # Target external liquidity pool (MSS swing low) or at least 1:1.5 R:R
                    mss_low = float(df['low'].iloc[i:n_bars].min())
                    tp_price = min(mss_low, entry_price - (risk * 1.5))
                    reward = entry_price - tp_price

                    # Piece 4 (from Video): Fibonacci Golden Pocket (0.50 - 0.786) Retracement Filter
                    if config.USE_FIBONACCI_FILTER:
                        if not is_in_fib_golden_pocket("SELL", entry_price, sweep_level, mss_low, config.FIB_MIN_RETRACEMENT, config.FIB_MAX_RETRACEMENT):
                            continue

                    if reward / risk >= min_rr:
                        self.logger.info("=" * 70)
                        self.logger.info(f"[{self.target_name}] SMC 4/4 A-GRADE BEARISH SETUP CONFIRMED!")
                        self.logger.info(f" 1. Liquidity Sweep at bar #{i} above {sweep_level:.2f}")
                        self.logger.info(f" 2. MSS confirmed at bar #{mss_bar} below {mss_target:.2f}")
                        self.logger.info(f" 3. Bearish FVG: [{active_fvg.bottom:.2f} - {active_fvg.top:.2f}] (Size: {active_fvg.size:.2f} pts)")
                        self.logger.info(f" 4. Fibonacci Golden Pocket (>= 50% premium) confirmed")
                        self.logger.info(f" -> Bearish Engulfing entry at {entry_price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f} (R:R {reward/risk:.2f})")
                        self.logger.info("=" * 70)

                        self._execute_order(
                            direction="SELL",
                            entry_price=entry_price,
                            sl_price=sl_price,
                            tp_price=tp_price,
                            fvg=active_fvg,
                            sh=sh,
                            sl=sl,
                            df_window=df.iloc[max(0, i - 10):trigger_idx + 1]
                        )
                        return

    def _execute_order(
        self,
        direction: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        fvg: FVGZone,
        sh: float,
        sl: float,
        df_window: pd.DataFrame
    ):
        """Sends order to MT5 with dynamic lot size and generates visual debug chart."""
        sl_dist = abs(entry_price - sl_price)
        if config.USE_DYNAMIC_LOT:
            lot_size = self.mt5_mgr.calculate_dynamic_lot(self.symbol, sl_dist)
        else:
            lot_size = self.profile.get("lot_size", config.DEFAULT_LOT)

        res = self.mt5_mgr.place_smc_order(
            symbol=self.symbol,
            direction=direction,
            volume=lot_size,
            sl_price=sl_price,
            tp_price=tp_price,
            magic=self.magic,
            comment=f"SMC-{direction}"
        )

        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            self.active_ticket = res.order
            self.trades_count_today += 1

            self.active_trade_details = {
                "ticket": res.order,
                "symbol": self.symbol,
                "direction": direction,
                "lot_size": lot_size,
                "open_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "open_price": res.price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "fvg_top": fvg.top,
                "fvg_bottom": fvg.bottom,
                "fvg_size": fvg.size,
                "pnl": 0.0,
                "exit_reason": "Active"
            }

            # Generate Matplotlib Visual Debug Chart
            try:
                chart_path = plot_smc_setup(
                    df_window=df_window,
                    symbol=self.target_name,
                    direction=direction,
                    entry_price=res.price,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    fvg_top=fvg.top,
                    fvg_bottom=fvg.bottom,
                    swing_high=sh,
                    swing_low=sl
                )
                self.logger.info(f"[{self.target_name}] SMC Setup Chart saved: {chart_path}")
            except Exception as e:
                self.logger.warning(f"Could not render SMC chart: {e}")

    def on_tick(self):
        """Main execution cycle checking on new 5-minute candle close."""
        today = date.today()
        self.reset_daily_state(today)

        # 1. Position monitoring
        self.monitor_active_position()

        # 2. Daily trades limit check
        if self.trades_count_today >= config.MAX_TRADES_PER_DAY:
            return

        if self.active_ticket is not None:
            return

        # 3. Fetch OHLCV M5 data
        df = self.mt5_mgr.fetch_ohlcv(self.symbol, config.TIMEFRAME, num_bars=150)
        if df is None or len(df) < config.SWING_LOOKBACK + 10:
            return

        # Check if the latest completed candle is new
        latest_closed_time = df.index[-2]  # index[-1] is the currently forming candle, index[-2] is the closed one
        if self.last_processed_candle_time == latest_closed_time:
            return

        self.last_processed_candle_time = latest_closed_time

        # Slice data up to the closed candle
        df_closed = df.iloc[:-1]
        self.evaluate_smc_setup(df_closed)
