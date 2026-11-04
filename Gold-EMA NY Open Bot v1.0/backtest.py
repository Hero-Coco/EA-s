"""
=============================================================================
Gold-EMA NY Open Bot v1.0 - Historical Backtest Engine
=============================================================================
Simulates the exact NY Open 5-Min Candle + 50 EMA Confluence Strategy
across historical MT5 M5 data for XAUUSD.
=============================================================================
"""

import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
import pytz
import MetaTrader5 as mt5

import config
from bot import calculate_ema

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Gold_EMA_Backtest")


class GoldEMABacktester:
    def __init__(self, initial_balance: float = 1000.0, n_bars: int = 15000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.n_bars = n_bars
        self.trades: List[Dict[str, Any]] = []

    def run(self) -> Optional[pd.DataFrame]:
        logger.info("Connecting to MT5 to fetch historical M5 Gold candles...")
        if not mt5.initialize():
            logger.error("Failed to initialize MT5.")
            return None

        # Resolve symbol
        symbol = None
        for sym in config.SYMBOL_CANDIDATES:
            if mt5.symbol_info(sym) is not None:
                symbol = sym
                break

        if not symbol:
            logger.error("No valid Gold symbol found.")
            mt5.shutdown()
            return None

        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, self.n_bars)
        mt5.shutdown()

        if rates is None or len(rates) == 0:
            logger.error("Could not fetch historical rates.")
            return None

        df = pd.DataFrame(rates)
        df['time_utc'] = pd.to_datetime(df['time'], unit='s', utc=True)
        # Convert UTC to US/Eastern timezone
        df['time_ny'] = df['time_utc'].dt.tz_convert(config.NY_TIMEZONE)
        df['ema50'] = calculate_ema(df, config.EMA_PERIOD)

        logger.info(
            f"Loaded {len(df)} M5 bars from {df['time_ny'].iloc[0].strftime('%Y-%m-%d')} "
            f"to {df['time_ny'].iloc[-1].strftime('%Y-%m-%d')} (NY Time)."
        )

        min_range = config.MIN_CANDLE_RANGE_POINTS * config.POINT_USD_VALUE
        sl_buffer = config.SL_BUFFER_POINTS * config.POINT_USD_VALUE
        trail_trigger = config.TRAILING_TRIGGER_POINTS * config.POINT_USD_VALUE
        trail_dist = config.TRAILING_DISTANCE_POINTS * config.POINT_USD_VALUE
        trail_step = config.TRAILING_STEP_POINTS * config.POINT_USD_VALUE
        lot = config.LOT_SIZE

        # Identify days with a 09:30 candle
        df['date'] = df['time_ny'].dt.date
        unique_dates = df['date'].unique()

        logger.info(f"Scanning {len(unique_dates)} trading days for 08:00 NY Open candles...")

        for trading_date in unique_dates:
            day_candles = df[df['date'] == trading_date]
            # Find the 08:00-08:05 candle (Forex/Gold NY Open)
            open_candle_mask = (day_candles['time_ny'].dt.hour == 8) & (day_candles['time_ny'].dt.minute == 0)
            if not open_candle_mask.any():
                continue

            open_idx = day_candles[open_candle_mask].index[0]
            candle = df.loc[open_idx]
            c_high = candle['high']
            c_low = candle['low']
            c_close = candle['close']
            ema_val = candle['ema50']

            if pd.isna(ema_val):
                continue

            # Volatility range filter
            candle_range = c_high - c_low
            if candle_range < min_range:
                continue

            # Signal
            if c_close > ema_val:
                direction = "LONG"
                initial_sl = c_low - sl_buffer
            elif c_close < ema_val:
                direction = "SHORT"
                initial_sl = c_high + sl_buffer
            else:
                continue

            # Entry at next candle open (09:35 candle)
            if open_idx + 1 >= len(df):
                break

            entry_bar = df.loc[open_idx + 1]
            entry_price = entry_bar['open']
            entry_time = entry_bar['time_ny']

            # Simulate forward intraday trade
            current_sl = initial_sl
            exit_price = None
            exit_time = None
            exit_reason = ""

            # Check next bars up to 6 hours (72 M5 bars)
            max_bars_ahead = min(72, len(df) - (open_idx + 1))
            for k in range(1, max_bars_ahead):
                future_bar = df.loc[open_idx + 1 + k]

                if direction == "LONG":
                    # Check SL
                    if future_bar['low'] <= current_sl:
                        exit_price = current_sl
                        exit_time = future_bar['time_ny']
                        exit_reason = "Stop Loss Hit"
                        break

                    # Check Trailing Stop Update
                    profit = future_bar['high'] - entry_price
                    if profit >= trail_trigger:
                        new_sl = future_bar['high'] - trail_dist
                        if new_sl > current_sl + trail_step:
                            current_sl = new_sl

                elif direction == "SHORT":
                    # Check SL
                    if future_bar['high'] >= current_sl:
                        exit_price = current_sl
                        exit_time = future_bar['time_ny']
                        exit_reason = "Stop Loss Hit"
                        break

                    # Check Trailing Stop Update
                    profit = entry_price - future_bar['low']
                    if profit >= trail_trigger:
                        new_sl = future_bar['low'] + trail_dist
                        if new_sl < current_sl - trail_step:
                            current_sl = new_sl

            # If still open at 6 hours, close at market
            if exit_price is None:
                last_bar = df.loc[open_idx + max_bars_ahead]
                exit_price = last_bar['close']
                exit_time = last_bar['time_ny']
                exit_reason = "6-Hour Session Close"

            # PnL in USD (for Gold: 1 USD move on 1 lot = $100. On 0.05 lot = $5 per $1.00 move)
            price_diff = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
            pnl_usd = price_diff * lot * 100.0

            self.balance += pnl_usd
            self.peak_balance = max(self.peak_balance, self.balance)
            dd = self.peak_balance - self.balance
            dd_pct = (dd / self.peak_balance * 100.0) if self.peak_balance > 0 else 0.0
            self.max_drawdown = max(self.max_drawdown, dd)
            self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)

            self.trades.append({
                "Date": entry_time.strftime("%Y-%m-%d %H:%M"),
                "Direction": direction,
                "Entry": round(entry_price, 2),
                "SL": round(initial_sl, 2),
                "Exit": round(exit_price, 2),
                "P&L": round(pnl_usd, 2),
                "ExitReason": exit_reason,
                "Balance": round(self.balance, 2)
            })

        return self._summarize()

    def _summarize(self) -> pd.DataFrame:
        df_trades = pd.DataFrame(self.trades)
        csv_file = config.BASE_DIR / "backtest_results.csv"

        if len(df_trades) == 0:
            logger.warning("No trades found matching setup criteria.")
            return df_trades

        df_trades.to_csv(csv_file, index=False)
        wins = df_trades[df_trades['P&L'] > 0]
        losses = df_trades[df_trades['P&L'] < 0]

        total = len(df_trades)
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / total * 100.0) if total > 0 else 0.0

        total_profit = wins['P&L'].sum()
        total_loss = abs(losses['P&L'].sum())
        profit_factor = (total_profit / total_loss) if total_loss > 0 else 999.0
        net_profit = self.balance - self.initial_balance
        net_profit_pct = (net_profit / self.initial_balance) * 100.0

        print("\n" + "=" * 70)
        print(" GOLD-EMA NY OPEN BOT v1.0 - HISTORICAL BACKTEST RESULTS")
        print("=" * 70)
        print(f" Instrument        : XAUUSD (M5)")
        print(f" Lot Size          : {config.LOT_SIZE} lots")
        print(f" Initial Balance   : ${self.initial_balance:,.2f}")
        print(f" Final Balance     : ${self.balance:,.2f}")
        print(f" Net Profit        : ${net_profit:+,.2f} ({net_profit_pct:+.2f}%)")
        print(f" Total Trades      : {total}")
        print(f" Win Rate          : {win_rate:.2f}% (Wins: {n_wins}, Losses: {n_losses})")
        print(f" Profit Factor     : {profit_factor:.2f}")
        print(f" Max Drawdown      : ${self.max_drawdown:.2f} ({self.max_drawdown_pct:.2f}%)")
        print(f" Detailed CSV File : {csv_file.name}")
        print("=" * 70 + "\n")

        return df_trades


if __name__ == "__main__":
    backtester = GoldEMABacktester(initial_balance=1000.0, n_bars=12000)
    backtester.run()

