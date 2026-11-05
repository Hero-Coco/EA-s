"""
=============================================================================
NQ-Precision ORB Bot v1.0 - Historical Backtester
=============================================================================
Simulates the institutional 09:30-09:45 ET M1 Opening Range Breakout strategy,
including 09:59:55 ET snapshot entry, RVOL & ATR Regime filters, 2.2x ATR SL,
0.3x ATR TP, and the 8-minute time-stop exit.
=============================================================================
"""

import argparse
from datetime import datetime, time
import math
from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
import pytz
import MetaTrader5 as mt5

import config
from mt5_manager import MT5Manager
from strategy import NQPrecisionORBStrategy


class NQPrecisionORBBacktester:
    """Historical simulator for NQ-Precision ORB on M1 candlestick data."""

    def __init__(self, target_name: str = "USTEC", initial_balance: float = 1000.0, n_bars: int = 20000):
        self.target_name = target_name
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.n_bars = n_bars

        self.profile = config.TARGET_PROFILES[target_name]
        self.ny_tz = pytz.timezone(config.TIMEZONE_NAME)
        self.trades: List[Dict[str, Any]] = []

    def fetch_data(self) -> Optional[pd.DataFrame]:
        """Connects to MT5, downloads M1 rates, and converts timestamps to NY time."""
        mgr = MT5Manager()
        if not mgr.initialize():
            return None

        symbol = mgr.resolve_symbol(self.target_name)
        if not symbol:
            mgr.shutdown()
            return None

        self.symbol = symbol
        print(f"Fetching {self.n_bars} bars of {symbol} (M1)...")
        df = mgr.get_rates(symbol, "M1", n_bars=self.n_bars)
        mgr.shutdown()

        if df is None or len(df) < 200:
            return None

        # Convert timestamps to NY timezone
        df['time_ny'] = df['time'].dt.tz_localize('UTC').dt.tz_convert(self.ny_tz)
        return df

    def run(self) -> pd.DataFrame:
        """Executes simulation on downloaded M1 data."""
        df = self.fetch_data()
        if df is None:
            print("Failed to retrieve backtest data.")
            return pd.DataFrame()

        # Compute indicators: ATR(14), ATR(50), RVOL(14), ATR Regime
        df = NQPrecisionORBStrategy.calculate_indicators(df)

        print(f"Loaded {len(df)} candles from {df['time_ny'].iloc[0]} to {df['time_ny'].iloc[-1]}.")

        # Group by NY trading day
        df['date_ny'] = df['time_ny'].dt.date
        days = df['date_ny'].unique()

        for day in days:
            day_df = df[df['date_ny'] == day]
            if len(day_df) < 30:
                continue

            # 1. Opening Range (09:30 to 09:45 ET)
            orb_bars = day_df[
                (day_df['time_ny'].dt.time >= config.RANGE_START_TIME) &
                (day_df['time_ny'].dt.time < config.RANGE_END_TIME)
            ]

            if orb_bars.empty or len(orb_bars) < 10:
                continue

            range_high = float(orb_bars['high'].max())
            range_low = float(orb_bars['low'].min())

            # 2. Find the Snapshot Bar around 09:59 - 10:00 ET
            trigger_bars = day_df[
                (day_df['time_ny'].dt.hour == 9) & (day_df['time_ny'].dt.minute == 59)
            ]

            if trigger_bars.empty:
                # Fallback: check 10:00 bar
                trigger_bars = day_df[
                    (day_df['time_ny'].dt.hour == 10) & (day_df['time_ny'].dt.minute == 0)
                ]

            if trigger_bars.empty:
                continue

            entry_bar = trigger_bars.iloc[0]
            entry_idx = entry_bar.name
            entry_price = float(entry_bar['close'])
            atr_val = float(entry_bar['atr'])
            rvol = float(entry_bar['rvol'])
            atr_regime = float(entry_bar['atr_regime'])

            if pd.isna(atr_val) or atr_val <= 0:
                continue

            # Check breakout direction
            direction = None
            if entry_price > range_high:
                direction = "BUY"
            elif entry_price < range_low:
                direction = "SELL"
            else:
                # Inside range -> No trade
                continue

            # Check dual filters
            if config.USE_FILTERS:
                if pd.isna(rvol) or rvol < config.RVOL_MIN or rvol > config.RVOL_MAX:
                    continue
                if pd.isna(atr_regime) or atr_regime < config.REGIME_MIN or atr_regime > config.REGIME_MAX:
                    continue

            # Calculate SL and TP
            sl_dist = atr_val * config.ATR_SL_MULT
            tp_dist = atr_val * config.ATR_TP_MULT
            sl_price = (entry_price - sl_dist) if direction == "BUY" else (entry_price + sl_dist)
            tp_price = (entry_price + tp_dist) if direction == "BUY" else (entry_price - tp_dist)

            # Sizing
            if config.USE_DYNAMIC_LOT and sl_dist > 0:
                risk_usd = self.balance * (config.RISK_PERCENT / 100.0)
                contract_mult = 100.0 if "XAU" in self.target_name else (1.0 if "BTC" in self.target_name else 1.0)
                raw_lot = risk_usd / (sl_dist * contract_mult)
                lot = max(0.01, min(round(raw_lot, 2), 5.0))
            else:
                lot = self.profile.get("fallback_lot", 0.01)

            # 3. Simulate Forward Bars up to CLOSE_AFTER_MIN (8 minutes)
            remaining_bars = day_df.loc[entry_idx + 1:]
            max_bars = min(len(remaining_bars), config.CLOSE_AFTER_MIN)

            exit_price = 0.0
            exit_reason = "Time Close"
            exit_time = entry_bar['time_ny']

            for i in range(max_bars):
                curr_bar = remaining_bars.iloc[i]
                high = float(curr_bar['high'])
                low = float(curr_bar['low'])
                exit_time = curr_bar['time_ny']

                if direction == "BUY":
                    if high >= tp_price:
                        exit_price = tp_price
                        exit_reason = "TP Hit"
                        break
                    elif low <= sl_price:
                        exit_price = sl_price
                        exit_reason = "SL Hit"
                        break
                elif direction == "SELL":
                    if low <= tp_price:
                        exit_price = tp_price
                        exit_reason = "TP Hit"
                        break
                    elif high >= sl_price:
                        exit_price = sl_price
                        exit_reason = "SL Hit"
                        break

            # If 8 minutes elapsed without hitting SL or TP
            if exit_price == 0.0:
                if max_bars > 0:
                    exit_price = float(remaining_bars.iloc[max_bars - 1]['close'])
                    exit_time = remaining_bars.iloc[max_bars - 1]['time_ny']
                else:
                    exit_price = entry_price

            # Calculate PnL
            pnl_pts = (exit_price - entry_price) if direction == "BUY" else (entry_price - exit_price)
            mult = 100.0 if "XAU" in self.target_name else 1.0
            pnl_usd = pnl_pts * lot * mult
            self.balance += pnl_usd

            self.peak_balance = max(self.peak_balance, self.balance)
            dd = self.peak_balance - self.balance
            dd_pct = (dd / self.peak_balance) * 100.0 if self.peak_balance > 0 else 0.0
            self.max_drawdown = max(self.max_drawdown, dd)
            self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)

            self.trades.append({
                "date": str(day),
                "entry_time": str(entry_bar['time_ny']),
                "direction": direction,
                "lot": lot,
                "entry_price": round(entry_price, 2),
                "sl": round(sl_price, 2),
                "tp": round(tp_price, 2),
                "exit_time": str(exit_time),
                "exit_price": round(exit_price, 2),
                "exit_reason": exit_reason,
                "pnl_usd": round(pnl_usd, 2),
                "running_balance": round(self.balance, 2)
            })

        return self._summarize()

    def _summarize(self) -> pd.DataFrame:
        """Calculates and formats performance metrics."""
        df_trades = pd.DataFrame(self.trades)
        csv_file = config.BASE_DIR / f"backtest_{self.target_name}.csv"
        if len(df_trades) == 0:
            print("No trades triggered during backtest.")
            return df_trades

        df_trades.to_csv(csv_file, index=False)
        wins = df_trades[df_trades['pnl_usd'] > 0]
        losses = df_trades[df_trades['pnl_usd'] < 0]

        total = len(df_trades)
        win_rate = (len(wins) / total * 100.0) if total > 0 else 0.0
        profit = wins['pnl_usd'].sum()
        loss = abs(losses['pnl_usd'].sum())
        pf = (profit / loss) if loss > 0 else 999.0
        net = self.balance - self.initial_balance
        net_pct = (net / self.initial_balance) * 100.0

        print("\n" + "=" * 70)
        print(f" NQ-PRECISION ORB BOT v1.0 - BACKTEST RESULTS: {self.target_name}")
        print("=" * 70)
        print(f" Broker Symbol     : {self.symbol}")
        print(f" Timeframe         : M1")
        print(f" Initial Balance   : ${self.initial_balance:,.2f}")
        print(f" Final Balance     : ${self.balance:,.2f}")
        print(f" Net Profit        : ${net:+,.2f} ({net_pct:+.2f}%)")
        print(f" Total Trades      : {total}")
        print(f" Win Rate          : {win_rate:.2f}% (Wins: {len(wins)}, Losses: {len(losses)})")
        print(f" Profit Factor     : {pf:.2f}")
        print(f" Max Drawdown      : ${self.max_drawdown:.2f} ({self.max_drawdown_pct:.2f}%)")
        print(f" Detailed CSV File : {csv_file.name}")
        print("=" * 70 + "\n")

        return df_trades


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest NQ-Precision ORB Bot v1.0")
    parser.add_argument("--target", type=str, default="USTEC", choices=["USTEC", "XAUUSD", "BTCUSD"])
    parser.add_argument("--bars", type=int, default=15000)
    parser.add_argument("--balance", type=float, default=1000.0)
    args = parser.parse_args()

    NQPrecisionORBBacktester(target_name=args.target, initial_balance=args.balance, n_bars=args.bars).run()
