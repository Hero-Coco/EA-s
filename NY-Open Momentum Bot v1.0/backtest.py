"""
NY-Open Momentum Bot v1.0 - Backtest Engine
============================================
Runs comprehensive historical backtest using real M5 / M15 broker data from MT5.
Simulates:
- 09:30-09:35 ET 5-minute range calculation (Breakout Box)
- Volatility filter (Range >= 30 points)
- Breakout entry on candle close (M15 / M5)
- Initial Stop Loss at opposite side +/- 10 points
- Trailing Stop (+50 pt trigger, 30 pt distance, 5 pt step)
- Daily loss limit (-200 points) and 1 trade per day constraint
- Comprehensive performance report & CSV output
"""

import os
import csv
import sys
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config
from holidays_filter import is_trading_day


class NYOpenBacktester:
    """Historical simulation engine for NY-Open Momentum strategy."""

    def __init__(
        self,
        symbol: str = None,
        lookback_bars: int = 25000,
        execution_tf: str = None,
        lot_size: float = None,
        initial_deposit: float = 1000.0,
        use_dynamic_lot: bool = True,
        risk_percent: float = 1.0
    ):
        self.symbol = symbol or config.FORCED_SYMBOL or "USTECm"
        self.profile = config.get_pair_profile(self.symbol)
        self.lookback_bars = lookback_bars
        self.execution_tf = execution_tf or config.EXECUTION_TIMEFRAME_NAME
        self.lot_size = lot_size if lot_size is not None else config.LOT_SIZE
        self.initial_deposit = float(initial_deposit)
        self.use_dynamic_lot = use_dynamic_lot
        self.risk_percent = float(risk_percent)
        self.ny_tz = pytz.timezone(config.TIMEZONE_STR)
        self.contract_size = 1.0
        self.point_usd_per_lot = 1.0
        self.results_csv = os.path.join(config.BASE_DIR, f"backtest_{self.symbol}.csv")

    def _init_mt5(self) -> bool:
        """Connects to MT5 to fetch broker historical data."""
        if mt5 is None:
            print("[ERROR] MetaTrader5 package is required for backtest.")
            return False

        if not mt5.initialize(path=config.MT5_PATH, timeout=config.MT5_TIMEOUT_MS):
            # Try default initialize
            if not mt5.initialize():
                err = mt5.last_error()
                print(f"[ERROR] MT5 initialize failed: {err}")
                return False

        if not mt5.symbol_select(self.symbol, True):
            print(f"[ERROR] Could not select symbol {self.symbol} in MT5.")
            return False

        info = mt5.symbol_info(self.symbol)
        if info:
            self.contract_size = info.trade_contract_size if info.trade_contract_size > 0 else 1.0
            if info.trade_tick_size > 0 and info.trade_tick_value_profit > 0:
                # 1.0 index point in USD for 1 lot
                ticks_per_point = 1.0 / info.trade_tick_size
                self.point_usd_per_lot = ticks_per_point * info.trade_tick_value_profit

        return True

    def fetch_historical_bars(self) -> List[Dict]:
        """Fetches M5 bars from MT5 and converts timestamps to US/Eastern."""
        print(f"[*] Fetching historical M5 data for {self.symbol} ({self.lookback_bars} bars)...")
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M5, 0, self.lookback_bars)
        if rates is None or len(rates) == 0:
            print(f"[ERROR] No historical rates returned for {self.symbol}.")
            return []

        formatted_bars = []
        for r in rates:
            dt_utc = datetime.fromtimestamp(r["time"], tz=pytz.utc)
            dt_ny = dt_utc.astimezone(self.ny_tz)
            formatted_bars.append({
                "time_utc": dt_utc,
                "time_ny": dt_ny,
                "date_ny": dt_ny.date(),
                "time_only": dt_ny.time(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"])
            })

        print(f"[+] Loaded {len(formatted_bars)} bars from "
              f"{formatted_bars[0]['date_ny']} to {formatted_bars[-1]['date_ny']}.")
        return formatted_bars

    def run_backtest(self) -> Dict:
        """Executes the backtest simulation over the fetched data."""
        if not self._init_mt5():
            return {}

        bars = self.fetch_historical_bars()
        mt5.shutdown()

        if not bars:
            return {}

        # Group bars by New York calendar date
        days_data: Dict[date, List[Dict]] = {}
        for b in bars:
            d = b["date_ny"]
            if d not in days_data:
                days_data[d] = []
            days_data[d].append(b)

        sorted_dates = sorted(days_data.keys())
        print(f"[*] Simulating NY-Open Momentum strategy across {len(sorted_dates)} calendar days...\n")

        trades: List[Dict] = []
        skipped_low_volatility = 0
        skipped_holidays_weekends = 0
        no_signal_days = 0
        total_daily_loss_limit_hits = 0

        running_balance = self.initial_deposit
        peak_balance = self.initial_deposit

        for d in sorted_dates:
            # 1. Weekend & US Holiday Filter
            is_valid, reason = is_trading_day(d)
            if not is_valid:
                skipped_holidays_weekends += 1
                continue

            day_bars = days_data[d]

            # 2. Find the 08:00 - 08:05 ET M5 opening candle (Forex/Gold NY Open)
            range_candle = None
            for b in day_bars:
                if b["time_only"] == time(8, 0):
                    range_candle = b
                    break

            if range_candle is None:
                # Incomplete day or market opened late
                continue

            range_high = range_candle["high"]
            range_low = range_candle["low"]
            range_size = range_high - range_low

            min_range = self.profile["min_range_points"]
            sl_buffer = self.profile["sl_buffer_points"]
            trail_trigger = self.profile["trailing_trigger_points"]
            trail_distance = self.profile["trailing_distance_points"]
            trail_step = self.profile["trailing_step_points"]

            # 3. Volatility Filter: Range >= min_range
            if range_size < min_range:
                skipped_low_volatility += 1
                continue

            # 4. Breakout Search: Check candle closes between 09:35 ET and 11:00 ET
            # For M15 execution, we group M5 bars into M15 completed closes (09:45, 10:00, 10:15, 10:30, 10:45, 11:00)
            entry_trade = None
            entry_bar_idx = None

            for idx, b in enumerate(day_bars):
                t = b["time_only"]
                if t < time(9, 35) or t > time(11, 0):
                    continue

                # If M15 execution is selected, trigger on M15 boundaries (minute 0, 15, 30, 45)
                if self.execution_tf.upper() == "M15":
                    # An M15 bar completes at the close of an M5 bar whose time ends at minute 10, 25, 40, 55
                    # In MT5, an M15 bar opened at 09:30 closes when the 09:40 M5 bar closes (at 09:45)
                    if b["time_only"].minute not in [10, 25, 40, 55]:
                        continue

                # Long Breakout Check
                if b["close"] > range_high:
                    entry_trade = {
                        "direction": "BUY",
                        "entry_time": b["time_ny"],
                        "entry_price": b["close"],
                        "initial_sl": range_low - sl_buffer,
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_size": range_size
                    }
                    entry_bar_idx = idx
                    break

                # Short Breakout Check
                elif b["close"] < range_low:
                    entry_trade = {
                        "direction": "SELL",
                        "entry_time": b["time_ny"],
                        "entry_price": b["close"],
                        "initial_sl": range_high + sl_buffer,
                        "range_high": range_high,
                        "range_low": range_low,
                        "range_size": range_size
                    }
                    entry_bar_idx = idx
                    break

            if entry_trade is None:
                no_signal_days += 1
                continue

            # 5. Position Lifecycle & Trailing Stop Simulation
            # Evaluate subsequent M5 bars for SL hit or Trailing Stop updates
            current_sl = entry_trade["initial_sl"]
            entry_price = entry_trade["entry_price"]
            direction = entry_trade["direction"]
            trailing_activated = False
            last_trailing_price = entry_price

            exit_time = None
            exit_price = None
            exit_reason = None

            # Scan bars from entry to end of day (e.g. up to 16:00 ET)
            for b in day_bars[entry_bar_idx + 1:]:
                # Check EOD close at 16:00 ET
                if b["time_only"] >= time(16, 0):
                    exit_time = b["time_ny"]
                    exit_price = b["close"]
                    exit_reason = "EOD Close"
                    break

                if direction == "BUY":
                    # Check if Stop Loss was hit on this bar
                    if b["low"] <= current_sl:
                        exit_time = b["time_ny"]
                        exit_price = current_sl
                        exit_reason = "Trailing Stop" if trailing_activated else "Initial SL"
                        break

                    # Check Trailing Stop logic
                    peak_profit = b["high"] - entry_price
                    if peak_profit >= trail_trigger:
                        trailing_activated = True
                        candidate_sl = b["high"] - trail_distance
                        if candidate_sl >= current_sl + trail_step:
                            current_sl = candidate_sl
                            last_trailing_price = b["high"]

                else:  # SELL
                    # Check if Stop Loss was hit on this bar
                    if b["high"] >= current_sl:
                        exit_time = b["time_ny"]
                        exit_price = current_sl
                        exit_reason = "Trailing Stop" if trailing_activated else "Initial SL"
                        break

                    # Check Trailing Stop logic
                    peak_profit = entry_price - b["low"]
                    if peak_profit >= trail_trigger:
                        trailing_activated = True
                        candidate_sl = b["low"] + trail_distance
                        if candidate_sl <= current_sl - trail_step:
                            current_sl = candidate_sl
                            last_trailing_price = b["low"]

            # If still open at end of data for the day
            if exit_price is None:
                last_bar = day_bars[-1]
                exit_time = last_bar["time_ny"]
                exit_price = last_bar["close"]
                exit_reason = "EOD Close"

            # Compute Points P&L & USD Profit
            if direction == "BUY":
                pnl_points = exit_price - entry_price
            else:
                pnl_points = entry_price - exit_price

            # Check max daily loss cap (-200 points)
            if pnl_points < -config.MAX_DAILY_LOSS_POINTS:
                pnl_points = -config.MAX_DAILY_LOSS_POINTS
                total_daily_loss_limit_hits += 1

            # 6. Position Sizing (Dynamic Lot vs Fixed Lot)
            sl_dist = abs(entry_price - entry_trade["initial_sl"])
            if self.use_dynamic_lot:
                risk_cash = running_balance * (self.risk_percent / 100.0)
                cost_per_lot = sl_dist * self.point_usd_per_lot
                raw_lots = (risk_cash / cost_per_lot) if cost_per_lot > 0 else 0.05
                # Normalization to broker volume
                raw_lots = max(0.05, min(10.0, raw_lots))
                steps = round((raw_lots - 0.05) / 0.01)
                trade_lots = round(0.05 + (steps * 0.01), 2)
            else:
                trade_lots = self.lot_size

            # Approximate USD profit for the trade
            pnl_usd = pnl_points * trade_lots * self.point_usd_per_lot
            running_balance += pnl_usd

            if running_balance > peak_balance:
                peak_balance = running_balance
            dd_usd = peak_balance - running_balance
            dd_pct = (dd_usd / peak_balance) * 100 if peak_balance > 0 else 0.0

            trade_record = {
                "Date": d.strftime("%Y-%m-%d"),
                "Direction": direction,
                "Lots": trade_lots,
                "EntryTime": entry_trade["entry_time"].strftime("%H:%M:%S ET"),
                "EntryPrice": entry_price,
                "InitialSL": entry_trade["initial_sl"],
                "ExitTime": exit_time.strftime("%H:%M:%S ET"),
                "ExitPrice": exit_price,
                "ExitReason": exit_reason,
                "PnL_Points": round(pnl_points, 2),
                "PnL_USD": round(pnl_usd, 2),
                "Balance": round(running_balance, 2),
                "DrawdownUSD": round(dd_usd, 2),
                "DrawdownPct": round(dd_pct, 2),
                "RangeSize": round(range_size, 2)
            }
            trades.append(trade_record)

        stats = self._calculate_metrics(trades)
        stats["skipped_low_volatility"] = skipped_low_volatility
        stats["skipped_holidays_weekends"] = skipped_holidays_weekends
        stats["no_signal_days"] = no_signal_days
        stats["total_days_evaluated"] = len(sorted_dates)
        stats["initial_deposit"] = self.initial_deposit
        stats["final_balance"] = round(running_balance, 2)
        stats["net_return_pct"] = round(((running_balance - self.initial_deposit) / self.initial_deposit) * 100, 2)

        self._save_results_csv(trades)
        self.print_report(stats, trades)
        return stats

    def _calculate_metrics(self, trades: List[Dict]) -> Dict:
        """Calculates statistical performance metrics with drawdowns."""
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_points": 0.0,
                "total_usd": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pts": 0.0,
                "max_drawdown_usd": 0.0,
                "max_drawdown_pct": 0.0,
                "consecutive_wins": 0,
                "consecutive_losses": 0
            }

        wins = [t for t in trades if t["PnL_Points"] > 0]
        losses = [t for t in trades if t["PnL_Points"] <= 0]

        total_trades = len(trades)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0.0

        total_pts = sum(t["PnL_Points"] for t in trades)
        total_usd = sum(t["PnL_USD"] for t in trades)

        gross_profit_usd = sum(t["PnL_USD"] for t in wins)
        gross_loss_usd = abs(sum(t["PnL_USD"] for t in losses))

        profit_factor = (gross_profit_usd / gross_loss_usd) if gross_loss_usd > 0 else float("inf")

        avg_win_usd = (gross_profit_usd / win_count) if win_count > 0 else 0.0
        avg_loss_usd = (gross_loss_usd / loss_count) if loss_count > 0 else 0.0

        largest_win_usd = max((t["PnL_USD"] for t in wins), default=0.0)
        largest_loss_usd = min((t["PnL_USD"] for t in losses), default=0.0)

        # Drawdown calculation
        max_dd_usd = max((t.get("DrawdownUSD", 0.0) for t in trades), default=0.0)
        max_dd_pct = max((t.get("DrawdownPct", 0.0) for t in trades), default=0.0)
        max_dd_pts = max_dd_usd / (self.lot_size * self.point_usd_per_lot) if (self.lot_size * self.point_usd_per_lot) > 0 else 0.0

        # Consecutive streaks
        max_cons_wins = 0
        max_cons_losses = 0
        curr_wins = 0
        curr_losses = 0

        for t in trades:
            if t["PnL_Points"] > 0:
                curr_wins += 1
                curr_losses = 0
                if curr_wins > max_cons_wins:
                    max_cons_wins = curr_wins
            else:
                curr_losses += 1
                curr_wins = 0
                if curr_losses > max_cons_losses:
                    max_cons_losses = curr_losses

        return {
            "total_trades": total_trades,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 2),
            "total_points": round(total_pts, 2),
            "total_usd": round(total_usd, 2),
            "gross_profit_usd": round(gross_profit_usd, 2),
            "gross_loss_usd": round(gross_loss_usd, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win_usd": round(avg_win_usd, 2),
            "avg_loss_usd": round(avg_loss_usd, 2),
            "largest_win_usd": round(largest_win_usd, 2),
            "largest_loss_usd": round(largest_loss_usd, 2),
            "max_drawdown_pts": round(max_dd_pts, 2),
            "max_drawdown_usd": round(max_dd_usd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_cons_wins": max_cons_wins,
            "max_cons_losses": max_cons_losses
        }

    def _save_results_csv(self, trades: List[Dict]):
        """Persists individual trade executions into CSV."""
        if not trades:
            return

        headers = list(trades[0].keys())
        with open(self.results_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(trades)

    def print_report(self, stats: Dict, trades: List[Dict]):
        """Prints a clean ASCII performance summary table."""
        deposit = stats.get("initial_deposit", self.initial_deposit)
        final_bal = stats.get("final_balance", deposit)
        net_ret = stats.get("net_return_pct", 0.0)

        print("=" * 78)
        print("               NY-OPEN MOMENTUM BOT v1.0 - BACKTEST REPORT")
        print("=" * 78)
        print(f" Symbol Evaluated       : {self.symbol}")
        print(f" Execution Timeframe    : {self.execution_tf}")
        lot_mode = f"Dynamic ({self.risk_percent}% Risk/Trade)" if self.use_dynamic_lot else f"Fixed ({self.lot_size} lots)"
        print(f" Position Sizing Mode   : {lot_mode}")
        print(f" Initial Deposit        : ${deposit:,.2f}")
        print(f" Final Account Balance  : ${final_bal:,.2f}")
        print(f" Net Return (ROI)       : {net_ret:+.2f}%")
        print("-" * 78)
        print(f" Total Days Evaluated   : {stats.get('total_days_evaluated', 0)}")
        print(f" Low Volatility Skipped : {stats.get('skipped_low_volatility', 0)} days (< 30 pts)")
        print(f" Holidays / Weekends    : {stats.get('skipped_holidays_weekends', 0)} days")
        print(f" Days Without Breakout  : {stats.get('no_signal_days', 0)} days")
        print("-" * 78)
        print(f" Total Executed Trades  : {stats['total_trades']}")
        print(f" Winning Trades         : {stats['wins']}  ({stats['win_rate']}%)")
        print(f" Losing Trades          : {stats['losses']}  ({100 - stats['win_rate']:.2f}%)")
        print(f" Consecutive Streaks    : Max Wins: {stats['max_cons_wins']} | Max Losses: {stats['max_cons_losses']}")
        print("-" * 78)
        print(f" Gross Profit (Wins)    : +${stats['gross_profit_usd']:,.2f}")
        print(f" Gross Loss (Losses)    : -${stats['gross_loss_usd']:,.2f}")
        print(f" Total Net Profit       : ${stats['total_usd']:+,.2f} ({stats['total_points']:+,.2f} pts)")
        print(f" Profit Factor          : {stats['profit_factor']}")
        print(f" Average Win Trade      : +${stats['avg_win_usd']:.2f}")
        print(f" Average Loss Trade     : -${stats['avg_loss_usd']:.2f}")
        print(f" Largest Winning Trade  : +${stats['largest_win_usd']:.2f}")
        print(f" Largest Losing Trade   : -${stats['largest_loss_usd']:.2f}")
        print("-" * 78)
        print(f" Maximum Drawdown ($)   : -${stats['max_drawdown_usd']:,.2f}")
        print(f" Maximum Drawdown (%)   : {stats['max_drawdown_pct']:.2f}%")
        print(f" Maximum Drawdown (Pts) : -{stats['max_drawdown_pts']:.2f} pts")
        print("=" * 78)
        print(f"[+] Detailed trade-by-trade breakdown exported to:")
        print(f"    {self.results_csv}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run NY-Open Momentum Backtest")
    parser.add_argument("--pair", type=str, default="USTECm", help="Symbol to backtest (USTECm, XAUUSDm, EURUSDm, BTCUSDm)")
    parser.add_argument("--all", action="store_true", help="Run backtest across all 4 pairs and display comparison")
    parser.add_argument("--bars", type=int, default=20000, help="Number of M5 bars (default: 20000)")
    parser.add_argument("--deposit", type=float, default=1000.0, help="Initial deposit amount (default: 1000.0)")
    parser.add_argument("--lots", type=float, default=None, help="Fixed lot size (if not using dynamic lot)")
    parser.add_argument("--risk", type=float, default=1.0, help="Risk percent per trade for dynamic lot (default: 1.0)")
    parser.add_argument("--fixed", action="store_true", help="Force fixed lot sizing instead of dynamic lot")
    args = parser.parse_args()

    use_dynamic = not args.fixed

    if args.all:
        all_pairs = ["USTECm", "XAUUSDm", "EURUSDm", "BTCUSDm"]
        print("\n" + "=" * 80)
        print("          MULTI-ASSET PORTFOLIO BACKTEST (USTEC, GOLD, EURUSD, BTC)")
        print("=" * 80)
        summary = []
        for p in all_pairs:
            print(f"\n>>> Running backtest for {p}...")
            eng = NYOpenBacktester(
                symbol=p,
                lookback_bars=args.bars,
                initial_deposit=args.deposit,
                lot_size=args.lots,
                use_dynamic_lot=use_dynamic,
                risk_percent=args.risk
            )
            res = eng.run_backtest()
            if res:
                summary.append({"symbol": p, "stats": res})

        print("\n" + "=" * 85)
        print("                        MULTI-PAIR BACKTEST COMPARISON SUMMARY")
        print("=" * 85)
        print(f"{'Symbol':<10} {'Trades':<8} {'Win Rate':<10} {'Gross Profit':<14} {'Gross Loss':<14} {'Net P&L ($)':<14} {'Max DD %':<10}")
        print("-" * 85)
        for s in summary:
            st = s["stats"]
            print(f"{s['symbol']:<10} {st.get('total_trades',0):<8} {st.get('win_rate',0):<9}% "
                  f"${st.get('gross_profit_usd',0):<13,.2f} -${st.get('gross_loss_usd',0):<12,.2f} "
                  f"${st.get('total_usd',0):<13,.2f} {st.get('max_drawdown_pct',0):<9.2f}%")
        print("=" * 85 + "\n")
    else:
        engine = NYOpenBacktester(
            symbol=args.pair,
            lookback_bars=args.bars,
            initial_deposit=args.deposit,
            lot_size=args.lots,
            use_dynamic_lot=use_dynamic,
            risk_percent=args.risk
        )
        engine.run_backtest()

