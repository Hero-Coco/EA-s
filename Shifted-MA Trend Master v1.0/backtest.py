"""
=============================================================================
Shifted-MA Trend Master v1.0 - Historical Backtesting Engine
=============================================================================
Simulates the exact MQL5 ExpertMAMA logic across historical MT5 bars:
- Signal MA (12 SMA, Shift=6) for entries
- Trailing MA (12 SMA, Shift=0) for bar-by-bar trailing stop
- Position reversals on opposite signals
- Generates detailed trade logs, performance metrics, and CSV reports.
=============================================================================
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

import config
from mt5_manager import MT5Manager
from strategy import ShiftedMAStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ShiftedMA_Backtest")


class ShiftedMABacktester:
    """Historical bar-by-bar simulator for Shifted-MA Strategy."""

    def __init__(
        self,
        target_name: str,
        initial_balance: float = 1000.0,
        n_bars: int = 3000
    ):
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
        """Executes the backtest."""
        if not self.mt5_mgr.initialize():
            logger.error("MT5 initialization failed.")
            return None

        self.symbol = self.mt5_mgr.resolve_symbol(self.target_name)
        if not self.symbol:
            logger.error(f"Cannot resolve symbol for {self.target_name}")
            self.mt5_mgr.shutdown()
            return None

        timeframe = self.profile["timeframe"]
        logger.info(f"Fetching {self.n_bars} bars of {self.symbol} ({timeframe})...")
        df = self.mt5_mgr.get_rates(self.symbol, timeframe, n_bars=self.n_bars)
        self.mt5_mgr.shutdown()

        if df is None or len(df) < 50:
            logger.error("Insufficient historical data.")
            return None

        logger.info(f"Loaded {len(df)} candles from {df['time'].iloc[0]} to {df['time'].iloc[-1]}.")

        # Calculate Indicators
        df = ShiftedMAStrategy.calculate_indicators(df)

        # Simulation State
        active_trade: Optional[Dict[str, Any]] = None

        # Loop through completed bars
        for i in range(config.SIGNAL_MA_PERIOD + config.SIGNAL_MA_SHIFT + 2, len(df)):
            bar1 = df.iloc[i - 1]
            bar2 = df.iloc[i - 2]
            curr_bar = df.iloc[i]  # Represents the newly open/active bar

            c1, c2 = bar1['close'], bar2['close']
            s_ma1, s_ma2 = bar1['signal_ma'], bar2['signal_ma']
            t_ma1 = bar1['trailing_ma']

            # Check for Signal on bar 1 close
            signal = None
            if c2 <= s_ma2 and c1 > s_ma1:
                signal = "BUY"
            elif c2 >= s_ma2 and c1 < s_ma1:
                signal = "SELL"

            # 1. Update Trailing Stop or check SL hit for active trade
            if active_trade is not None:
                pos_dir = active_trade["direction"]
                entry_price = active_trade["entry_price"]
                current_sl = active_trade["sl"]
                lot = active_trade["lot"]

                # Check if current bar hit SL
                sl_hit = False
                exit_price = 0.0

                if pos_dir == "BUY":
                    if curr_bar['low'] <= current_sl:
                        sl_hit = True
                        exit_price = current_sl
                elif pos_dir == "SELL":
                    if curr_bar['high'] >= current_sl:
                        sl_hit = True
                        exit_price = current_sl

                if sl_hit:
                    # Calculate PnL
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
                        "exit_reason": "Trailing Stop Hit",
                        "running_balance": round(self.balance, 2)
                    })
                    self.trades.append(active_trade)
                    active_trade = None

                else:
                    # Trailing MA update
                    if pos_dir == "BUY":
                        new_sl = t_ma1
                        if new_sl > current_sl:
                            active_trade["sl"] = new_sl
                    elif pos_dir == "SELL":
                        new_sl = t_ma1
                        if current_sl == 0.0 or new_sl < current_sl:
                            active_trade["sl"] = new_sl

            # 2. Check for Signal Reversal or New Trade Entry
            if signal is not None:
                # If active trade is in opposite direction, close it at current bar open
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

                # Open New Position if none active
                if active_trade is None:
                    entry_price = curr_bar['open']
                    initial_sl = t_ma1
                    sl_dist = abs(entry_price - initial_sl)
                    
                    # Lot calculation
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
                    }

        # Summarize results
        return self._summarize()

    def _summarize(self) -> pd.DataFrame:
        """Calculates and prints performance metrics."""
        df_trades = pd.DataFrame(self.trades)
        csv_file = config.BASE_DIR / f"backtest_{self.target_name}.csv"

        if len(df_trades) == 0:
            logger.info(f"[{self.target_name}] No trades generated during this period.")
            return df_trades

        df_trades.to_csv(csv_file, index=False)

        winning_trades = df_trades[df_trades['pnl'] > 0]
        losing_trades = df_trades[df_trades['pnl'] < 0]

        total_trades = len(df_trades)
        n_wins = len(winning_trades)
        n_losses = len(losing_trades)
        win_rate = (n_wins / total_trades * 100.0) if total_trades > 0 else 0.0

        total_profit = winning_trades['pnl'].sum()
        total_loss = abs(losing_trades['pnl'].sum())
        profit_factor = (total_profit / total_loss) if total_loss > 0 else 999.0
        net_profit = self.balance - self.initial_balance
        net_profit_pct = (net_profit / self.initial_balance) * 100.0

        print("\n" + "=" * 70)
        print(f" SHIFTED-MA TREND MASTER v1.0 - BACKTEST RESULTS: {self.target_name}")
        print("=" * 70)
        print(f" Broker Symbol     : {self.symbol}")
        print(f" Timeframe         : {self.profile['timeframe']}")
        print(f" Initial Balance   : ${self.initial_balance:,.2f}")
        print(f" Final Balance     : ${self.balance:,.2f}")
        print(f" Net Profit        : ${net_profit:+,.2f} ({net_profit_pct:+.2f}%)")
        print(f" Total Trades      : {total_trades}")
        print(f" Win Rate          : {win_rate:.2f}% (Wins: {n_wins}, Losses: {n_losses})")
        print(f" Profit Factor     : {profit_factor:.2f}")
        print(f" Max Drawdown      : ${self.max_drawdown:.2f} ({self.max_drawdown_pct:.2f}%)")
        print(f" Detailed CSV File : {csv_file.name}")
        print("=" * 70 + "\n")

        return df_trades


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest Shifted-MA Trend Master v1.0")
    parser.add_argument("--target", type=str, default="XAUUSD", choices=["XAUUSD", "BTCUSD", "USTEC"], help="Target symbol")
    parser.add_argument("--bars", type=int, default=2500, help="Number of historical bars")
    parser.add_argument("--balance", type=float, default=1000.0, help="Initial balance")
    args = parser.parse_args()

    backtester = ShiftedMABacktester(
        target_name=args.target,
        initial_balance=args.balance,
        n_bars=args.bars
    )
    backtester.run()

