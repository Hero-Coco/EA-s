"""
=============================================================================
NY-Open 12 EMA Trend Bot v1.0 - Strategy Engine
=============================================================================
Strategy Rules:
1. Calculates 12 EMA and 14 ATR on 5-Minute timeframe.
2. Identifies the close of the FIRST 5-minute candle after New York open (09:30 - 09:35 ET).
3. If Close > 12 EMA -> BUY Order.
4. If Close < 12 EMA -> SELL Order.
5. Trailing Stop:
   - Dynamic ATR-based or fixed point trailing stop.
   - Initial Stop Loss placed at Entry +/- (ATR * initial_sl_mult).
   - Sl trails upward for BUY as price advances, and downward for SELL.
6. Take Profit: Strictly 0.0 (unlimited upside/downside captured by trailing stop).
7. Frequency: Exactly 1 trade per day per symbol.
=============================================================================
"""

from datetime import datetime, date, time
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd
import pytz
import MetaTrader5 as mt5

import config
from mt5_manager import MT5Manager
from trade_logger import setup_logger, record_trade_to_csv


class NYOpen12EMAStrategy:
    """Strategy instance for a single symbol (e.g. NAS100 / USTECm or XAUUSD / XAUUSDm)."""

    def __init__(self, target_name: str, broker_symbol: str, mt5_mgr: MT5Manager):
        self.target_name = target_name
        self.symbol = broker_symbol
        self.mt5_mgr = mt5_mgr
        self.logger = setup_logger(f"Strategy_{target_name}")

        self.magic = config.MAGIC_NUMBERS.get(self.symbol, config.MAGIC_NUMBERS.get(target_name, 940101))
        self.profile = config.PAIR_PROFILES.get(target_name, config.PAIR_PROFILES.get("NAS100", {}))

        self.ny_tz = pytz.timezone(config.TIMEZONE_NAME)

        # Daily state variables
        self.current_trading_day: Optional[date] = None
        self.signal_processed_today: bool = False
        self.active_ticket: Optional[int] = None
        self.active_direction: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.last_trail_sl: float = 0.0
        self.ema12_at_entry: float = 0.0

    def reset_daily_state(self, current_date: date):
        """Resets flags at the start of a new New York trading day."""
        if self.current_trading_day != current_date:
            self.current_trading_day = current_date
            self.signal_processed_today = False
            self.active_ticket = None
            self.active_direction = None
            self.entry_price = 0.0
            self.entry_time = None
            self.last_trail_sl = 0.0
            self.ema12_at_entry = 0.0
            self.logger.info(f"[{self.target_name} ({self.symbol})] New Trading Day Initialized: {current_date}")

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates 12 EMA and 14 ATR using pandas.
        """
        # 12 EMA calculation
        df['ema12'] = df['close'].ewm(span=config.EMA_PERIOD, adjust=False).mean()

        # True Range and ATR(14)
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = df['tr'].rolling(window=config.ATR_PERIOD).mean()
        return df

    def check_opening_signal(self, now_ny: datetime):
        """
        Evaluates the close of the FIRST 5-minute candle after 09:30 AM ET (at 09:35 AM ET).
        """
        if self.signal_processed_today:
            return

        now_time = now_ny.time()

        # If it's before 09:35 ET, wait for the first 5-min candle to close
        if now_time < config.ENTRY_SIGNAL_TIME:
            return

        # Fetch recent M5 bars
        df = self.mt5_mgr.fetch_ohlcv(self.symbol, config.TIMEFRAME, num_bars=50)
        if df is None or len(df) < config.EMA_PERIOD + 2:
            return

        df = self.compute_indicators(df)

        # Identify the 08:00:00 bar of today (Forex/Gold NY Open)
        # In MT5, the bar timestamp is the open time of the bar (i.e. 08:00:00 represents 08:00 - 08:05)
        today = now_ny.date()
        target_bar_ny = None

        for idx, row in df.iterrows():
            bar_time = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
            if bar_time.date() == today and bar_time.hour == 8 and bar_time.minute == 0:
                target_bar_ny = row
                break

        if target_bar_ny is None:
            # Bar not yet available or missing
            return

        first_close = float(target_bar_ny['close'])
        ema12 = float(target_bar_ny['ema12'])
        atr = float(target_bar_ny['atr']) if not np.isnan(target_bar_ny['atr']) else (first_close * 0.005)

        self.logger.info(
            f"[{self.target_name}] First 5-min Candle (08:00-08:05 ET) Closed: "
            f"Close = {first_close:.4f} | 12 EMA = {ema12:.4f} | ATR({config.ATR_PERIOD}) = {atr:.4f}"
        )

        direction = None
        if first_close > ema12:
            direction = "BUY"
            self.logger.info(f"[{self.target_name}] Close ({first_close}) > 12 EMA ({ema12}) -> BUY Signal Confirmed!")
        elif first_close < ema12:
            direction = "SELL"
            self.logger.info(f"[{self.target_name}] Close ({first_close}) < 12 EMA ({ema12}) -> SELL Signal Confirmed!")
        else:
            self.logger.info(f"[{self.target_name}] Close ({first_close}) equals 12 EMA ({ema12}) -> No Trade.")
            self.signal_processed_today = True
            return

        # Calculate initial Stop Loss
        trail_mode = self.profile.get("trail_mode", config.TRAIL_MODE)
        point = self.mt5_mgr.symbol_infos[self.symbol].point if self.symbol in self.mt5_mgr.symbol_infos else 0.01

        if trail_mode == "ATR":
            atr_mult = self.profile.get("initial_sl_atr_mult", config.INITIAL_SL_ATR_MULT)
            sl_distance = atr * atr_mult
        else:
            sl_points = self.profile.get("fixed_trail_points", config.TRAIL_POINTS_DEFAULT)
            sl_distance = sl_points * point

        quote = self.mt5_mgr.get_market_quote(self.symbol)
        if quote is None:
            self.logger.error(f"[{self.target_name}] Failed to get market quote to execute order.")
            return

        bid, ask = quote
        if direction == "BUY":
            initial_sl = ask - sl_distance
        else:
            initial_sl = bid + sl_distance

        lot_size = self.profile.get("lot_size", config.DEFAULT_LOT)

        # Place the order
        res = self.mt5_mgr.place_market_order(
            symbol=self.symbol,
            direction=direction,
            volume=lot_size,
            initial_sl=initial_sl,
            magic=self.magic,
            comment=f"NY-12EMA-{direction}"
        )

        self.signal_processed_today = True

        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            self.active_ticket = res.order
            self.active_direction = direction
            self.entry_price = res.price
            self.entry_time = now_ny
            self.last_trail_sl = initial_sl
            self.ema12_at_entry = ema12

            self.logger.info(
                f"[{self.target_name}] Live position opened: #{self.active_ticket} {direction} "
                f"at {self.entry_price} | Initial SL: {initial_sl:.4f} | TP: 0.0"
            )

    def manage_trailing_stop(self, now_ny: datetime):
        """
        Monitors active position and updates Stop Loss as price moves favorably.
        """
        pos = self.mt5_mgr.get_open_position(self.symbol, self.magic)

        # If no active position found in MT5, check if our tracked position was closed
        if pos is None:
            if self.active_ticket is not None:
                self.logger.info(
                    f"[{self.target_name}] Position #{self.active_ticket} was closed (hit Trailing Stop Loss)."
                )
                # Fetch recent deals to record in CSV
                self._record_closed_position()
                self.active_ticket = None
                self.active_direction = None
            return

        self.active_ticket = pos.ticket
        self.active_direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"

        quote = self.mt5_mgr.get_market_quote(self.symbol)
        if quote is None:
            return
        bid, ask = quote

        sym_info = self.mt5_mgr.symbol_infos.get(self.symbol)
        point = sym_info.point if sym_info else 0.01

        # Fetch latest ATR for dynamic trailing distance
        df = self.mt5_mgr.fetch_ohlcv(self.symbol, config.TIMEFRAME, num_bars=30)
        atr_val = 0.0
        if df is not None and len(df) >= config.ATR_PERIOD:
            df = self.compute_indicators(df)
            atr_val = float(df['atr'].iloc[-1])

        trail_mode = self.profile.get("trail_mode", config.TRAIL_MODE)
        if trail_mode == "ATR" and atr_val > 0:
            trail_mult = self.profile.get("atr_multiplier", config.ATR_MULTIPLIER)
            trail_dist = atr_val * trail_mult
        else:
            trail_pts = self.profile.get("fixed_trail_points", config.TRAIL_POINTS_DEFAULT)
            trail_dist = trail_pts * point

        min_step = self.profile.get("min_trail_step", config.MIN_TRAIL_STEP_POINTS) * point

        # BUY Trailing Stop: Sl rises as Bid rises
        if pos.type == mt5.ORDER_TYPE_BUY:
            target_sl = bid - trail_dist
            # Only move SL up
            if target_sl > (pos.sl + min_step):
                self.mt5_mgr.modify_stop_loss(pos, target_sl)
                self.last_trail_sl = target_sl

        # SELL Trailing Stop: Sl falls as Ask falls
        elif pos.type == mt5.ORDER_TYPE_SELL:
            target_sl = ask + trail_dist
            # Only move SL down
            if pos.sl == 0.0 or target_sl < (pos.sl - min_step):
                self.mt5_mgr.modify_stop_loss(pos, target_sl)
                self.last_trail_sl = target_sl

    def _record_closed_position(self):
        """Records the closed position into trades_history.csv."""
        try:
            record_trade_to_csv({
                "ticket": self.active_ticket,
                "symbol": self.symbol,
                "direction": self.active_direction,
                "lot_size": self.profile.get("lot_size", config.DEFAULT_LOT),
                "open_time": self.entry_time.strftime("%Y-%m-%d %H:%M:%S") if self.entry_time else "",
                "open_price": self.entry_price,
                "close_time": datetime.now(self.ny_tz).strftime("%Y-%m-%d %H:%M:%S"),
                "close_price": self.last_trail_sl,
                "ema12_at_entry": self.ema12_at_entry,
                "trail_mode": self.profile.get("trail_mode", config.TRAIL_MODE),
                "pnl": 0.0,
                "comment": "Closed by Trailing Stop"
            })
        except Exception as e:
            self.logger.error(f"Error recording closed position: {e}")

    def on_tick(self):
        """Executed periodically in the main bot loop."""
        now_ny = datetime.now(self.ny_tz)
        self.reset_daily_state(now_ny.date())

        # 1. Manage active position (trailing stop)
        self.manage_trailing_stop(now_ny)

        # 2. Check for 09:35 ET entry signal
        self.check_opening_signal(now_ny)

