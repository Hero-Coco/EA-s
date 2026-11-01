"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - MetaTrader 5 Manager
=============================================================================
Handles:
- Terminal connection & account status
- Broker symbol alias resolution (IN50m, XAUUSDm, BTCUSDm)
- M5 OHLCV bar fetching & pandas formatting
- Market order placement with FVG Stop Loss and Liquidity Take Profit
- Volume normalization (volume_min, volume_step, volume_max)
=============================================================================
"""

from typing import Dict, Optional, Tuple, List, Any
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
        self.active_symbols: Dict[str, str] = {}
        self.symbol_infos: Dict[str, mt5.SymbolInfo] = {}

    def initialize(self) -> bool:
        """Initializes connection to MT5 terminal."""
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

        if not terminal_info.trade_allowed:
            self.logger.warning(
                "NOTE: 'Algo Trading' button is currently DISABLED in the MT5 top toolbar! "
                "Please click the 'Algo Trading' button (green icon) in MT5 to enable live order placement."
            )

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
        Discovers broker-specific symbol names for NIFTY, XAUUSD, and BTCUSD.
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

    def fetch_ohlcv(self, symbol: str, timeframe=config.TIMEFRAME, num_bars: int = 150) -> Optional[pd.DataFrame]:
        """
        Fetches the latest M5 OHLCV bars and formats into a pandas DataFrame.
        """
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars)
        if rates is None or len(rates) == 0:
            self.logger.error(f"Failed to fetch rates for {symbol}. Error: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df['datetime'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('datetime', inplace=True)
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
        """Returns open position for symbol with given magic number, if any."""
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return None
        for pos in positions:
            if pos.magic == magic:
                return pos
        return None

    def place_smc_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl_price: float,
        tp_price: float,
        magic: int,
        comment: str = "SMC-FVG"
    ) -> Optional[Any]:
        """
        Executes a market order (BUY / SELL) with predefined Stop Loss and Take Profit.
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
        sl_round = round(sl_price, digits)
        tp_round = round(tp_price, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": normalized_vol,
            "type": order_type,
            "price": price_round,
            "sl": sl_round,
            "tp": tp_round,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        self.logger.info(
            f"Sending SMC {direction} order: {symbol} | Vol: {normalized_vol} | "
            f"Price: {price_round} | SL: {sl_round} | TP: {tp_round} | Magic: {magic}"
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

    def shutdown(self):
        """Cleanly terminates MT5 terminal connection."""
        if self.is_connected:
            mt5.shutdown()
            self.is_connected = False
            self.logger.info("MT5 connection terminated.")

