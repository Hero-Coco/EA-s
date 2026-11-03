"""
=============================================================================
MACD-Momentum Master v1.0 - Historical Backtesting Engine
=============================================================================
Simulates ExpertMACD across historical MT5 bars.
=============================================================================
"""

import os
import sys
import argparse
import logging
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

import config
from mt5_manager import MT5Manager
from strategy import MACDStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MACD_Backtest")


class MACDBacktester:
    def __init__(self, target_name: str, initial_balance: float = 1000.0, n_bars: int = 2500):
        self.target_name = target_name
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.peak_balance = initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.n_bars = n_bars

        self.mt5_mgr = MT5Manager(logger=logger)
        self.profile = config.TARGET_PROFILES[target_name]
        self.symbol: Optional[str] = None
        self.trades: List[Dict[str, Any]] = []

    def run(self) -> Optional[pd.DataFrame]:
        if not self.mt5_mgr.initialize():
            return None

        self.symbol = self.mt5_mgr.resolve_symbol(self.target_name)
        if not self.symbol:
            self.mt5_mgr.shutdown()
            return None

        timeframe = self.profile["timeframe"]
        df = self.mt5_mgr.get_rates(self.symbol, timeframe, n_bars=self.n_bars)
        self.mt5_mgr.shutdown()

        if df is None or len(df) < 50:
            return None

        df = MACDStrategy.calculate_indicators(df)
        active_trade: Optional[Dict[str, Any]] = None

        sl_pts = self.profile.get("sl_points", 20.0)
        tp_pts = self.profile.get("tp_points", 50.0)

        for i in range(config.MACD_SLOW + config.MACD_SIGNAL + 5, len(df)):
            bar1 = df.iloc[i - 1]
            bar2 = df.iloc[i - 2]
            curr_bar = df.iloc[i]

            m1, s1 = bar1['macd_main'], bar1['macd_signal']
            m2, s2 = bar2['macd_main'], bar2['macd_signal']

            signal = None
            if (m2 <= s2 and m1 > s1) or (m2 <= 0.0 and m1 > 0.0):
                signal = "BUY"
            elif (m2 >= s2 and m1 < s1) or (m2 >= 0.0 and m1 < 0.0):
                signal = "SELL"

            # Check SL or TP for active trade
            if active_trade is not None:
                pos_dir = active_trade["direction"]
                entry_price = active_trade["entry_price"]
                sl = active_trade["sl"]
                tp = active_trade["tp"]
                lot = active_trade["lot"]

                exited = False
                exit_price = 0.0
                reason = ""

                if pos_dir == "BUY":
                    if curr_bar['low'] <= sl:
                        exited = True
                        exit_price = sl
                        reason = "Stop Loss Hit"
                    elif curr_bar['high'] >= tp:
                        exited = True
                        exit_price = tp
                        reason = "Take Profit Hit"
                elif pos_dir == "SELL":
                    if curr_bar['high'] >= sl:
                        exited = True
                        exit_price = sl
                        reason = "Stop Loss Hit"
                    elif curr_bar['low'] <= tp:
                        exited = True
                        exit_price = tp
                        reason = "Take Profit Hit"

                if exited:
                    pnl_points = (exit_price - entry_price) if pos_dir == "BUY" else (entry_price - exit_price)
                    pnl_usd = pnl_points * lot * 100.0 if "XAU" in self.symbol else (pnl_points * lot)
                    self.balance += pnl_usd

                    self.peak_balance = max(self.peak_balance, self.balance)
                    dd = self.peak_balance - self.balance
                    dd_pct = (dd / self.peak_balance) * 100.0 if self.peak_balance > 0 else 0.0
                    self.max_drawdown = max(self.max_drawdown, dd)
                    self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)

                    active_trade.update({
                        "exit_time": curr_bar['time'],
                        "exit_price": round(exit_price, 2),
                        "pnl": round(pnl_usd, 2),
                        "exit_reason": reason,
                        "running_balance": round(self.balance, 2)
                    })
                    self.trades.append(active_trade)
                    active_trade = None

            # Check Reversal or New Entry
            if signal is not None:
                if active_trade is not None and active_trade["direction"] != signal:
                    exit_price = curr_bar['open']
                    pos_dir = active_trade["direction"]
                    entry_price = active_trade["entry_price"]
                    lot = active_trade["lot"]

                    pnl_points = (exit_price - entry_price) if pos_dir == "BUY" else (entry_price - exit_price)
                    pnl_usd = pnl_points * lot * 100.0 if "XAU" in self.symbol else (pnl_points * lot)
                    self.balance += pnl_usd

                    self.peak_balance = max(self.peak_balance, self.balance)
                    dd = self.peak_balance - self.balance
                    dd_pct = (dd / self.peak_balance) * 100.0 if self.peak_balance > 0 else 0.0
                    self.max_drawdown = max(self.max_drawdown, dd)
                    self.max_drawdown_pct = max(self.max_drawdown_pct, dd_pct)

                    active_trade.update({
                        "exit_time": curr_bar['time'],
                        "exit_price": round(exit_price, 2),
                        "pnl": round(pnl_usd, 2),
                        "exit_reason": "MACD Reversal",
                        "running_balance": round(self.balance, 2)
                    })
                    self.trades.append(active_trade)
                    active_trade = None

                if active_trade is None:
                    entry_price = curr_bar['open']
                    sl_price = (entry_price - sl_pts) if signal == "BUY" else (entry_price + sl_pts)
                    tp_price = (entry_price + tp_pts) if signal == "BUY" else (entry_price - tp_pts)

                    if config.USE_DYNAMIC_LOT and sl_pts > 0:
                        risk_usd = self.balance * (config.RISK_PERCENT / 100.0)
                        raw_lot = risk_usd / (sl_pts * 100.0 if "XAU" in self.symbol else sl_pts)
                        lot = max(0.01, min(round(raw_lot, 2), 5.0))
                    else:
                        lot = self.profile.get("fallback_lot", 0.01)

                    active_trade = {
                        "symbol": self.symbol,
                        "direction": signal,
                        "lot": lot,
                        "entry_time": curr_bar['time'],
                        "entry_price": round(entry_price, 2),
                        "sl": sl_price,
                        "tp": tp_price
                    }

        return self._summarize()

    def _summarize(self) -> pd.DataFrame:
        df_trades = pd.DataFrame(self.trades)
        csv_file = config.BASE_DIR / f"backtest_{self.target_name}.csv"
        if len(df_trades) == 0:
            return df_trades

        df_trades.to_csv(csv_file, index=False)
        wins = df_trades[df_trades['pnl'] > 0]
        losses = df_trades[df_trades['pnl'] < 0]

        total = len(df_trades)
        win_rate = (len(wins) / total * 100.0) if total > 0 else 0.0
        profit = wins['pnl'].sum()
        loss = abs(losses['pnl'].sum())
        pf = (profit / loss) if loss > 0 else 999.0
        net = self.balance - self.initial_balance
        net_pct = (net / self.initial_balance) * 100.0

        print("\n" + "=" * 70)
        print(f" MACD-MOMENTUM MASTER v1.0 - BACKTEST RESULTS: {self.target_name}")
        print("=" * 70)
        print(f" Broker Symbol     : {self.symbol}")
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
    parser = argparse.ArgumentParser(description="Backtest MACD-Momentum Master v1.0")
    parser.add_argument("--target", type=str, default="XAUUSD", choices=["XAUUSD", "BTCUSD", "USTEC"])
    parser.add_argument("--bars", type=int, default=2500)
    parser.add_argument("--balance", type=float, default=1000.0)
    args = parser.parse_args()

    MACDBacktester(target_name=args.target, initial_balance=args.balance, n_bars=args.bars).run()
