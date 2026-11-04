"""
NY-Open Momentum Bot v1.0 - MetaTrader 5 Manager Module
=======================================================
Robust wrapper for MetaTrader 5 connection, auto-symbol detection,
candle data retrieval, order execution, trailing stop updates, and P&L tracking.
"""

import sys
import logging
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Tuple

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import pytz
import config


class MT5Manager:
    """Encapsulates all MT5 communication and trade management."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.symbol: Optional[str] = None
        self.symbol_info = None
        self.digits: int = 2
        self.point: float = 0.01
        self.index_point_unit: float = config.INDEX_POINT_SIZE
        self.ny_tz = pytz.timezone(config.TIMEZONE_STR)

    def initialize(self) -> bool:
        """Initializes connection to MT5 terminal and verifies account."""
        if mt5 is None:
            self.logger.critical("The 'MetaTrader5' Python package is not installed. Run: pip install MetaTrader5")
            return False

        init_args = {}
        if config.MT5_PATH:
            init_args["path"] = config.MT5_PATH
        if config.MT5_LOGIN:
            init_args["login"] = config.MT5_LOGIN
        if config.MT5_PASSWORD:
            init_args["password"] = config.MT5_PASSWORD
        if config.MT5_SERVER:
            init_args["server"] = config.MT5_SERVER
        if config.MT5_TIMEOUT_MS:
            init_args["timeout"] = config.MT5_TIMEOUT_MS

        self.logger.info("Connecting to MetaTrader 5 terminal...")
        
        # Attempt 1: Attach to currently running MT5 instance
        connected = False
        try:
            connected = mt5.initialize(timeout=config.MT5_TIMEOUT_MS)
        except Exception:
            connected = False

        # Attempt 2: Launch via explicit terminal64.exe path if default attach failed
        if not connected and config.MT5_PATH:
            self.logger.info(f"Attaching with explicit terminal path: {config.MT5_PATH}")
            connected = mt5.initialize(path=config.MT5_PATH, timeout=config.MT5_TIMEOUT_MS)

        if not connected:
            err_code, err_desc = mt5.last_error()
            self.logger.error(f"mt5.initialize() failed. Error Code: {err_code}, Description: {err_desc}")
            return False

        version = mt5.version()
        self.logger.info(f"MT5 Terminal successfully initialized. Version: {version}")

        # Check terminal algorithmic trading permission
        term_info = mt5.terminal_info()
        if term_info and not term_info.trade_allowed:
            self.logger.warning(
                "NOTE: 'Algo Trading' button is currently DISABLED in the MT5 top toolbar! "
                "Please click the 'Algo Trading' button (green icon) in MT5 to enable live order placement."
            )

        # Fetch and display account details
        account = mt5.account_info()
        if account is None:
            self.logger.warning("Could not retrieve MT5 account info. Please check terminal login.")
        else:
            self.logger.info(
                f"Account: #{account.login} | Name: '{account.name}' | "
                f"Balance: {account.balance:.2f} {account.currency} | Equity: {account.equity:.2f} | "
                f"Leverage: 1:{account.leverage} | Server: {account.server}"
            )

        # Initialize all portfolio symbols in Market Watch
        self.initialize_symbols(config.ACTIVE_PAIRS)

        return True

    def initialize_symbols(self, symbols: List[str]):
        """Selects all target portfolio symbols in MT5 Market Watch."""
        for s in symbols:
            if not mt5.symbol_select(s, True):
                self.logger.warning(f"Could not enable symbol '{s}' in Market Watch.")
            else:
                info = mt5.symbol_info(s)
                if info:
                    self.logger.info(
                        f"Portfolio Pair Ready: '{s}' | Digits: {info.digits} | "
                        f"Spread: {info.spread} | Min Lot: {info.volume_min}"
                    )
        # Default active symbol is the first in list
        if symbols:
            self.symbol = symbols[0]
            info = mt5.symbol_info(self.symbol)
            if info:
                self.digits = info.digits
                self.point = info.point

    def detect_and_select_symbol(self) -> bool:
        """
        Auto-detects the active broker symbol for Nasdaq 100
        from the candidate list or user forced symbol.
        """
        candidates = [config.FORCED_SYMBOL] if config.FORCED_SYMBOL else config.SYMBOL_CANDIDATES

        self.logger.info(f"Searching broker symbol list for NAS100 candidates: {candidates}")
        matched_symbol = None

        for cand in candidates:
            if not cand:
                continue
            info = mt5.symbol_info(cand)
            if info is not None:
                matched_symbol = cand
                break

        # Fallback: fuzzy search across all broker symbols if exact match not found
        if not matched_symbol:
            all_symbols = mt5.symbols_get()
            if all_symbols:
                for s in all_symbols:
                    name_upper = s.name.upper()
                    if any(target in name_upper for target in ["NAS100", "US100", "USTEC", "NQ"]):
                        matched_symbol = s.name
                        self.logger.info(f"Fuzzy detected Nasdaq symbol: {matched_symbol}")
                        break

        if not matched_symbol:
            self.logger.error("Could not auto-detect NAS100 symbol from broker. Specify FORCED_SYMBOL in config.py.")
            return False

        # Select symbol in Market Watch
        if not mt5.symbol_select(matched_symbol, True):
            self.logger.error(f"Failed to enable symbol '{matched_symbol}' in Market Watch.")
            return False

        info = mt5.symbol_info(matched_symbol)
        if info is None:
            self.logger.error(f"Cannot get symbol_info for '{matched_symbol}'.")
            return False

        self.symbol = matched_symbol
        self.symbol_info = info
        self.digits = info.digits
        self.point = info.point

        self.logger.info(
            f"Active Symbol: '{self.symbol}' | Digits: {self.digits} | Point: {self.point} | "
            f"Spread: {info.spread} | Trade Mode: {info.trade_mode}"
        )
        return True

    def shutdown(self):
        """Disconnects cleanly from MT5 terminal."""
        if mt5 is not None:
            mt5.shutdown()
            self.logger.info("MT5 connection gracefully terminated.")

    def get_current_tick(self, symbol: str = None) -> Optional[Tuple[float, float]]:
        """Returns (bid, ask) tuple or None if unavailable."""
        sym = symbol or self.symbol
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return None
        return tick.bid, tick.ask

    def get_m5_ny_open_candle(self, ny_date: date, symbol: str = None) -> Optional[Dict]:
        """
        Retrieves the 09:30-09:35 ET M5 candle for the given date and symbol.
        Uses candle UNIX timestamps converted to US/Eastern timezone.
        """
        sym = symbol or self.symbol
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 150)
        if rates is None or len(rates) == 0:
            return None

        target_open_time = time(8, 0)
        target_close_time = time(8, 5)

        profile = config.get_pair_profile(sym)
        point_unit = profile.get("index_point_size", 1.0)

        for rate in reversed(rates):
            dt_utc = datetime.fromtimestamp(rate["time"], tz=pytz.utc)
            dt_ny = dt_utc.astimezone(self.ny_tz)

            if dt_ny.date() == ny_date and dt_ny.time() == target_open_time:
                now_ny = datetime.now(self.ny_tz)
                if now_ny.date() == ny_date and now_ny.time() < target_close_time:
                    return None

                return {
                    "open": float(rate["open"]),
                    "high": float(rate["high"]),
                    "low": float(rate["low"]),
                    "close": float(rate["close"]),
                    "volume": float(rate["tick_volume"]),
                    "time_ny": dt_ny,
                    "range_points": (float(rate["high"]) - float(rate["low"])) / point_unit
                }

        return None

    def get_latest_closed_candle(self, timeframe_name: str, symbol: str = None) -> Optional[Dict]:
        """
        Returns the most recently completed candle for the specified timeframe and symbol.
        """
        sym = symbol or self.symbol
        tf = mt5.TIMEFRAME_M15 if timeframe_name.upper() == "M15" else mt5.TIMEFRAME_M5
        rates = mt5.copy_rates_from_pos(sym, tf, 1, 1)
        if rates is None or len(rates) == 0:
            return None

        rate = rates[0]
        dt_utc = datetime.fromtimestamp(rate["time"], tz=pytz.utc)
        dt_ny = dt_utc.astimezone(self.ny_tz)

        return {
            "time_utc": dt_utc,
            "time_ny": dt_ny,
            "open": float(rate["open"]),
            "high": float(rate["high"]),
            "low": float(rate["low"]),
            "close": float(rate["close"]),
            "volume": float(rate["tick_volume"])
        }

    def _get_filling_mode(self, symbol: str = None) -> int:
        """Determines supported order filling mode for current broker and symbol."""
        sym = symbol or self.symbol
        info = mt5.symbol_info(sym)
        if not info:
            return mt5.ORDER_FILLING_IOC

        fill_flags = info.filling_mode
        if fill_flags & 1:
            return mt5.ORDER_FILLING_IOC
        elif fill_flags & 2:
            return mt5.ORDER_FILLING_FOK
        else:
            return mt5.ORDER_FILLING_RETURN

    def calculate_lot_size(self, sl_distance_points: float, symbol: str = None) -> float:
        """
        Calculates position lot size for the given symbol.
        If USE_DYNAMIC_LOT is True: calculates lots based on RISK_PERCENT of account balance.
        If False: returns fixed config.LOT_SIZE.
        Normalizes lot size according to broker volume constraints (min, step, max).
        """
        sym = symbol or self.symbol
        if not config.USE_DYNAMIC_LOT:
            return self._normalize_lot_size(config.LOT_SIZE, sym)

        account = mt5.account_info()
        if account is None or account.balance <= 0:
            self.logger.warning("Could not read account balance for dynamic lots. Using fixed lot size.")
            return self._normalize_lot_size(config.LOT_SIZE, sym)

        risk_cash = account.balance * (config.RISK_PERCENT / 100.0)

        info = mt5.symbol_info(sym)
        if not info:
            return self._normalize_lot_size(config.LOT_SIZE, sym)

        point_usd = 1.0
        if info.trade_tick_size > 0 and info.trade_tick_value_profit > 0:
            ticks_per_point = 1.0 / info.trade_tick_size
            point_usd = ticks_per_point * info.trade_tick_value_profit

        cost_per_lot = sl_distance_points * point_usd
        if cost_per_lot <= 0:
            return self._normalize_lot_size(config.LOT_SIZE, sym)

        raw_lots = risk_cash / cost_per_lot

        if config.MAX_LOT_OVERRIDE:
            raw_lots = min(raw_lots, config.MAX_LOT_OVERRIDE)

        normalized_lots = self._normalize_lot_size(raw_lots, sym)
        self.logger.info(
            f"DYNAMIC LOT ({sym}): Balance=${account.balance:.2f} | Risk={config.RISK_PERCENT}% (${risk_cash:.2f}) | "
            f"SL Dist={sl_distance_points:.4f} | Lots={normalized_lots}"
        )
        return normalized_lots

    def _normalize_lot_size(self, raw_lots: float, symbol: str = None) -> float:
        """Clamps and snaps raw lot size to broker minimum, maximum, and step size."""
        sym = symbol or self.symbol
        info = mt5.symbol_info(sym)
        if not info:
            return round(raw_lots, 2)

        vol_min = config.MIN_LOT_OVERRIDE or info.volume_min
        vol_max = config.MAX_LOT_OVERRIDE or info.volume_max
        vol_step = info.volume_step

        clamped = max(vol_min, min(vol_max, raw_lots))
        steps = round((clamped - vol_min) / vol_step)
        final_lots = round(vol_min + (steps * vol_step), 2)
        return final_lots

    def open_market_order(
        self,
        order_type_str: str,
        lot_size: float,
        stop_loss: float,
        symbol: str = None,
        magic: int = None
    ) -> Optional[int]:
        """
        Executes Buy or Sell order on the specified symbol.
        No fixed TP is specified (trailing stop captures the trend).
        """
        sym = symbol or self.symbol
        magic_num = magic or config.MAGIC_NUMBER
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            self.logger.error(f"Cannot retrieve current tick for {sym}.")
            return None

        is_buy = (order_type_str.upper() == "BUY")
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        price = tick.ask if is_buy else tick.bid

        # Normalize lot size according to broker volume min/step/max
        info = mt5.symbol_info(sym)
        digits = info.digits if info else 2
        lot_size = self._normalize_lot_size(lot_size, sym)

        price = round(price, digits)
        stop_loss = round(stop_loss, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(lot_size),
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": 0.0,
            "deviation": config.SLIPPAGE,
            "magic": magic_num,
            "comment": f"{config.ORDER_COMMENT} ({sym})",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(sym)
        }

        self.logger.info(
            f"Sending {order_type_str} order on {sym}: Lots={lot_size}, "
            f"Price={price}, SL={stop_loss}, Magic={magic_num}"
        )

        result = mt5.order_send(request)
        if result is None:
            err_code, err_desc = mt5.last_error()
            self.logger.error(f"order_send() returned None. Code: {err_code}, Desc: {err_desc}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error(
                f"Order execution rejected by broker for {sym}! Retcode: {result.retcode}, "
                f"Comment: '{result.comment}'"
            )
            return None

        self.logger.info(
            f"Order successfully filled on {sym}! Ticket: #{result.order}, "
            f"Executed Price: {result.price}, Volume: {result.volume}"
        )
        return result.order

    def modify_position_sl(self, ticket: int, new_sl: float, symbol: str = None) -> bool:
        """Modifies the Stop Loss of an open position for trailing stop."""
        sym = symbol or self.symbol
        info = mt5.symbol_info(sym)
        digits = info.digits if info else 2
        new_sl = round(new_sl, digits)
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": sym,
            "sl": new_sl,
            "tp": 0.0
        }

        result = mt5.order_send(request)
        if result is None:
            err_code, err_desc = mt5.last_error()
            self.logger.error(f"modify_position_sl() returned None. Code: {err_code}, Desc: {err_desc}")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.warning(
                f"Failed to update SL for #{ticket} ({sym}) to {new_sl}. Retcode: {result.retcode}, "
                f"Comment: '{result.comment}'"
            )
            return False

        self.logger.info(f"Trailing Stop updated for position #{ticket} ({sym}) -> New SL: {new_sl}")
        return True

    def get_open_positions(self, symbol: str = None, magic: int = None) -> List[Dict]:
        """Returns active open positions belonging to this bot's Magic Number and Symbol."""
        sym = symbol or self.symbol
        positions = mt5.positions_get(symbol=sym)
        bot_positions = []
        if positions:
            for p in positions:
                # Check magic number if provided, else check if matches any bot magic number
                match_magic = (p.magic == magic) if magic else (p.magic in config.MAGIC_NUMBERS.values() or p.magic == config.MAGIC_NUMBER)
                if match_magic:
                    bot_positions.append({
                        "ticket": p.ticket,
                        "time": p.time,
                        "symbol": p.symbol,
                        "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                        "volume": p.volume,
                        "price_open": p.price_open,
                        "sl": p.sl,
                        "tp": p.tp,
                        "price_current": p.price_current,
                        "profit": p.profit,
                        "magic": p.magic
                    })
        return bot_positions

    def get_daily_deals(self, target_date: date) -> List[Dict]:
        """
        Retrieves all closed deals executed today matching our magic number
        and computes points P&L and currency profit.
        """
        # Define UTC search range for today
        start_utc = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=pytz.utc)
        end_utc = start_utc + timedelta(days=1)

        deals = mt5.history_deals_get(start_utc, end_utc)
        results = []
        if deals:
            for d in deals:
                if d.magic == config.MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT:
                    # Closing deal
                    results.append({
                        "ticket": d.ticket,
                        "order": d.order,
                        "time": d.time,
                        "symbol": d.symbol,
                        "type": "SELL" if d.type == mt5.DEAL_TYPE_BUY else "BUY",
                        "volume": d.volume,
                        "price": d.price,
                        "profit": d.profit,
                        "fee": d.fee,
                        "swap": d.swap
                    })
        return results

    def calculate_daily_pnl(self, target_date: date) -> Tuple[float, float, int]:
        """
        Calculates today's realized profit:
        Returns (total_profit_currency, total_pnl_points, closed_trades_count).
        """
        deals = self.get_daily_deals(target_date)
        total_currency = 0.0
        closed_count = len(deals)

        for d in deals:
            total_currency += (d["profit"] + d.get("fee", 0.0) + d.get("swap", 0.0))

        # Approximate points if lot size is known or derived
        # For NAS100: profit ~= volume * points * point_value_factor
        return total_currency, closed_count

