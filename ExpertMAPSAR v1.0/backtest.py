"""
=============================================================================
MAPSAR-Trend Bot v1.0 - Historical Backtesting Engine
=============================================================================
Simulates ExpertMAPSAR (12 SMA Shift=6 + Parabolic SAR Trailing Stop).
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
from strategy import MAPSARStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MAPSAR_Backtest")


class MAPSARBacktester:
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

        df = MAPSARStrategy.calculate_indicators(df)
        active_trade: Optional[Dict[str, Any]] = None

        for i in range(config.SIGNAL_MA_PERIOD + config.SIGNAL_MA_SHIFT + 5, len(df)):
            bar1 = df.iloc[i - 1]
            bar2 = df.iloc[i - 2]
            curr_bar = df.iloc[i]

            c1, c2 = bar1['close'], bar2['close']
            s_ma1, s_ma2 = bar1['signal_ma'], bar2['signal_ma']
            sar1 = bar1['sar']

            signal = None
            if c2 <= s_ma2 and c1 > s_ma1:
                signal = "BUY"
            elif c2 >= s_ma2 and c1 < s_ma1:
                signal = "SELL"

            # Check SL hit or update SAR trailing stop
            if active_trade is not None:
                pos_dir = active_trade["direction"]
                entry_price = active_trade["entry_price"]
                current_sl = active_trade["sl"]
                lot = active_trade["lot"]

                sl_hit = False
                exit_price = 0.0

                if pos_dir == "BUY" and curr_bar['low'] <= current_sl:
                    sl_hit = True
                    exit_price = current_sl
                elif pos_dir == "SELL" and curr_bar['high'] >= current_sl:
                    sl_hit = True
                    exit_price = current_sl

                if sl_hit:
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
                        "exit_reason": "Trailing SL Hit",
                        "running_balance": round(self.balance, 2)
                    })
                    self.trades.append(active_trade)
                    active_trade = None
                else:
                    # 1:1 R:R Trailing Stop: Starts at 1:1 R:R, advances by 0.5 R for every 0.5 R profit
                    r = active_trade["r"]
                    if pos_dir == "BUY":
                        profit = curr_bar['high'] - entry_price
                        if profit >= config.TRAIL_START_R * r:
                            n_steps = int((profit - config.TRAIL_START_R * r) / (config.TRAIL_STEP_R * r))
                            target_sl = entry_price + (n_steps * config.TRAIL_STEP_R * r)
                            if target_sl > active_trade["sl"]:
                                active_trade["sl"] = target_sl
                    elif pos_dir == "SELL":
                        profit = entry_price - curr_bar['low']
                        if profit >= config.TRAIL_START_R * r:
                            n_steps = int((profit - config.TRAIL_START_R * r) / (config.TRAIL_STEP_R * r))
                            target_sl = entry_price - (n_steps * config.TRAIL_STEP_R * r)
                            if target_sl < active_trade["sl"]:
                                active_trade["sl"] = target_sl

            # Check signal reversal or new entry
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
                        "exit_reason": "Signal Reversal",
                        "running_balance": round(self.balance, 2)
                    })
                    self.trades.append(active_trade)
                    active_trade = None

                if active_trade is None:
                    entry_price = curr_bar['open']
                    r = entry_price * (config.INITIAL_SL_PERCENT / 100.0)
                    initial_sl = entry_price - r if signal == "BUY" else entry_price + r
                    sl_dist = r

                    if config.USE_DYNAMIC_LOT and sl_dist > 0:
                        risk_usd = self.balance * (config.RISK_PERCENT / 100.0)
                        raw_lot = risk_usd / (sl_dist * 100.0 if "XAU" in self.symbol else sl_dist)
                        lot = max(0.01, min(round(raw_lot, 2), 5.0))
                    else:
                        lot = self.profile.get("fallback_lot", 0.01)

                    active_trade = {
                        "symbol": self.symbol,
                        "direction": signal,
                        "lot": lot,
                        "entry_time": curr_bar['time'],
                        "entry_price": round(entry_price, 2),
                        "sl": initial_sl,
                        "r": r,
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
        print(f" MAPSAR-TREND BOT v1.0 - BACKTEST RESULTS: {self.target_name}")
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
    parser = argparse.ArgumentParser(description="Backtest MAPSAR-Trend Bot v1.0")
    parser.add_argument("--target", type=str, default="XAUUSD", choices=["XAUUSD", "BTCUSD", "USTEC"])
    parser.add_argument("--bars", type=int, default=2500)
    parser.add_argument("--balance", type=float, default=1000.0)
    args = parser.parse_args()

    MAPSARBacktester(target_name=args.target, initial_balance=args.balance, n_bars=args.bars).run()

