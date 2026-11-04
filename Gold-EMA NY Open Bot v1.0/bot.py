"""
=============================================================================
Gold-EMA NY Open Bot v1.0 - MetaTrader 5 Expert Advisor
=============================================================================
Strategy:
1. Timing Filter: Only trade during New York open: 09:30 - 09:35 ET (14:30 - 14:35 UTC)
2. EMA 50 on M5 timeframe calculated on candle close
3. 5-Min Candle Analysis:
   - Close > EMA 50 -> Go LONG
   - Close < EMA 50 -> Go SHORT
4. Trade Management:
   - Long SL: 5-min candle low - 200 points ($2.00) buffer
   - Short SL: 5-min candle high + 200 points ($2.00) buffer
   - Trailing Stop: Activates at +400 points ($4.00) profit, trails by 300 points ($3.00),
     updates every 50 points ($0.50)
   - No fixed TP (capture full momentum trend)
5. Risk Management:
   - 0.05 lots
   - Max 1 trade per day
   - Max daily loss: -$500
   - Candle range filter: >= 300 points ($3.00)
   - Spread filter: <= 250 points ($2.50)
   - Weekend and holiday protection
=============================================================================
"""

import os
import sys
import time
import math
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import pandas as pd
import pytz
import MetaTrader5 as mt5

import config

# Setup Logger
logger = logging.getLogger("Gold_EMA_NY_Open")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(stream_handler)


def calculate_ema(df: pd.DataFrame, period: int = config.EMA_PERIOD) -> pd.Series:
    """
    Calculates 50-period Exponential Moving Average (EMA 50) on M5 timeframe.
    Uses pandas_ta if available, otherwise pure pandas ewm (100% compatible).
    """
    try:
        import pandas_ta as ta
        ema = ta.ema(df['close'], length=period)
        if ema is not None:
            return ema
    except Exception:
        pass

    # Pure pandas EWM calculation matching standard EMA formula
    return df['close'].ewm(span=period, adjust=False).mean()


def detect_ny_open_setup(
    df: pd.DataFrame,
    symbol: str,
    ny_now: datetime
) -> Optional[Dict[str, Any]]:
    """
    Analyzes the first 5-minute candle after NY Open (09:30 - 09:35 ET) and EMA 50.
    Returns trade setup dictionary if conditions are satisfied, else None.
    """
    if len(df) < config.EMA_PERIOD + 5:
        logger.warning("Insufficient candles to compute 50 EMA.")
        return None

    df = df.copy()
    df['ema50'] = calculate_ema(df, config.EMA_PERIOD)

    # Completed 5-min candle is at index -2 (bar 1)
    candle = df.iloc[-2]
    c_open = candle['open']
    c_high = candle['high']
    c_low = candle['low']
    c_close = candle['close']
    c_time = candle['time']
    ema_val = candle['ema50']

    # 1. Candle Volatility Filter (avoid low volatility chop)
    candle_range = c_high - c_low
    min_range = config.MIN_CANDLE_RANGE_POINTS * config.POINT_USD_VALUE

    if candle_range < min_range:
        logger.info(
            f"NY Open Candle Range ({candle_range:.2f}) < Minimum Required ({min_range:.2f}). "
            f"Low volatility detected; skipping trade."
        )
        return None

    # 2. Bullish / Bearish Signal Evaluation
    direction = None
    sl_buffer = config.SL_BUFFER_POINTS * config.POINT_USD_VALUE

    if c_close > ema_val:
        direction = "LONG"
        sl_price = c_low - sl_buffer
    elif c_close < ema_val:
        direction = "SHORT"
        sl_price = c_high + sl_buffer
    else:
        logger.info("Candle closed exactly on EMA 50; no directional signal.")
        return None

    # Detailed required log
    logger.info("=" * 70)
    logger.info(f"NY OPEN CANDLE CLOSE: {c_close:.2f}, EMA50: {ema_val:.2f}, SIGNAL: {direction}")
    logger.info(f"Candle Time: {c_time} | Open: {c_open:.2f} | High: {c_high:.2f} | Low: {c_low:.2f} | Range: {candle_range:.2f}")
    logger.info(f"Initial Stop Loss: {sl_price:.2f} (Buffer: {sl_buffer:.2f})")
    logger.info("=" * 70)

    return {
        "direction": direction,
        "candle_time": c_time,
        "candle_close": c_close,
        "ema50": ema_val,
        "sl_price": sl_price,
        "candle_high": c_high,
        "candle_low": c_low
    }


class GoldEMANyOpenBot:
    """Master Automated Bot for XAUUSD M5 NY Open Strategy."""

    def __init__(self):
        self.symbol: Optional[str] = None
        self.symbol_info: Optional[Any] = None
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.current_trading_day: Optional[date] = None
        self.active_position_ticket: Optional[int] = None
        self.active_trade_info: Optional[Dict[str, Any]] = None

    def initialize_mt5(self) -> bool:
        """Initializes terminal connection and resolves XAUUSD symbol."""
        logger.info("Connecting to MetaTrader 5 terminal...")
        if not mt5.initialize():
            logger.error(f"MT5 initialization failed! Error: {mt5.last_error()}")
            return False

        acc = mt5.account_info()
        if acc is None:
            logger.error(f"Failed to fetch account info. Error: {mt5.last_error()}")
            return False

        logger.info(
            f"Connected to MT5! Account: #{acc.login} | Name: '{acc.name}' | "
            f"Balance: ${acc.balance:.2f} | Equity: ${acc.equity:.2f} | Server: {acc.server}"
        )

        # Resolve broker symbol
        for sym in config.SYMBOL_CANDIDATES:
            info = mt5.symbol_info(sym)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(sym, True)
                self.symbol = sym
                self.symbol_info = info
                logger.info(
                    f"Gold Symbol mapped to broker symbol: '{sym}' "
                    f"(Digits: {info.digits}, Point: {info.point}, Min Lot: {info.volume_min})"
                )
                return True

        logger.error(f"Could not resolve any XAUUSD symbol from {config.SYMBOL_CANDIDATES}")
        return False

    def is_market_open(self, ny_now: datetime) -> bool:
        """Checks for weekend and basic market hours."""
        weekday = ny_now.weekday()
        # Saturday = 5, Sunday = 6
        if weekday == 5:
            return False
        if weekday == 6 and ny_now.hour < 18:
            return False
        if weekday == 4 and ny_now.hour >= 17:
            return False
        return True

    def check_spread(self) -> bool:
        """Validates spread before placing trade."""
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return False

        info = mt5.symbol_info(self.symbol)
        spread_price = tick.ask - tick.bid
        max_spread = config.MAX_SPREAD_POINTS * config.POINT_USD_VALUE

        if spread_price > max_spread:
            logger.warning(
                f"Spread too high ({spread_price:.2f} > max {max_spread:.2f}); skipping trade."
            )
            return False
        return True

    def fetch_m5_rates(self, n_bars: int = 150) -> Optional[pd.DataFrame]:
        """Fetches M5 candlestick data."""
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M5, 0, n_bars)
        if rates is None or len(rates) == 0:
            logger.warning(f"Failed to fetch rates: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def place_trade_with_trailing(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        lot: float = config.LOT_SIZE
    ) -> bool:
        """
        Executes order and sets up the active trailing stop manager.
        """
        if not self.check_spread():
            return False

        order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        info = mt5.symbol_info(symbol)
        digits = info.digits if info else 2

        entry_norm = round(entry_price, digits)
        sl_norm = round(sl_price, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": entry_norm,
            "sl": sl_norm,
            "tp": 0.0,  # No fixed TP, let trailing stop capture full 6-hour trend
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": "Gold-EMA NY Open v1.0",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Adapt broker filling mode
        if info:
            if info.filling_mode & 1:
                request["type_filling"] = mt5.ORDER_FILLING_FOK
            elif info.filling_mode & 2:
                request["type_filling"] = mt5.ORDER_FILLING_IOC
            else:
                request["type_filling"] = mt5.ORDER_FILLING_RETURN

        logger.info(
            f"Sending {direction} Market Order: {lot} lots @ {entry_norm} | SL: {sl_norm} on {symbol}"
        )
        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else str(mt5.last_error())
            logger.error(f"Order failed! Reason: {err}")
            return False

        logger.info(f"Trade successfully placed! Order #{result.order}, Deal #{result.deal}")
        self.trades_today += 1
        self.active_position_ticket = result.order

        self.active_trade_info = {
            "ticket": result.order,
            "direction": direction,
            "entry_time": datetime.now(),
            "entry_price": entry_norm,
            "initial_sl": sl_norm,
            "current_sl": sl_norm,
            "lot": lot,
            "trailing_activated": False,
            "last_trailing_update_price": entry_norm
        }

        return True

    def manage_trailing_stop(self) -> None:
        """
        Monitors open position and manages trailing stop:
        - Activates when in profit >= 400 points ($4.00)
        - Trails 300 points ($3.00) behind price
        - Updates SL every 50 points ($0.50)
        """
        if self.active_position_ticket is None or self.active_trade_info is None:
            return

        positions = mt5.positions_get(symbol=self.symbol)
        active_pos = None
        if positions:
            for p in positions:
                if p.magic == config.MAGIC_NUMBER:
                    active_pos = p
                    break

        # If position was closed (SL hit or manual close)
        if active_pos is None:
            self._handle_trade_closed()
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return

        direction = self.active_trade_info["direction"]
        entry = self.active_trade_info["entry_price"]
        current_sl = active_pos.sl
        digits = self.symbol_info.digits if self.symbol_info else 2

        trigger_dist = config.TRAILING_TRIGGER_POINTS * config.POINT_USD_VALUE
        trail_dist = config.TRAILING_DISTANCE_POINTS * config.POINT_USD_VALUE
        step_dist = config.TRAILING_STEP_POINTS * config.POINT_USD_VALUE

        if direction == "LONG":
            profit_points = tick.bid - entry
            if profit_points >= trigger_dist:
                target_sl = round(tick.bid - trail_dist, digits)
                if target_sl > current_sl + step_dist:
                    logger.info(
                        f"Trailing Stop Update (LONG): Bid: {tick.bid:.2f} | "
                        f"Old SL: {current_sl:.2f} -> New SL: {target_sl:.2f} (Profit: +{profit_points:.2f})"
                    )
                    self._modify_sl(active_pos.ticket, target_sl)
                    self.active_trade_info["current_sl"] = target_sl
                    self.active_trade_info["trailing_activated"] = True

        elif direction == "SHORT":
            profit_points = entry - tick.ask
            if profit_points >= trigger_dist:
                target_sl = round(tick.ask + trail_dist, digits)
                if (current_sl == 0.0) or (target_sl < current_sl - step_dist):
                    logger.info(
                        f"Trailing Stop Update (SHORT): Ask: {tick.ask:.2f} | "
                        f"Old SL: {current_sl:.2f} -> New SL: {target_sl:.2f} (Profit: +{profit_points:.2f})"
                    )
                    self._modify_sl(active_pos.ticket, target_sl)
                    self.active_trade_info["current_sl"] = target_sl
                    self.active_trade_info["trailing_activated"] = True

    def _modify_sl(self, ticket: int, new_sl: float) -> bool:
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": self.symbol,
            "sl": float(new_sl),
            "tp": 0.0,
        }
        res = mt5.order_send(request)
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def _handle_trade_closed(self) -> None:
        """Records trade in CSV, updates daily P&L and console metrics."""
        logger.info(f"Position #{self.active_position_ticket} has closed.")
        # Retrieve deal history for this ticket
        from_time = self.active_trade_info["entry_time"].timestamp() - 60
        to_time = time.time() + 60
        history_deals = mt5.history_deals_get(from_time, to_time)

        pnl = 0.0
        exit_price = 0.0
        exit_time = datetime.now()

        if history_deals:
            for deal in history_deals:
                if deal.magic == config.MAGIC_NUMBER and deal.entry == 1:  # Out deal
                    pnl = deal.profit
                    exit_price = deal.price
                    exit_time = datetime.fromtimestamp(deal.time)

        duration_sec = (exit_time - self.active_trade_info["entry_time"]).total_seconds()
        duration_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60)}s"

        self.daily_pnl += pnl

        # Save to CSV: Date, Direction, Entry, SL, Exit, P&L, Duration
        file_exists = config.TRADES_CSV.exists()
        df_row = pd.DataFrame([{
            "Date": self.active_trade_info["entry_time"].strftime("%Y-%m-%d %H:%M"),
            "Direction": self.active_trade_info["direction"],
            "Entry": self.active_trade_info["entry_price"],
            "SL": self.active_trade_info["initial_sl"],
            "Exit": exit_price,
            "P&L": round(pnl, 2),
            "Duration": duration_str
        }])
        df_row.to_csv(config.TRADES_CSV, mode="a", header=not file_exists, index=False)

        # Print metrics
        self.print_daily_summary()

        # Reset active position
        self.active_position_ticket = None
        self.active_trade_info = None

    def print_daily_summary(self) -> None:
        """Prints current daily metrics to console."""
        print("\n" + "=" * 60)
        print(" GOLD-EMA NY OPEN BOT v1.0 - DAILY PERFORMANCE")
        print("=" * 60)
        print(f" Date           : {date.today()}")
        print(f" Daily P&L      : ${self.daily_pnl:+,.2f}")
        print(f" Trades Today   : {self.trades_today} / {config.MAX_TRADES_PER_DAY}")
        print(f" Max Daily Loss : -${config.MAX_DAILY_LOSS:.2f}")

        # Calculate all-time win rate from CSV if present
        if config.TRADES_CSV.exists():
            df_hist = pd.read_csv(config.TRADES_CSV)
            if len(df_hist) > 0:
                wins = len(df_hist[df_hist['P&L'] > 0])
                win_rate = (wins / len(df_hist)) * 100.0
                total_pnl = df_hist['P&L'].sum()
                print(f" Total Trades   : {len(df_hist)}")
                print(f" Overall WinRate: {win_rate:.2f}% (Wins: {wins}, Losses: {len(df_hist)-wins})")
                print(f" Total Net P&L  : ${total_pnl:+,.2f}")
        print("=" * 60 + "\n")

    def run(self):
        """Main monitoring and trading loop."""
        if not self.initialize_mt5():
            return

        ny_tz = pytz.timezone(config.NY_TIMEZONE)
        logger.info("=" * 70)
        logger.info(" GOLD-EMA NY OPEN BOT v1.0 STARTED")
        logger.info(f" Symbol: {self.symbol} | Timeframe: M5 | Lot: {config.LOT_SIZE}")
        logger.info(f" NY Open Window: 08:00 - 08:05 ET (13:00 UTC / 19:00 BD) | Entry Trigger at 08:05 ET candle close")
        logger.info(f" Max Daily Loss: -${config.MAX_DAILY_LOSS:.2f} | Max Trades/Day: {config.MAX_TRADES_PER_DAY}")
        logger.info(" Press Ctrl+C in terminal to stop gracefully.")
        logger.info("=" * 70)

        trade_executed_today = False

        try:
            while True:
                ny_now = datetime.now(ny_tz)
                today = ny_now.date()

                # Reset daily state on new day
                if self.current_trading_day != today:
                    self.current_trading_day = today
                    self.trades_today = 0
                    self.daily_pnl = 0.0
                    trade_executed_today = False
                    logger.info(f"New trading day initialized: {today} (NY Time)")

                # Weekend / Holiday Check
                if not self.is_market_open(ny_now):
                    time.sleep(30)
                    continue

                # Max Daily Loss Enforcement (-$500)
                if self.daily_pnl <= -config.MAX_DAILY_LOSS:
                    logger.warning(
                        f"Max daily loss of -${config.MAX_DAILY_LOSS:.2f} reached "
                        f"(Current: ${self.daily_pnl:.2f}). Halting trading for today."
                    )
                    time.sleep(60)
                    continue

                # Manage Trailing Stop for any active trade
                if self.active_position_ticket is not None:
                    self.manage_trailing_stop()

                # Check if we already took today's allowed trade
                if self.trades_today >= config.MAX_TRADES_PER_DAY or trade_executed_today:
                    time.sleep(5)
                    continue

                # Check Timing Filter: Run exactly during 08:05:00 - 08:14:59 ET
                if ny_now.hour == config.NY_OPEN_HOUR and config.NY_ENTRY_MINUTE <= ny_now.minute < config.NY_WINDOW_END_MINUTE:
                    logger.info(
                        f"NY Open Window Active! Time: {ny_now.strftime('%H:%M:%S')} ET. "
                        f"Analyzing 08:00-08:05 M5 candle..."
                    )

                    df = self.fetch_m5_rates(n_bars=150)
                    if df is not None:
                        setup = detect_ny_open_setup(df, self.symbol, ny_now)
                        if setup is not None:
                            tick = mt5.symbol_info_tick(self.symbol)
                            entry_price = tick.ask if setup["direction"] == "LONG" else tick.bid

                            placed = self.place_trade_with_trailing(
                                symbol=self.symbol,
                                direction=setup["direction"],
                                entry_price=entry_price,
                                sl_price=setup["sl_price"],
                                lot=config.LOT_SIZE
                            )

                            if placed:
                                trade_executed_today = True
                                logger.info(f"Daily trade complete. Next trade window will be tomorrow at 08:05 ET.")
                        else:
                            trade_executed_today = True  # Setup invalid today, avoid repeating

                time.sleep(1.0)

        except KeyboardInterrupt:
            logger.info("Ctrl+C detected! Stopping bot...")
        finally:
            mt5.shutdown()
            logger.info("Gold-EMA NY Open Bot shutdown cleanly.")


if __name__ == "__main__":
    bot = GoldEMANyOpenBot()
    bot.run()

