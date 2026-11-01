"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - Historical Backtesting Engine
=============================================================================
Simulates Smart Money Concepts (SMC) on MT5 M5 historical data:
- Assets: NIFTY (IN50m), Gold (XAUUSDm), Bitcoin (BTCUSDm)
- Detects Liquidity Sweeps, Market Structure Shifts, and FVGs
- Executes trades on FVG Mitigation + Engulfing confirmation
- Enforces SL beyond FVG and TP at next liquidity level
- Calculates Win Rate, Profit Factor, Net P&L, Max Drawdown
=============================================================================
"""

import argparse
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

import config
from smc_detector import (
    calculate_swings,
    detect_liquidity_sweep,
    detect_fvg_at_bar,
    is_engulfing_inside_fvg,
    FVGZone
)
from trade_logger import setup_logger
from chart_visualizer import plot_smc_setup


class SMCBacktester:
    """Historical backtester for Smart Money Concepts."""

    def __init__(self, symbol: str, target_name: str, initial_deposit: float = 1000.0):
        self.symbol = symbol
        self.target_name = target_name
        self.initial_deposit = initial_deposit
        self.logger = setup_logger(f"Backtest_{target_name}")
        self.profile = config.PAIR_PROFILES.get(target_name, config.PAIR_PROFILES.get("NIFTY", {}))

    def fetch_historical_bars(self, num_bars: int = 25000) -> pd.DataFrame:
        """Fetches historical M5 bars from MT5."""
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialization failed! Code: {mt5.last_error()}")

        mt5.symbol_select(self.symbol, True)
        rates = mt5.copy_rates_from_pos(self.symbol, config.TIMEFRAME, 0, num_bars)
        if rates is None or len(rates) == 0:
            raise ValueError(f"No historical rates available for {self.symbol}")

        df = pd.DataFrame(rates)
        df['datetime'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('datetime', inplace=True)
        df.sort_index(inplace=True)
        return df

    def run(self, num_bars: int = 25000) -> Dict[str, Any]:
        """Runs SMC simulation bar-by-bar."""
        df = self.fetch_historical_bars(num_bars)
        sym_info = mt5.symbol_info(self.symbol)
        contract_size = sym_info.trade_contract_size if sym_info else 1.0
        lot_size = self.profile.get("lot_size", config.DEFAULT_LOT)
        min_fvg = self.profile.get("min_fvg_points", 10.0)
        sl_buffer = self.profile.get("sl_buffer_points", 2.0)
        min_rr = self.profile.get("min_rr_ratio", 1.5)

        swing_high_series, swing_low_series = calculate_swings(df, config.SWING_LOOKBACK)

        trades: List[Dict[str, Any]] = []
        running_balance = self.initial_deposit
        in_trade = False
        trade_dir = ""
        trade_entry = 0.0
        trade_sl = 0.0
        trade_tp = 0.0
        trade_entry_time = None
        trade_entry_idx = 0
        trade_fvg_top = 0.0
        trade_fvg_bottom = 0.0

        daily_trades_count: Dict[date, int] = {}
        first_setup_plotted = False

        n = len(df)
        lookback = config.SWING_LOOKBACK

        for idx in range(lookback + 5, n):
            current_bar = df.iloc[idx]
            bar_date = current_bar.name.date() if hasattr(current_bar.name, 'date') else date.today()

            # 1. Manage open position
            if in_trade:
                high_p = float(current_bar['high'])
                low_p = float(current_bar['low'])
                closed = False
                exit_price = 0.0
                exit_reason = ""

                if trade_dir == "BUY":
                    if low_p <= trade_sl:
                        exit_price = trade_sl
                        exit_reason = "Stop Loss Hit"
                        closed = True
                    elif high_p >= trade_tp:
                        exit_price = trade_tp
                        exit_reason = "Take Profit Hit"
                        closed = True
                elif trade_dir == "SELL":
                    if high_p >= trade_sl:
                        exit_price = trade_sl
                        exit_reason = "Stop Loss Hit"
                        closed = True
                    elif low_p <= trade_tp:
                        exit_price = trade_tp
                        exit_reason = "Take Profit Hit"
                        closed = True

                if closed:
                    pnl = (exit_price - trade_entry) * contract_size * lot_size if trade_dir == "BUY" else (trade_entry - exit_price) * contract_size * lot_size
                    running_balance += pnl
                    trades.append({
                        "Symbol": self.symbol,
                        "Direction": trade_dir,
                        "EntryTime": trade_entry_time.strftime("%Y-%m-%d %H:%M") if hasattr(trade_entry_time, 'strftime') else str(trade_entry_time),
                        "EntryPrice": round(trade_entry, 2),
                        "SL": round(trade_sl, 2),
                        "TP": round(trade_tp, 2),
                        "ExitTime": current_bar.name.strftime("%Y-%m-%d %H:%M") if hasattr(current_bar.name, 'strftime') else str(current_bar.name),
                        "ExitPrice": round(exit_price, 2),
                        "PnL": round(pnl, 2),
                        "RunningBalance": round(running_balance, 2),
                        "ExitReason": exit_reason
                    })
                    in_trade = False
                continue

            # 2. Check daily trade limit (Max 2 trades per day)
            if daily_trades_count.get(bar_date, 0) >= config.MAX_TRADES_PER_DAY:
                continue

            # 3. Check for SMC setup
            # Scan recent bars for liquidity sweep
            sh = swing_high_series.iloc[idx]
            sl = swing_low_series.iloc[idx]

            # Look back over recent bars (last 25 bars) for a sweep
            for s_idx in range(max(lookback, idx - 25), idx):
                s_sh = swing_high_series.iloc[s_idx]
                s_sl = swing_low_series.iloc[s_idx]
                sweep = detect_liquidity_sweep(df, s_idx, s_sh, s_sl)
                if sweep is None:
                    continue

                sweep_type, sweep_level = sweep

                # --- BULLISH SETUP ---
                if sweep_type == "BULLISH":
                    # Check for MSS (Close > s_sh)
                    mss_found = any(df['close'].iloc[m] > s_sh for m in range(s_idx + 1, idx))
                    if not mss_found:
                        continue

                    # Check for Bullish FVG
                    active_fvg = None
                    for f_idx in range(s_idx, idx + 1):
                        fvg = detect_fvg_at_bar(df, f_idx, min_size_points=min_fvg)
                        if fvg and fvg.direction == "BULLISH":
                            active_fvg = fvg

                    if active_fvg is None:
                        continue

                    # Check for Bullish Engulfing inside FVG at current bar
                    if is_engulfing_inside_fvg(df, idx, active_fvg):
                        entry_p = float(current_bar['close'])
                        sl_p = active_fvg.bottom - sl_buffer
                        risk = entry_p - sl_p
                        if risk <= 0:
                            continue

                        # Target external liquidity pool (MSS swing high) or at least 1:2 R:R
                        mss_high = float(df['high'].iloc[s_idx:idx].max())
                        tp_p = max(mss_high, entry_p + (risk * 1.5))
                        reward = tp_p - entry_p

                        if reward / risk >= min_rr:
                            in_trade = True
                            trade_dir = "BUY"
                            trade_entry = entry_p
                            trade_sl = sl_p
                            trade_tp = tp_p
                            trade_entry_time = current_bar.name
                            trade_entry_idx = idx
                            trade_fvg_top = active_fvg.top
                            trade_fvg_bottom = active_fvg.bottom
                            daily_trades_count[bar_date] = daily_trades_count.get(bar_date, 0) + 1

                            # Plot first sample setup for debug
                            if not first_setup_plotted:
                                try:
                                    window_df = df.iloc[max(0, s_idx - 10):idx + 1]
                                    plot_smc_setup(
                                        df_window=window_df,
                                        symbol=self.target_name,
                                        direction="BUY",
                                        entry_price=entry_p,
                                        sl_price=sl_p,
                                        tp_price=tp_p,
                                        fvg_top=active_fvg.top,
                                        fvg_bottom=active_fvg.bottom,
                                        swing_high=s_sh,
                                        swing_low=s_sl,
                                        setup_name="backtest_sample_buy"
                                    )
                                    first_setup_plotted = True
                                except Exception:
                                    pass
                            break

                # --- BEARISH SETUP ---
                elif sweep_type == "BEARISH":
                    # Check for MSS (Close < s_sl)
                    mss_found = any(df['close'].iloc[m] < s_sl for m in range(s_idx + 1, idx))
                    if not mss_found:
                        continue

                    # Check for Bearish FVG
                    active_fvg = None
                    for f_idx in range(s_idx, idx + 1):
                        fvg = detect_fvg_at_bar(df, f_idx, min_size_points=min_fvg)
                        if fvg and fvg.direction == "BEARISH":
                            active_fvg = fvg

                    if active_fvg is None:
                        continue

                    # Check for Bearish Engulfing inside FVG at current bar
                    if is_engulfing_inside_fvg(df, idx, active_fvg):
                        entry_p = float(current_bar['close'])
                        sl_p = active_fvg.top + sl_buffer
                        risk = sl_p - entry_p
                        if risk <= 0:
                            continue

                        # Target external liquidity pool (MSS swing low) or at least 1:2 R:R
                        mss_low = float(df['low'].iloc[s_idx:idx].min())
                        tp_p = min(mss_low, entry_p - (risk * 1.5))
                        reward = entry_p - tp_p

                        if reward / risk >= min_rr:
                            in_trade = True
                            trade_dir = "SELL"
                            trade_entry = entry_p
                            trade_sl = sl_p
                            trade_tp = tp_p
                            trade_entry_time = current_bar.name
                            trade_entry_idx = idx
                            trade_fvg_top = active_fvg.top
                            trade_fvg_bottom = active_fvg.bottom
                            daily_trades_count[bar_date] = daily_trades_count.get(bar_date, 0) + 1

                            if not first_setup_plotted:
                                try:
                                    window_df = df.iloc[max(0, s_idx - 10):idx + 1]
                                    plot_smc_setup(
                                        df_window=window_df,
                                        symbol=self.target_name,
                                        direction="SELL",
                                        entry_price=entry_p,
                                        sl_price=sl_p,
                                        tp_price=tp_p,
                                        fvg_top=active_fvg.top,
                                        fvg_bottom=active_fvg.bottom,
                                        swing_high=s_sh,
                                        swing_low=s_sl,
                                        setup_name="backtest_sample_sell"
                                    )
                                    first_setup_plotted = True
                                except Exception:
                                    pass
                            break

        trades_df = pd.DataFrame(trades)
        return self._compute_summary(trades_df, running_balance)

    def _compute_summary(self, trades_df: pd.DataFrame, final_balance: float) -> Dict[str, Any]:
        """Calculates backtest summary statistics."""
        if trades_df.empty:
            return {
                "Symbol": self.symbol,
                "Target": self.target_name,
                "TotalTrades": 0,
                "WinRate": 0.0,
                "NetProfit": 0.0,
                "ROI": 0.0,
                "ProfitFactor": 0.0,
                "MaxDrawdownUSD": 0.0,
                "MaxDrawdownPct": 0.0
            }

        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['PnL'] > 0])
        losing_trades = len(trades_df[trades_df['PnL'] < 0])
        win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

        net_profit = final_balance - self.initial_deposit
        roi = (net_profit / self.initial_deposit) * 100.0

        trades_df['Peak'] = trades_df['RunningBalance'].cummax()
        trades_df['Drawdown'] = trades_df['Peak'] - trades_df['RunningBalance']
        trades_df['DrawdownPct'] = (trades_df['Drawdown'] / trades_df['Peak']) * 100.0
        max_drawdown_pct = trades_df['DrawdownPct'].max()
        max_drawdown_usd = trades_df['Drawdown'].max()

        gross_profit = trades_df[trades_df['PnL'] > 0]['PnL'].sum()
        gross_loss = abs(trades_df[trades_df['PnL'] < 0]['PnL'].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

        csv_filename = config.BASE_DIR / f"backtest_{self.target_name}.csv"
        trades_df.to_csv(csv_filename, index=False)

        summary = {
            "Symbol": self.symbol,
            "Target": self.target_name,
            "InitialDeposit": self.initial_deposit,
            "FinalBalance": round(final_balance, 2),
            "NetProfit": round(net_profit, 2),
            "ROI": round(roi, 2),
            "TotalTrades": total_trades,
            "WinningTrades": winning_trades,
            "LosingTrades": losing_trades,
            "WinRate": round(win_rate, 2),
            "ProfitFactor": round(profit_factor, 2),
            "MaxDrawdownUSD": round(max_drawdown_usd, 2),
            "MaxDrawdownPct": round(max_drawdown_pct, 2),
            "CSVPath": str(csv_filename)
        }

        self.logger.info("=" * 70)
        self.logger.info(f"SMC BACKTEST RESULTS: {self.target_name} ({self.symbol})")
        self.logger.info("=" * 70)
        self.logger.info(f" Initial Balance   : ${self.initial_deposit:.2f}")
        self.logger.info(f" Final Balance     : ${final_balance:.2f}")
        self.logger.info(f" Net Profit        : ${net_profit:+.2f} ({roi:+.2f}%)")
        self.logger.info(f" Total Trades      : {total_trades}")
        self.logger.info(f" Win Rate          : {win_rate:.2f}% (Won: {winning_trades}, Lost: {losing_trades})")
        self.logger.info(f" Profit Factor     : {profit_factor:.2f}")
        self.logger.info(f" Max Drawdown      : ${max_drawdown_usd:.2f} ({max_drawdown_pct:.2f}%)")
        self.logger.info(f" Detailed CSV File : {csv_filename.name}")
        self.logger.info("=" * 70)

        return summary


def main():
    parser = argparse.ArgumentParser(description="SMC Backtester")
    parser.add_argument("--symbol", type=str, default=None, help="Target: NIFTY, XAUUSD, or BTCUSD")
    parser.add_argument("--bars", type=int, default=25000, help="Number of historical M5 bars to fetch")
    args = parser.parse_args()

    if not mt5.initialize():
        print("Failed to initialize MT5!")
        return

    all_symbols = {s.name.upper(): s.name for s in mt5.symbols_get()}
    resolved = {}
    for target, candidates in config.CANDIDATE_SYMBOLS.items():
        for cand in candidates:
            if cand.upper() in all_symbols:
                resolved[target] = all_symbols[cand.upper()]
                break

    targets_to_run = [args.symbol] if args.symbol else config.ACTIVE_TARGETS

    for target in targets_to_run:
        broker_sym = resolved.get(target)
        if not broker_sym:
            print(f"Skipping {target}: could not resolve broker symbol.")
            continue
        tester = SMCBacktester(symbol=broker_sym, target_name=target)
        tester.run(num_bars=args.bars)

    mt5.shutdown()


if __name__ == "__main__":
    main()
