"""
=============================================================================
NQ-Precision ORB Bot v1.0 - MetaTrader 5 Bridge
=============================================================================
Robust MT5 communication wrapper with automatic symbol resolving, volume
normalization, dynamic lot sizing, position recovery, and order management.
=============================================================================
"""

import logging
import math
from typing import Optional, Dict, Any, List
import pandas as pd
import MetaTrader5 as mt5

import config


class MT5Manager:
    """Manages the MT5 terminal connection, data copying, and trade execution."""

    TIMEFRAME_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("NQPrecisionORB")
        self.initialized = False
        self.resolved_symbols: Dict[str, str] = {}
        self.symbol_infos: Dict[str, Any] = {}

    def initialize(self) -> bool:
        """Initializes terminal connection and logs account details."""
        if self.initialized:
            return True

        self.logger.info("Connecting to MetaTrader 5 terminal...")
        if not mt5.initialize():
            self.logger.error(f"MT5 initialization failed. Error: {mt5.last_error()}")
            return False

        version = mt5.version()
        self.logger.info(f"MT5 Terminal successfully initialized. Version: {version}")

        account_info = mt5.account_info()
        if account_info is None:
            self.logger.error(f"Failed to fetch account info. Error: {mt5.last_error()}")
            return False

        self.logger.info(
            f"Account: #{account_info.login} | Name: '{account_info.name}' | "
            f"Balance: {account_info.balance:.2f} {account_info.currency} | "
            f"Equity: {account_info.equity:.2f} | Server: {account_info.server}"
        )
        self.initialized = True
        return True

    def shutdown(self):
        """Disconnects cleanly from the MT5 terminal."""
        if self.initialized:
            self.logger.info("Terminating MT5 connection...")
            mt5.shutdown()
            self.initialized = False
            self.logger.info("MT5 connection terminated.")

    def resolve_symbol(self, target_key: str) -> Optional[str]:
        """Resolves broker-specific symbol name (e.g. USTECm for USTEC)."""
        if target_key in self.resolved_symbols:
            return self.resolved_symbols[target_key]

        profile = config.TARGET_PROFILES.get(target_key)
        if not profile:
            self.logger.error(f"No profile defined for target '{target_key}'")
            return None

        candidates = profile["broker_symbol_candidates"]
        for sym in candidates:
            info = mt5.symbol_info(sym)
            if info is not None:
                if not info.visible:
                    if not mt5.symbol_select(sym, True):
                        self.logger.warning(f"Could not enable '{sym}' in MarketWatch")
                        continue
                self.resolved_symbols[target_key] = sym
                self.symbol_infos[sym] = info
                self.logger.info(
                    f"Target '{target_key}' mapped to broker symbol '{sym}' "
                    f"(Digits: {info.digits}, Point: {info.point}, Min Lot: {info.volume_min})"
                )
                return sym

        self.logger.error(f"Could not find any matching broker symbol for target '{target_key}'")
        return None

    def get_symbol_info(self, symbol: str) -> Optional[Any]:
        """Returns refreshed symbol info object."""
        info = mt5.symbol_info(symbol)
        if info:
            self.symbol_infos[symbol] = info
        return info

    def get_rates(self, symbol: str, timeframe_str: str = config.TIMEFRAME, n_bars: int = 200) -> Optional[pd.DataFrame]:
        """Fetches recent bars from MT5 and returns a pandas DataFrame."""
        tf = self.TIMEFRAME_MAP.get(timeframe_str.upper(), mt5.TIMEFRAME_M1)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is None or len(rates) == 0:
            self.logger.warning(f"Failed to fetch rates for {symbol}. Error: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def calculate_lot_size(
        self,
        symbol: str,
        sl_distance_price: float,
        target_key: str
    ) -> float:
        """
        Calculates dynamic lot size based on account balance/equity risk percentage.
        Falls back to default profile lot size if dynamic sizing is disabled.
        """
        profile = config.TARGET_PROFILES.get(target_key, {})
        fallback_lot = profile.get("fallback_lot", 0.01)

        info = self.get_symbol_info(symbol)
        if info is None:
            return fallback_lot

        vol_min = info.volume_min
        vol_max = info.volume_max
        vol_step = info.volume_step if info.volume_step > 0 else 0.01

        if not config.USE_DYNAMIC_LOT:
            return max(vol_min, min(fallback_lot, vol_max))

        account = mt5.account_info()
        if account is None or account.equity < config.MIN_BALANCE_THRESHOLD:
            self.logger.warning("Account equity too low for dynamic sizing; using min lot.")
            return vol_min

        risk_amount = account.equity * (config.RISK_PERCENT / 100.0)

        if sl_distance_price <= 0:
            return fallback_lot

        tick_size = info.trade_tick_size if info.trade_tick_size > 0 else info.point
        tick_value = info.trade_tick_value if info.trade_tick_value > 0 else 1.0

        ticks_at_risk = sl_distance_price / tick_size
        cost_per_lot = ticks_at_risk * tick_value

        if cost_per_lot <= 0:
            return fallback_lot

        calculated_lot = risk_amount / cost_per_lot

        # Normalization
        steps = math.floor(calculated_lot / vol_step)
        normalized_lot = steps * vol_step
        normalized_lot = max(vol_min, min(normalized_lot, vol_max))
        normalized_lot = round(normalized_lot, 2)

        return normalized_lot

    def open_position(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        sl: float = 0.0,
        tp: float = 0.0,
        magic: int = 0,
        comment: str = "NQ-Precision ORB"
    ) -> Optional[Any]:
        """Sends market order deal request to MT5."""
        info = self.get_symbol_info(symbol)
        if not info:
            self.logger.error(f"Cannot execute trade: Symbol info missing for '{symbol}'")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            self.logger.error(f"Cannot execute trade: Tick info missing for '{symbol}'")
            return None

        digits = info.digits
        is_buy = (order_type.upper() == "BUY")
        action_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        price = tick.ask if is_buy else tick.bid

        # Check filling mode
        filling_mode = mt5.ORDER_FILLING_IOC
        if info.filling_mode & mt5.ORDER_FILLING_IOC:
            filling_mode = mt5.ORDER_FILLING_IOC
        elif info.filling_mode & mt5.ORDER_FILLING_FOK:
            filling_mode = mt5.ORDER_FILLING_FOK
        elif info.filling_mode & mt5.ORDER_FILLING_RETURN:
            filling_mode = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": action_type,
            "price": round(price, digits),
            "sl": round(sl, digits) if sl > 0 else 0.0,
            "tp": round(tp, digits) if tp > 0 else 0.0,
            "deviation": 20,
            "magic": int(magic),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        self.logger.info(
            f"Sending Order: {order_type} {volume} {symbol} @ {price:.{digits}f} "
            f"| SL: {sl:.{digits}f} | TP: {tp:.{digits}f} | Magic: {magic}"
        )
        res = mt5.order_send(request)
        if res is None:
            self.logger.error(f"Order failed: mt5.order_send() returned None. Error: {mt5.last_error()}")
            return None

        if res.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error(f"Order rejected: Code={res.retcode}, Description={res.comment}")
            return None

        self.logger.info(f"Order FILLED: #{res.order} {order_type} {volume} {symbol} @ {res.price}")
        return res

    def close_position(self, position: Any) -> bool:
        """Closes an active position at current market price."""
        symbol = position.symbol
        info = self.get_symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not info or not tick:
            return False

        digits = info.digits
        is_buy = (position.type == 0)
        action_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price = tick.bid if is_buy else tick.ask

        filling_mode = mt5.ORDER_FILLING_IOC
        if info.filling_mode & mt5.ORDER_FILLING_IOC:
            filling_mode = mt5.ORDER_FILLING_IOC
        elif info.filling_mode & mt5.ORDER_FILLING_FOK:
            filling_mode = mt5.ORDER_FILLING_FOK
        elif info.filling_mode & mt5.ORDER_FILLING_RETURN:
            filling_mode = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": position.ticket,
            "volume": position.volume,
            "type": action_type,
            "price": round(price, digits),
            "deviation": 20,
            "magic": position.magic,
            "comment": "NQ-ORB Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        res = mt5.order_send(request)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            self.logger.info(f"Position #{position.ticket} successfully closed @ {price}")
            return True

        self.logger.error(f"Failed to close #{position.ticket}: {res.comment if res else mt5.last_error()}")
        return False

    def get_open_positions(self, symbol: str, magic: int) -> List[Any]:
        """Returns all open positions matching symbol and magic number."""
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return []
        return [p for p in positions if p.magic == magic]
