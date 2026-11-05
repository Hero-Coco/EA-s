"""
=============================================================================
NQ-Precision ORB Bot v1.0 - Strategy & Execution Engine
=============================================================================
Replicates the institutional Opening Range Breakout (ORB) strategy:
- 09:30 - 09:45 ET M1 Opening Range construction
- 09:59:55 ET snapshot breakout entry
- Dual RVOL & ATR Regime filters
- Dynamic lot sizing based on account equity and 2.2x ATR SL
- 8-minute time-stop flat exit
- Full MT5 state recovery on bot restart
=============================================================================
"""

import logging
from datetime import datetime, time, date
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
import numpy as np
import pytz
import MetaTrader5 as mt5

import config
from mt5_manager import MT5Manager


class NQPrecisionORBStrategy:
    """Strategy instance executing the NQ Precision ORB algorithm for a single instrument."""

    def __init__(self, target_name: str, mt5_mgr: MT5Manager, logger: Optional[logging.Logger] = None):
        self.target_name = target_name
        self.mt5_mgr = mt5_mgr
        self.logger = logger or logging.getLogger(f"ORB_{target_name}")

        self.profile = config.TARGET_PROFILES[target_name]
        self.magic_number = self.profile["magic_number"]
        self.timeframe = config.TIMEFRAME
        self.ny_tz = pytz.timezone(config.TIMEZONE_NAME)

        self.symbol: Optional[str] = None
        self.active_trading_day: Optional[date] = None

        # Opening Range state
        self.range_high: float = 0.0
        self.range_low: float = 0.0
        self.have_range: bool = False
        self.range_locked: bool = False

        # Daily Trade state
        self.traded_today: bool = False
        self.active_position_ticket: Optional[int] = None
        self.entry_time: Optional[datetime] = None
        self.entry_price: float = 0.0
        self.entry_side: Optional[str] = None

    def initialize(self) -> bool:
        """Resolves broker symbol and runs initial state recovery."""
        self.symbol = self.mt5_mgr.resolve_symbol(self.target_name)
        if not self.symbol:
            return False

        # State Recovery on startup
        self.recover_existing_positions()
        return True

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Calculates ATR(14), ATR(50), ATR Regime, and RVOL(14)."""
        df = df.copy()

        # True Range
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Short ATR & Long ATR
        df['atr'] = df['tr'].rolling(window=config.ATR_PERIOD).mean()
        df['atr_long'] = df['tr'].rolling(window=config.ATR_REGIME_LEN).mean()
        df['atr_regime'] = df['atr'] / df['atr_long']

        # RVOL (Relative Volume)
        vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume'
        rolling_mean_vol = df[vol_col].rolling(window=config.RVOL_LEN).mean()
        df['rvol'] = df[vol_col] / rolling_mean_vol

        return df

    def reset_daily_state(self, current_ny_date: date):
        """Resets intraday variables at the beginning of a new NY trading session."""
        if self.active_trading_day != current_ny_date:
            self.active_trading_day = current_ny_date

            # Only reset traded_today if no active position is currently running
            open_positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
            if not open_positions:
                self.traded_today = False
                self.active_position_ticket = None
                self.entry_time = None
                self.entry_price = 0.0
                self.entry_side = None

            self.range_high = 0.0
            self.range_low = 0.0
            self.have_range = False
            self.range_locked = False

            self.logger.info("=" * 70)
            self.logger.info(f"[{self.target_name}] NEW TRADING DAY INITIALIZED: {current_ny_date} (NY Time)")
            self.logger.info("=" * 70)

    def recover_existing_positions(self) -> None:
        """
        State Recovery: Scans MT5 for open positions matching MAGIC_NUMBER.
        Adopts existing positions into active tracking and resumes 8-minute time-stop.
        """
        if not self.symbol:
            return

        positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
        if positions:
            pos = positions[0]
            self.active_position_ticket = pos.ticket
            self.entry_side = "BUY" if pos.type == 0 else "SELL"
            self.entry_price = pos.price_open
            # Convert pos.time (UTC timestamp) to NY datetime
            utc_dt = datetime.fromtimestamp(pos.time, tz=pytz.utc)
            self.entry_time = utc_dt.astimezone(self.ny_tz)
            self.traded_today = True

            self.logger.info(
                f"[{self.target_name}] STATE RECOVERY: Adopted existing {self.entry_side} position "
                f"#{pos.ticket} @ {pos.price_open:.2f} (SL: {pos.sl:.2f}, TP: {pos.tp:.2f}, Vol: {pos.volume}). "
                f"Opened at {self.entry_time.strftime('%H:%M:%S ET')}. Resuming active management & time-stop..."
            )

    def update_opening_range(self, df: pd.DataFrame, now_ny: datetime):
        """
        Constructs and locks the Opening Range from 1-minute bars between 09:30 and 09:45 ET.
        """
        if self.range_locked:
            return

        # Ensure timestamps in NY timezone
        df = df.copy()
        if df['time'].dt.tz is None:
            # MT5 timestamps are typically broker local/UTC; convert to UTC then NY
            df['time_ny'] = df['time'].dt.tz_localize('UTC').dt.tz_convert(self.ny_tz)
        else:
            df['time_ny'] = df['time'].dt.tz_convert(self.ny_tz)

        today_bars = df[df['time_ny'].dt.date == now_ny.date()]
        orb_bars = today_bars[
            (today_bars['time_ny'].dt.time >= config.RANGE_START_TIME) &
            (today_bars['time_ny'].dt.time < config.RANGE_END_TIME)
        ]

        if not orb_bars.empty:
            self.range_high = float(orb_bars['high'].max())
            self.range_low = float(orb_bars['low'].min())
            self.have_range = True

        # Lock range at or after 09:45 ET
        if now_ny.time() >= config.RANGE_END_TIME and self.have_range and not self.range_locked:
            self.range_locked = True
            range_pts = self.range_high - self.range_low
            self.logger.info("=" * 65)
            self.logger.info(
                f"[{self.target_name}] OPENING RANGE LOCKED (09:30-09:45 ET): "
                f"High={self.range_high:.2f} | Low={self.range_low:.2f} | Size={range_pts:.2f}"
            )
            self.logger.info("=" * 65)

    def check_filters(self, rvol: float, atr_regime: float) -> bool:
        """Validates that RVOL and ATR Regime sit strictly within institutional bounds."""
        if not config.USE_FILTERS:
            return True

        if pd.isna(rvol) or rvol < config.RVOL_MIN or rvol > config.RVOL_MAX:
            self.logger.info(
                f"[{self.target_name}] Filter Blocked: RVOL {rvol:.2f} outside [{config.RVOL_MIN}, {config.RVOL_MAX}]"
            )
            return False

        if pd.isna(atr_regime) or atr_regime < config.REGIME_MIN or atr_regime > config.REGIME_MAX:
            self.logger.info(
                f"[{self.target_name}] Filter Blocked: ATR Regime {atr_regime:.2f} outside [{config.REGIME_MIN}, {config.REGIME_MAX}]"
            )
            return False

        return True

    def evaluate_entry_trigger(self, df: pd.DataFrame, now_ny: datetime):
        """Evaluates entry trigger at 09:59:55 ET or breakout window."""
        if not self.range_locked or self.traded_today or self.active_position_ticket is not None:
            return

        now_time = now_ny.time()

        # Check timing window
        if config.USE_TRIGGER_TIME:
            # Trigger snapshot window: 09:59:55 - 10:00:15 ET
            trigger_target = time(config.TRIGGER_HOUR, config.TRIGGER_MINUTE, config.TRIGGER_SECOND)
            cutoff_target = time(config.TRIGGER_HOUR + 1, 0, 15) if config.TRIGGER_MINUTE == 59 else time(config.TRIGGER_HOUR, config.TRIGGER_MINUTE + 1, 0)
            in_window = (now_time >= trigger_target) and (now_time <= cutoff_target)
        else:
            in_window = (now_time >= config.RANGE_END_TIME) and (now_time <= config.TRADE_UNTIL_TIME)

        if not in_window:
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return

        current_bid = tick.bid
        current_ask = tick.ask

        # 1. Determine breakout direction
        direction = None
        if current_bid > self.range_high:
            direction = "BUY"
            entry_price = current_ask
        elif current_ask < self.range_low:
            direction = "SELL"
            entry_price = current_bid
        else:
            # Inside range
            if config.USE_TRIGGER_TIME:
                self.traded_today = True
                self.logger.info(
                    f"[{self.target_name}] 09:59:55 ET Snapshot: Price {current_bid:.2f} is INSIDE "
                    f"Opening Range [{self.range_low:.2f}, {self.range_high:.2f}]. NO TRADE TODAY."
                )
            return

        # 2. Check filters
        df_ind = self.calculate_indicators(df)
        last_bar = df_ind.iloc[-2]
        rvol = float(last_bar.get('rvol', np.nan))
        atr_regime = float(last_bar.get('atr_regime', np.nan))
        atr_val = float(last_bar.get('atr', np.nan))

        if pd.isna(atr_val) or atr_val <= 0:
            self.logger.warning(f"[{self.target_name}] ATR is not available; skipping entry.")
            return

        if not self.check_filters(rvol, atr_regime):
            self.traded_today = True
            self.logger.info(f"[{self.target_name}] Breakout detected but cancelled due to filter criteria.")
            return

        # 3. Compute ATR-based SL & TP
        sl_dist = atr_val * config.ATR_SL_MULT
        tp_dist = atr_val * config.ATR_TP_MULT

        sl_price = (entry_price - sl_dist) if direction == "BUY" else (entry_price + sl_dist)
        tp_price = (entry_price + tp_dist) if direction == "BUY" else (entry_price - tp_dist)

        # 4. Dynamic Lot Sizing
        lot = self.mt5_mgr.calculate_lot_size(
            symbol=self.symbol,
            sl_distance_price=sl_dist,
            target_key=self.target_name
        )

        self.logger.info("=" * 70)
        self.logger.info(
            f"[{self.target_name}] EXECUTING {direction} ORB BREAKOUT! "
            f"Price: {entry_price:.2f} | Range: [{self.range_low:.2f} - {self.range_high:.2f}]"
        )
        self.logger.info(
            f"Lot: {lot} | ATR(14): {atr_val:.2f} | RVOL: {rvol:.2f} | ATR Regime: {atr_regime:.2f} | "
            f"SL: {sl_price:.2f} (2.2x ATR) | TP: {tp_price:.2f} (0.3x ATR)"
        )
        self.logger.info("=" * 70)

        res = self.mt5_mgr.open_position(
            symbol=self.symbol,
            order_type=direction,
            volume=lot,
            sl=sl_price,
            tp=tp_price,
            magic=self.magic_number,
            comment="NQ-Precision ORB"
        )

        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            self.traded_today = True
            self.active_position_ticket = res.order
            self.entry_price = res.price
            self.entry_time = now_ny
            self.entry_side = direction

    def manage_time_stop_and_exit(self, now_ny: datetime):
        """
        Monitors active position:
        - Detects if position hit SL/TP.
        - Enforces 8-minute Time Stop: closes position if open >= 8 minutes.
        """
        if self.active_position_ticket is None:
            return

        positions = self.mt5_mgr.get_open_positions(self.symbol, self.magic_number)
        active_pos = next((p for p in positions if p.ticket == self.active_position_ticket), None)

        # If position closed (SL or TP hit)
        if active_pos is None:
            self.logger.info(f"[{self.target_name}] Position #{self.active_position_ticket} closed (SL or TP filled).")
            self.active_position_ticket = None
            self.entry_time = None
            self.entry_price = 0.0
            self.entry_side = None
            return

        # Enforce 8-Minute Time-Based Close
        if config.USE_TIME_CLOSE and self.entry_time is not None:
            elapsed_sec = (now_ny - self.entry_time).total_seconds()
            elapsed_min = elapsed_sec / 60.0

            if elapsed_min >= config.CLOSE_AFTER_MIN:
                self.logger.info(
                    f"[{self.target_name}] TIME-STOP TRIGGERED! "
                    f"Position #{active_pos.ticket} has been open for {elapsed_min:.1f} minutes "
                    f"(Limit: {config.CLOSE_AFTER_MIN} mins). Closing at market..."
                )
                if self.mt5_mgr.close_position(active_pos):
                    self.active_position_ticket = None
                    self.entry_time = None
                    self.entry_price = 0.0
                    self.entry_side = None

    def on_tick(self):
        """Main execution cycle called continuously on each loop tick."""
        if not self.symbol:
            return

        now_ny = datetime.now(self.ny_tz)
        self.reset_daily_state(now_ny.date())

        # 1. Manage active position (8-minute Time-Stop & SL/TP tracking)
        self.manage_time_stop_and_exit(now_ny)

        # Fetch M1 rates
        df = self.mt5_mgr.get_rates(self.symbol, config.TIMEFRAME, n_bars=120)
        if df is None or len(df) < config.ATR_REGIME_LEN + 5:
            return

        # 2. Update and lock opening range (09:30 - 09:45 ET)
        self.update_opening_range(df, now_ny)

        # 3. Check for snapshot entry trigger (09:59:55 ET)
        self.evaluate_entry_trigger(df, now_ny)
