"""
=============================================================================
NY-Open 12 EMA Trend Bot v1.0 - MetaTrader 5 Manager
=============================================================================
Handles:
- Terminal connection & account status
- Broker symbol alias resolution (e.g. USTECm, XAUUSDm)
- OHLCV M5 candle fetching & pandas formatting
- Market order placement with SL and TP=0.0
- Trailing Stop position modification (TRADE_ACTION_SLTP)
- Volume normalization (volume_min, volume_step, volume_max)
=============================================================================
"""

import math
from datetime import datetime
from typing import Dict, Optional, Tuple, List
import pandas as pd
import pytz
import MetaTrader5 as mt5

import config
from trade_logger import setup_logger


class MT5Manager:
    """Manages all interactions with MetaTrader 5."""

    def __init__(self):
        self.logger = setup_logger("MT5Manager")
        self.is_connected = False
        self.active_symbols: Dict[str, str] = {}  # e.g. {"NAS100": "USTECm", "XAUUSD": "XAUUSDm"}
        self.symbol_infos: Dict[str, mt5.SymbolInfo] = {}
        self.ny_tz = pytz.timezone(config.TIMEZONE_NAME)

    def initialize(self) -> bool:
        """Initializes connection to MT5 terminal and prints account info."""
        self.logger.info("Connecting to MetaTrader 5 terminal...")
        if not mt5.initialize():
            self.logger.error(f"MT5 initialization failed! Error code: {mt5.last_error()}")
            return False

        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            self.logger.error("Failed to query MT5 terminal info.")
            return False

        version = mt5.version()
        self.logger.info(f"MT5 Terminal successfully initialized. Version: {version}")

        # Check Algo Trading master toggle
        if not terminal_info.trade_allowed:
            self.logger.warning(
                "NOTE: 'Algo Trading' button is currently DISABLED in the MT5 top toolbar! "
                "Please click the 'Algo Trading' button (green icon) in MT5 to enable live order placement."
            )

        # Account details
        account = mt5.account_info()
        if account is not None:
            self.logger.info(
                f"Account: #{account.login} | Name: '{account.name}' | "
                f"Balance: {account.balance:.2f} {account.currency} | "
                f"Equity: {account.equity:.2f} | Leverage: 1:{account.leverage} | "
                f"Server: {account.server}"
            )

        self.is_connected = True
        return True

    def resolve_symbols(self) -> Dict[str, str]:
        """
        Discovers broker-specific symbol names for NAS100 and XAUUSD.
        Returns a dictionary mapping target key -> broker symbol (e.g. {'NAS100': 'USTECm', 'XAUUSD': 'XAUUSDm'}).
        """
        if not self.is_connected:
            return {}

        all_symbols = mt5.symbols_get()
        if not all_symbols:
            self.logger.error("Unable to retrieve broker symbol list.")
            return {}

        broker_symbol_names = {s.name.upper(): s.name for s in all_symbols}

        resolved = {}
        for target, candidates in config.CANDIDATE_SYMBOLS.items():
            found_symbol = None
            for cand in candidates:
                cand_upper = cand.upper()
                if cand_upper in broker_symbol_names:
                    found_symbol = broker_symbol_names[cand_upper]
                    break

            if found_symbol:
                # Ensure symbol is selected in Market Watch
                mt5.symbol_select(found_symbol, True)
                sym_info = mt5.symbol_info(found_symbol)
                if sym_info:
                    resolved[target] = found_symbol
                    self.symbol_infos[found_symbol] = sym_info
                    self.logger.info(
                        f"Target '{target}' mapped to broker symbol '{found_symbol}' "
                        f"(Digits: {sym_info.digits}, Point: {sym_info.point}, Min Lot: {sym_info.volume_min})"
                    )
            else:
                self.logger.warning(f"Could not find any broker symbol candidate for target '{target}'")

        self.active_symbols = resolved
        return resolved

    def fetch_ohlcv(self, symbol: str, timeframe=config.TIMEFRAME, num_bars: int = 100) -> Optional[pd.DataFrame]:
        """
        Fetches the latest M5 OHLCV bars and formats into a pandas DataFrame.
        Timestamp converted to New York time.
        """
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars)
        if rates is None or len(rates) == 0:
            self.logger.error(f"Failed to fetch rates for {symbol}. Error: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        # Convert UTC timestamp to NY Time
        df['datetime_utc'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df['datetime_ny'] = df['datetime_utc'].dt.tz_convert(self.ny_tz)
        df.set_index('datetime_ny', inplace=True)
        return df

    def normalize_volume(self, symbol: str, requested_lot: float) -> float:
        """Clamps and steps volume according to broker specifications."""
        sym_info = self.symbol_infos.get(symbol) or mt5.symbol_info(symbol)
        if sym_info is None:
            return requested_lot

        vol_min = sym_info.volume_min
        vol_max = sym_info.volume_max
        vol_step = sym_info.volume_step

        if vol_step <= 0:
            vol_step = 0.01

        steps = round((requested_lot - vol_min) / vol_step)
        adjusted_vol = vol_min + (steps * vol_step)
        adjusted_vol = max(vol_min, min(vol_max, adjusted_vol))

        # Precision rounding
        step_str = f"{vol_step:.8f}".rstrip('0')
        decimals = len(step_str.split('.')[1]) if '.' in step_str else 2
        return round(adjusted_vol, decimals)

    def get_market_quote(self, symbol: str) -> Optional[Tuple[float, float]]:
        """Returns current (bid, ask) quote for symbol."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return tick.bid, tick.ask

    def get_open_position(self, symbol: str, magic: int) -> Optional[Any]:
        """Returns the open position for symbol with given magic number, if any."""
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return None
        for pos in positions:
            if pos.magic == magic:
                return pos
        return None

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        initial_sl: float,
        magic: int,
        comment: str = "NY-12EMA"
    ) -> Optional[mt5.TradeResult]:
        """
        Executes a market order (BUY / SELL) with Stop Loss.
        Take Profit is strictly 0.0 (closed by trailing stop).
        """
        sym_info = self.symbol_infos.get(symbol) or mt5.symbol_info(symbol)
        if sym_info is None:
            self.logger.error(f"Cannot place order: symbol info missing for {symbol}")
            return None

        quote = self.get_market_quote(symbol)
        if quote is None:
            self.logger.error(f"Cannot place order: unable to get current quote for {symbol}")
            return None
        bid, ask = quote

        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        price = ask if direction.upper() == "BUY" else bid

        normalized_vol = self.normalize_volume(symbol, volume)
        digits = sym_info.digits
        price_round = round(price, digits)
        sl_round = round(initial_sl, digits) if initial_sl > 0 else 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": normalized_vol,
            "type": order_type,
            "price": price_round,
            "sl": sl_round,
            "tp": 0.0,  # No Take Profit: Let Trailing Stop ride
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        self.logger.info(
            f"Sending {direction} order: {symbol} | Vol: {normalized_vol} | "
            f"Price: {price_round} | SL: {sl_round} | TP: 0.0 | Magic: {magic}"
        )

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else mt5.last_error()
            self.logger.error(f"Order failed for {symbol}! Result: {result}, Error: {err}")
            return None

        self.logger.info(
            f"Order successfully filled! Ticket: #{result.order} | Price: {result.price} | Volume: {result.volume}"
        )
        return result

    def modify_stop_loss(self, position: Any, new_sl: float) -> bool:
        """
        Updates the Stop Loss of an existing open position (Trailing Stop).
        """
        symbol = position.symbol
        sym_info = self.symbol_infos.get(symbol) or mt5.symbol_info(symbol)
        digits = sym_info.digits if sym_info else 2
        new_sl_rounded = round(new_sl, digits)

        # Do not modify if difference is negligible
        if abs(position.sl - new_sl_rounded) < (sym_info.point if sym_info else 0.001):
            return True

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": position.ticket,
            "sl": new_sl_rounded,
            "tp": position.tp,
        }

        res = mt5.order_send(request)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.warning(
                f"Failed to trail SL on ticket #{position.ticket} ({symbol}) to {new_sl_rounded}. "
                f"Retcode: {getattr(res, 'retcode', None)}, Comment: {getattr(res, 'comment', None)}"
            )
            return False

        self.logger.info(f"Trailing SL updated on #{position.ticket} ({symbol}) -> {new_sl_rounded}")
        return True

    def close_position(self, position: Any, comment: str = "Exit") -> bool:
        """Closes an open position at current market price."""
        symbol = position.symbol
        quote = self.get_market_quote(symbol)
        if quote is None:
            return False
        bid, ask = quote

        close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = bid if position.type == mt5.ORDER_TYPE_BUY else ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": position.ticket,
            "volume": position.volume,
            "type": close_type,
            "price": price,
            "deviation": 20,
            "magic": position.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        res = mt5.order_send(request)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            self.logger.error(f"Failed to close position #{position.ticket}! Retcode: {getattr(res, 'retcode', None)}")
            return False

        self.logger.info(f"Position #{position.ticket} ({symbol}) closed successfully at {price}.")
        return True

    def shutdown(self):
        """Cleanly terminates MT5 terminal connection."""
        if self.is_connected:
            mt5.shutdown()
            self.is_connected = False
            self.logger.info("MT5 connection terminated.")

