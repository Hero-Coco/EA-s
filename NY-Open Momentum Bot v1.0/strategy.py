"""
NY-Open Momentum Bot v1.0 - Core Strategy Engine
=================================================
Implements the New York Open Opening Range Breakout (ORB) momentum strategy:
1. 09:30-09:35 ET 5-minute range calculation (Breakout Box).
2. Volatility filter (Range >= 30 points).
3. Candle close breakout entry (Long above Range High / Short below Range Low).
4. Initial Stop Loss at opposite side of box +/- 10 points buffer.
5. Trailing Stop (+50 pts profit trigger, 30 pts trail distance, 5 pts step).
6. Max daily loss limit (-200 points) and 1 trade per day constraint.
"""

import logging
from datetime import datetime, date, time
from typing import Optional, Dict

import pytz
import config
from holidays_filter import is_trading_day
from mt5_manager import MT5Manager
from trade_logger import TradeHistoryRecorder


class NYOpenMomentumStrategy:
    """Manages the lifecycle, execution, and risk control of the NY Open Momentum strategy."""

    def __init__(
        self,
        mt5_mgr: MT5Manager,
        recorder: TradeHistoryRecorder,
        logger: logging.Logger,
        symbol: str = None,
        magic_number: int = None
    ):
        self.mt5 = mt5_mgr
        self.recorder = recorder
        self.logger = logger
        self.symbol = symbol or mt5_mgr.symbol or "USTECm"
        self.magic = magic_number or config.MAGIC_NUMBERS.get(self.symbol, config.MAGIC_NUMBER)
        self.profile = config.get_pair_profile(self.symbol)
        self.point_unit = self.profile.get("index_point_size", 1.0)
        self.ny_tz = pytz.timezone(config.TIMEZONE_STR)

        # State tracking variables (reset daily)
        self.active_date: Optional[date] = None
        self.is_holiday_or_weekend: bool = False
        self.holiday_reason: str = ""

        # Breakout Box State
        self.range_calculated: bool = False
        self.range_high: float = 0.0
        self.range_low: float = 0.0
        self.range_size: float = 0.0
        self.range_valid: bool = False

        # Daily Trade State
        self.trades_count_today: int = 0
        self.daily_loss_points: float = 0.0
        self.daily_halted: bool = False

        # Active Position Tracking
        self.active_ticket: Optional[int] = None
        self.position_direction: Optional[str] = None
        self.entry_price: float = 0.0
        self.initial_sl: float = 0.0
        self.current_sl: float = 0.0
        self.trailing_activated: bool = False
        self.last_trailing_update_price: float = 0.0
        self.last_evaluated_candle_time: Optional[datetime] = None

    def reset_daily_state_if_needed(self, current_ny_dt: datetime):
        """Resets the intraday state variables whenever a new calendar day begins."""
        today = current_ny_dt.date()
        if self.active_date != today:
            self.active_date = today
            self.range_calculated = False
            self.range_high = 0.0
            self.range_low = 0.0
            self.range_size = 0.0
            self.range_valid = False
            self.trades_count_today = 0
            self.daily_loss_points = 0.0
            self.daily_halted = False
            self.last_evaluated_candle_time = None

            # Verify if today is an active trading day
            is_valid, reason = is_trading_day(today)
            self.is_holiday_or_weekend = not is_valid
            self.holiday_reason = reason

            self.logger.info("=" * 70)
            self.logger.info(f"NEW TRADING DAY INITIALIZED: {today} (NY Time)")
            self.logger.info(f"Market Status: {'OPEN' if is_valid else 'CLOSED'} ({reason})")
            self.logger.info("=" * 70)

    def on_tick(self):
        """
        Main decision cycle invoked on each loop tick.
        Evaluates session timing, range formation, breakout signals, and trailing stops.
        """
        now_ny = datetime.now(self.ny_tz)
        self.reset_daily_state_if_needed(now_ny)

        # 1. Weekend & Holiday Guard
        if self.is_holiday_or_weekend:
            return

        # 2. Check and manage any existing open position
        self.manage_active_position(now_ny)

        # 3. Daily Loss and Trade Limit Guards
        if self.daily_halted:
            return

        if self.trades_count_today >= config.MAX_TRADES_PER_DAY:
            return

        # 4. Session Timing Filter
        now_time = now_ny.time()

        # Phase A: Pre-Market (Before 09:30 ET)
        if now_time < config.NY_OPEN_TIME:
            return

        # Phase B: 09:30 - 09:35 ET: Opening 5-Minute Candle Forming
        if config.NY_OPEN_TIME <= now_time < config.NY_RANGE_END_TIME:
            return

        # Phase C: 09:35 ET: Calculate 5-Minute Range Box
        if not self.range_calculated:
            self.calculate_5min_range(now_ny)
            return

        # Phase D: Check if Breakout Box was valid (volatility filter)
        if not self.range_valid:
            return

        # Phase E: Breakout Monitoring Window (09:35 - 11:00 ET)
        if config.TRADE_WINDOW_START <= now_time <= config.TRADE_WINDOW_END:
            if self.active_ticket is None and self.trades_count_today < config.MAX_TRADES_PER_DAY:
                self.evaluate_breakout_entry(now_ny)
        else:
            # Past trade entry window for today
            pass

    def calculate_5min_range(self, now_ny: datetime):
        """
        Extracts the 09:30-09:35 M5 candle to establish the Breakout Box.
        Validates minimum range threshold using the asset profile.
        """
        candle = self.mt5.get_m5_ny_open_candle(now_ny.date(), symbol=self.symbol)
        if candle is None:
            # Candle data might not have synced yet from broker; retry on next tick
            return

        min_range = self.profile["min_range_points"]

        self.range_high = candle["high"]
        self.range_low = candle["low"]
        self.range_size = (self.range_high - self.range_low) / self.point_unit
        self.range_calculated = True

        self.logger.info("*" * 65)
        self.logger.info(
            f"NY OPEN RANGE ESTABLISHED on {self.symbol}: High={self.range_high:.4f}, "
            f"Low={self.range_low:.4f}, Range={self.range_size:.4f} points"
        )

        # Check minimum range filter
        if self.range_size < min_range:
            self.range_valid = False
            self.daily_halted = True
            self.logger.warning(
                f"VOLATILITY FILTER: 5-min range ({self.range_size:.4f}) < {min_range:.4f} threshold. "
                f"Low volatility day on {self.symbol} - NO TRADES ALLOWED TODAY."
            )
        else:
            self.range_valid = True
            self.logger.info(
                f"BREAKOUT BOX ARMED ({self.symbol}): Ready for {config.EXECUTION_TIMEFRAME_NAME} candle close outside "
                f"[{self.range_low:.4f} - {self.range_high:.4f}]"
            )
        self.logger.info("*" * 65)

    def evaluate_breakout_entry(self, now_ny: datetime):
        """
        Inspects the most recent completed candle close.
        Triggers entry strictly on candle close breaking above/below the 5-min range.
        """
        closed_candle = self.mt5.get_latest_closed_candle(config.EXECUTION_TIMEFRAME_NAME, symbol=self.symbol)
        if closed_candle is None:
            return

        candle_close_time = closed_candle["time_ny"]

        # Prevent re-evaluating the exact same candle repeatedly
        if self.last_evaluated_candle_time == candle_close_time:
            return

        # Ensure the closed candle occurred during or after the NY open (09:30 ET)
        if candle_close_time.time() < config.NY_OPEN_TIME:
            return

        close_price = closed_candle["close"]
        self.last_evaluated_candle_time = candle_close_time

        sl_buffer = self.profile["sl_buffer_points"]

        # Check Long Breakout (Close strictly ABOVE 5-min Range High)
        if close_price > self.range_high:
            self.logger.info(
                f"LONG ENTRY TRIGGERED on {self.symbol}: {config.EXECUTION_TIMEFRAME_NAME} candle closed at {close_price} "
                f"(ABOVE Range High {self.range_high})"
            )
            # Stop Loss: Opposite side of box (Range Low) minus buffer
            sl = self.range_low - (sl_buffer * self.point_unit)
            self.execute_entry("BUY", sl, close_price)

        # Check Short Breakout (Close strictly BELOW 5-min Range Low)
        elif close_price < self.range_low:
            self.logger.info(
                f"SHORT ENTRY TRIGGERED on {self.symbol}: {config.EXECUTION_TIMEFRAME_NAME} candle closed at {close_price} "
                f"(BELOW Range Low {self.range_low})"
            )
            # Stop Loss: Opposite side of box (Range High) plus buffer
            sl = self.range_high + (sl_buffer * self.point_unit)
            self.execute_entry("SELL", sl, close_price)

    def execute_entry(self, direction: str, initial_sl: float, signal_price: float):
        """Calculates lot size (dynamic or fixed) and sends market order to MT5."""
        sl_distance_points = abs(signal_price - initial_sl) / self.point_unit
        calculated_lots = self.mt5.calculate_lot_size(sl_distance_points, symbol=self.symbol)

        ticket = self.mt5.open_market_order(
            order_type_str=direction,
            lot_size=calculated_lots,
            stop_loss=initial_sl,
            symbol=self.symbol,
            magic=self.magic
        )

        if ticket is not None:
            self.active_ticket = ticket
            self.position_direction = direction
            self.active_lots = calculated_lots
            self.initial_sl = initial_sl
            self.current_sl = initial_sl
            self.entry_price = signal_price
            self.trailing_activated = False
            self.last_trailing_update_price = signal_price
            self.trades_count_today += 1

            self.logger.info(
                f"TRADE ENTERED: #{ticket} {direction} {calculated_lots} lots on {self.mt5.symbol} | "
                f"Initial SL={initial_sl:.2f} (Dist: {sl_distance_points:.2f} pts) | "
                f"Trades Today: {self.trades_count_today}/{config.MAX_TRADES_PER_DAY}"
            )
        else:
            self.logger.error(f"Failed to enter {direction} trade. Will retry if valid conditions persist.")

    def manage_active_position(self, now_ny: datetime):
        """
        Monitors open positions, manages trailing stop logic,
        and records exits to CSV when a trade closes.
        """
        open_positions = self.mt5.get_open_positions(symbol=self.symbol, magic=self.magic)

        # If we previously had an active ticket, but it's no longer open -> position closed!
        if self.active_ticket is not None:
            matching = [p for p in open_positions if p["ticket"] == self.active_ticket]
            if not matching:
                self.handle_position_closure(now_ny)
                return

        # If no tracked position, check if any open position exists with our magic number
        if not open_positions:
            self.active_ticket = None
            return

        pos = open_positions[0]
        self.active_ticket = pos["ticket"]
        self.position_direction = pos["type"]
        self.current_sl = pos["sl"]

        # Trailing Stop Management
        self.apply_trailing_stop(pos)

    def apply_trailing_stop(self, pos: Dict):
        """
        Executes trailing stop rules:
        - Trigger: Trade reaches trail_trigger profit.
        - Distance: Trail trail_distance behind current price.
        - Step: Update SL every trail_step points as price moves in favor.
        """
        tick = self.mt5.get_current_tick(symbol=self.symbol)
        if tick is None:
            return

        bid, ask = tick
        entry = pos["price_open"]
        is_buy = (pos["type"] == "BUY")
        current_price = bid if is_buy else ask

        # Calculate profit in index points
        if is_buy:
            profit_points = (current_price - entry) / self.point_unit
        else:
            profit_points = (entry - current_price) / self.point_unit

        trail_trigger = self.profile["trailing_trigger_points"]
        trail_distance = self.profile["trailing_distance_points"]
        trail_step = self.profile["trailing_step_points"]

        # Check activation threshold
        if profit_points >= trail_trigger:
            if not self.trailing_activated:
                self.trailing_activated = True
                self.last_trailing_update_price = current_price
                self.logger.info(
                    f"TRAILING STOP ACTIVATED on #{pos['ticket']} ({self.symbol})! "
                    f"Profit: +{profit_points:.4f} >= {trail_trigger:.4f} threshold."
                )

            # Compute candidate new Stop Loss
            if is_buy:
                proposed_sl = current_price - (trail_distance * self.point_unit)
                # Check step increment
                if proposed_sl > (self.current_sl + (trail_step * self.point_unit)):
                    if self.mt5.modify_position_sl(pos["ticket"], proposed_sl, symbol=self.symbol):
                        self.current_sl = proposed_sl
                        self.last_trailing_update_price = current_price
            else:
                proposed_sl = current_price + (trail_distance * self.point_unit)
                # Check step decrement for Sell
                if proposed_sl < (self.current_sl - (trail_step * self.point_unit)):
                    if self.mt5.modify_position_sl(pos["ticket"], proposed_sl, symbol=self.symbol):
                        self.current_sl = proposed_sl
                        self.last_trailing_update_price = current_price

    def handle_position_closure(self, now_ny: datetime):
        """Processes trade outcome, updates daily P&L, checks daily loss limit, and writes CSV."""
        closed_ticket = self.active_ticket
        self.logger.info(f"Position #{closed_ticket} ({self.symbol}) has closed.")

        # Retrieve deals from MT5 history to get exact exit price and profit
        deals = self.mt5.get_daily_deals(now_ny.date())
        matching_deals = [d for d in deals if d["order"] == closed_ticket or d["ticket"] == closed_ticket]

        exit_price = 0.0
        profit_currency = 0.0
        if matching_deals:
            deal = matching_deals[-1]
            exit_price = deal["price"]
            profit_currency = deal["profit"] + deal.get("fee", 0.0) + deal.get("swap", 0.0)
        else:
            tick = self.mt5.get_current_tick(symbol=self.symbol)
            exit_price = tick[0] if tick else self.entry_price

        # Calculate realized points P&L
        if self.position_direction == "BUY":
            pnl_points = (exit_price - self.entry_price) / self.point_unit
        else:
            pnl_points = (self.entry_price - exit_price) / self.point_unit

        exit_reason = "Trailing Stop" if self.trailing_activated else "Initial Stop Loss"

        self.logger.info("=" * 65)
        self.logger.info(
            f"TRADE RESULT #{closed_ticket} ({self.symbol}): {self.position_direction} | Entry: {self.entry_price:.4f} | "
            f"Exit: {exit_price:.4f} | Points P&L: {pnl_points:+.2f} | Currency: ${profit_currency:+.2f}"
        )
        self.logger.info(f"Exit Reason: {exit_reason}")
        self.logger.info("=" * 65)

        # Record to CSV
        self.recorder.record_trade(
            trade_id=closed_ticket,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol=self.symbol,
            action=self.position_direction,
            lots=getattr(self, "active_lots", config.LOT_SIZE),
            entry_price=self.entry_price,
            initial_sl=self.initial_sl,
            exit_price=exit_price,
            close_time=now_ny.strftime("%Y-%m-%d %H:%M:%S ET"),
            pnl_points=pnl_points,
            pnl_currency=profit_currency,
            exit_reason=exit_reason,
            magic=self.magic
        )

        # Track daily loss in points
        if pnl_points < 0:
            self.daily_loss_points += abs(pnl_points)
            self.logger.warning(
                f"Daily realized loss accumulated: -{self.daily_loss_points:.2f} points "
                f"(Max Allowed: -{config.MAX_DAILY_LOSS_POINTS:.2f} pts)"
            )
            if self.daily_loss_points >= config.MAX_DAILY_LOSS_POINTS:
                self.daily_halted = True
                self.logger.critical(
                    f"MAX DAILY LOSS LIMIT HIT (-{self.daily_loss_points:.2f} pts >= -{config.MAX_DAILY_LOSS_POINTS:.2f} pts)! "
                    f"HALTING ALL TRADING FOR THE REST OF TODAY."
                )

        # Reset active tracking state
        self.active_ticket = None
        self.position_direction = None
        self.entry_price = 0.0
        self.initial_sl = 0.0
        self.current_sl = 0.0
        self.trailing_activated = False

        # Print updated daily summary
        self.print_daily_summary(now_ny)

    def print_daily_summary(self, now_ny: datetime):
        """Displays formatted daily P&L and status in the console."""
        currency_pnl, deal_count = self.mt5.calculate_daily_pnl(now_ny.date())
        self.logger.info("-" * 65)
        self.logger.info(f"DAILY P&L SUMMARY [{now_ny.strftime('%Y-%m-%d ET')} - {self.symbol}]:")
        self.logger.info(f"  Closed Trades Today: {deal_count}")
        self.logger.info(f"  Realized Points Loss: -{self.daily_loss_points:.2f} pts")
        self.logger.info(f"  Net Currency Profit: ${currency_pnl:+.2f}")
        self.logger.info(f"  Trading Allowed Remainder of Today: {'NO' if self.daily_halted else 'YES'}")
        self.logger.info("-" * 65)


class PortfolioStrategyManager:
    """Coordinates simultaneous execution across multiple portfolio pairs."""

    def __init__(
        self,
        mt5_mgr: MT5Manager,
        recorder: TradeHistoryRecorder,
        logger: logging.Logger,
        pairs: list = None
    ):
        self.mt5 = mt5_mgr
        self.recorder = recorder
        self.logger = logger
        self.pairs = pairs or config.ACTIVE_PAIRS
        self.strategies = {}

        for p in self.pairs:
            magic = config.MAGIC_NUMBERS.get(p, config.MAGIC_NUMBER)
            self.strategies[p] = NYOpenMomentumStrategy(
                mt5_mgr=self.mt5,
                recorder=self.recorder,
                logger=self.logger,
                symbol=p,
                magic_number=magic
            )
            self.logger.info(f"Initialized strategy instance for {p} (Magic: {magic})")

    def on_tick(self):
        """Executes on_tick on all managed symbol strategies."""
        for sym, strat in self.strategies.items():
            try:
                strat.on_tick()
            except Exception as e:
                self.logger.error(f"Error executing on_tick for {sym}: {e}")

