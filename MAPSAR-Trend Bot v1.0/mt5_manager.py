"""
=============================================================================
MAPSAR-Trend Bot v1.0 - MetaTrader 5 Bridge
=============================================================================
"""

import logging
import math
from typing import Optional, Dict, Any, List, Tuple
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
        self.logger = logger or logging.getLogger("MAPSAR")
        self.initialized = False
        self.resolved_symbols: Dict[str, str] = {}
        self.symbol_infos: Dict[str, Any] = {}

    def initialize(self) -> bool:
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
        if self.initialized:
            self.logger.info("Terminating MT5 connection...")
            mt5.shutdown()
            self.initialized = False
            self.logger.info("MT5 connection terminated.")

    def resolve_symbol(self, target_key: str) -> Optional[str]:
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
        info = mt5.symbol_info(symbol)
        if info:
            self.symbol_infos[symbol] = info
        return info

    def get_rates(self, symbol: str, timeframe_str: str, n_bars: int = 150) -> Optional[pd.DataFrame]:
        tf = self.TIMEFRAME_MAP.get(timeframe_str.upper())
        if tf is None:
            self.logger.error(f"Unsupported timeframe: {timeframe_str}")
            return None

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is None or len(rates) == 0:
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
        magic: int = 970101,
        comment: str = "MAPSAR-Trend Bot v1.0"
    ) -> Optional[Any]:
        info = self.get_symbol_info(symbol)
        if info is None:
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None

        price = tick.ask if order_type.upper() == "BUY" else tick.bid
        action_type = mt5.ORDER_TYPE_BUY if order_type.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        digits = info.digits
        price = round(price, digits)
        sl = round(sl, digits) if sl > 0 else 0.0
        tp = round(tp, digits) if tp > 0 else 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": action_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": int(magic),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        filling_mode = info.filling_mode
        if filling_mode & 1:
            request["type_filling"] = mt5.ORDER_FILLING_FOK
        elif filling_mode & 2:
            request["type_filling"] = mt5.ORDER_FILLING_IOC
        else:
            request["type_filling"] = mt5.ORDER_FILLING_RETURN

        self.logger.info(
            f"Sending {order_type} order: {volume} lots @ {price} | SL: {sl} | TP: {tp} on {symbol}"
        )
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else str(mt5.last_error())
            self.logger.error(f"Order failed! Reason: {err}")
            return None

        self.logger.info(f"Order executed successfully! Deal #{result.deal}, Order #{result.order}")
        return result

    def modify_position_sltp(self, ticket: int, symbol: str, sl: float, tp: float = 0.0) -> bool:
        info = self.get_symbol_info(symbol)
        digits = info.digits if info else 2
        sl_norm = round(sl, digits)
        tp_norm = round(tp, digits) if tp > 0 else 0.0

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": sl_norm,
            "tp": tp_norm,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return False

        self.logger.info(f"Position #{ticket} SL updated to {sl_norm} successfully.")
        return True

    def close_position(self, position: Any) -> bool:
        symbol = position.symbol
        ticket = position.ticket
        vol = position.volume
        pos_type = position.type

        info = self.get_symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return False

        price = tick.bid if pos_type == mt5.ORDER_TYPE_BUY else tick.ask
        order_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": vol,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": position.magic,
            "comment": "MAPSAR Close/Reversal",
            "type_time": mt5.ORDER_TIME_GTC,
        }

        if info:
            if info.filling_mode & 1:
                request["type_filling"] = mt5.ORDER_FILLING_FOK
            elif info.filling_mode & 2:
                request["type_filling"] = mt5.ORDER_FILLING_IOC
            else:
                request["type_filling"] = mt5.ORDER_FILLING_RETURN

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.logger.info(f"Position #{ticket} closed successfully at {price}.")
            return True
        return False

    def get_open_positions(self, symbol: Optional[str] = None, magic: Optional[int] = None) -> List[Any]:
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if positions is None:
            return []

        filtered = []
        for pos in positions:
            if magic is not None and pos.magic != magic:
                continue
            filtered.append(pos)
        return filtered
