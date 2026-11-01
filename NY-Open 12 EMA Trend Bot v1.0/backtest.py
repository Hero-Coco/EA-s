"""
=============================================================================
NY-Open 12 EMA Trend Bot v1.0 - Backtest Engine
=============================================================================
Simulates historical performance on MT5 M5 data for NAS100 and XAUUSD.
Rules:
- At 09:35 ET, check Close of 09:30-09:35 bar vs 12 EMA.
- If Close > 12 EMA -> BUY.
- If Close < 12 EMA -> SELL.
- Initial SL = Entry +/- (ATR * initial_sl_mult).
- Trailing Stop trails bar-by-bar using ATR multiplier.
- No TP (trailing stop exits the trade).
- Max 1 trade per day per asset.
=============================================================================
"""

import argparse
from datetime import datetime, time
from typing import Dict, List, Any
import numpy as np
import pandas as pd
import pytz
import MetaTrader5 as mt5

import config
from trade_logger import setup_logger


class NY12EMABacktester:
    """Historical backtester using real MT5 M5 historical data."""

    def __init__(self, symbol: str, target_name: str, initial_deposit: float = 1000.0):
        self.symbol = symbol
        self.target_name = target_name
        self.initial_deposit = initial_deposit
        self.logger = setup_logger(f"Backtest_{target_name}")
        self.ny_tz = pytz.timezone(config.TIMEZONE_NAME)
        self.profile = config.PAIR_PROFILES.get(target_name, config.PAIR_PROFILES.get("NAS100", {}))

    def fetch_historical_bars(self, num_bars: int = 25000) -> pd.DataFrame:
        """Fetches historical M5 bars from MT5."""
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialization failed! Code: {mt5.last_error()}")

        mt5.symbol_select(self.symbol, True)
        rates = mt5.copy_rates_from_pos(self.symbol, config.TIMEFRAME, 0, num_bars)
        if rates is None or len(rates) == 0:
            raise ValueError(f"No historical rates available for {self.symbol}")

        df = pd.DataFrame(rates)
        df['datetime_utc'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df['datetime_ny'] = df['datetime_utc'].dt.tz_convert(self.ny_tz)
        df.set_index('datetime_ny', inplace=True)
        df.sort_index(inplace=True)

        # Indicators: 12 EMA & 14 ATR
        df['ema12'] = df['close'].ewm(span=config.EMA_PERIOD, adjust=False).mean()

        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = df['tr'].rolling(window=config.ATR_PERIOD).mean()
        return df

    def run(self, num_bars: int = 25000) -> Dict[str, Any]:
        """Runs historical simulation day-by-day."""
        df = self.fetch_historical_bars(num_bars)
        sym_info = mt5.symbol_info(self.symbol)
        contract_size = sym_info.trade_contract_size if sym_info else 1.0
        lot_size = self.profile.get("lot_size", config.DEFAULT_LOT)
        trail_mult = self.profile.get("atr_multiplier", config.ATR_MULTIPLIER)
        initial_sl_mult = self.profile.get("initial_sl_atr_mult", config.INITIAL_SL_ATR_MULT)

        df['date'] = df.index.date
        unique_days = sorted(list(set(df['date'])))

        trades: List[Dict[str, Any]] = []
        running_balance = self.initial_deposit

        for day in unique_days:
            day_bars = df[df['date'] == day]
            # Need bars from 09:30 onwards
            ny_open_bars = day_bars[(day_bars.index.time >= time(9, 30))]
            if len(ny_open_bars) < 2:
                continue

            # First bar is 09:30 - 09:35 ET
            first_bar = ny_open_bars.iloc[0]
            if first_bar.name.time() != time(9, 30):
                continue

            first_close = float(first_bar['close'])
            ema12 = float(first_bar['ema12'])
            atr = float(first_bar['atr']) if not np.isnan(first_bar['atr']) else (first_close * 0.005)

            if first_close > ema12:
                direction = "BUY"
            elif first_close < ema12:
                direction = "SELL"
            else:
                continue

            # Entry happens at open of the next bar (09:35:00 ET)
            subsequent_bars = ny_open_bars.iloc[1:]
            if len(subsequent_bars) == 0:
                continue

            entry_bar = subsequent_bars.iloc[0]
            entry_price = float(entry_bar['open'])
            entry_time = entry_bar.name

            # Initial SL
            sl_dist = atr * initial_sl_mult
            if direction == "BUY":
                current_sl = entry_price - sl_dist
            else:
                current_sl = entry_price + sl_dist

            trade_closed = False
            exit_price = entry_price
            exit_time = entry_time
            exit_reason = "Trailing SL"

            for _, bar in subsequent_bars.iterrows():
                bar_high = float(bar['high'])
                bar_low = float(bar['low'])
                bar_atr = float(bar['atr']) if not np.isnan(bar['atr']) else atr
                trail_dist = bar_atr * trail_mult

                if direction == "BUY":
                    # Check if SL was hit during this bar
                    if bar_low <= current_sl:
                        exit_price = current_sl
                        exit_time = bar.name
                        trade_closed = True
                        break
                    # Otherwise, trail SL up
                    potential_sl = bar_high - trail_dist
                    if potential_sl > current_sl:
                        current_sl = potential_sl

                elif direction == "SELL":
                    # Check if SL was hit during this bar
                    if bar_high >= current_sl:
                        exit_price = current_sl
                        exit_time = bar.name
                        trade_closed = True
                        break
                    # Otherwise, trail SL down
                    potential_sl = bar_low + trail_dist
                    if potential_sl < current_sl:
                        current_sl = potential_sl

                # End of day session close at 16:00 ET
                if bar.name.time() >= config.SESSION_CLOSE_TIME:
                    exit_price = float(bar['close'])
                    exit_time = bar.name
                    exit_reason = "Session Close (16:00 ET)"
                    trade_closed = True
                    break

            if not trade_closed and len(subsequent_bars) > 0:
                exit_price = float(subsequent_bars.iloc[-1]['close'])
                exit_time = subsequent_bars.iloc[-1].name
                exit_reason = "EOD Force Close"

            # Compute Profit/Loss
            if direction == "BUY":
                pnl = (exit_price - entry_price) * contract_size * lot_size
            else:
                pnl = (entry_price - exit_price) * contract_size * lot_size

            running_balance += pnl

            trades.append({
                "Date": day,
                "Symbol": self.symbol,
                "Direction": direction,
                "EntryTime": entry_time.strftime("%Y-%m-%d %H:%M"),
                "EntryPrice": round(entry_price, 4),
                "EMA12": round(ema12, 4),
                "ExitTime": exit_time.strftime("%Y-%m-%d %H:%M"),
                "ExitPrice": round(exit_price, 4),
                "PnL": round(pnl, 2),
                "RunningBalance": round(running_balance, 2),
                "ExitReason": exit_reason
            })

        trades_df = pd.DataFrame(trades)
        return self._compute_summary(trades_df, running_balance)

    def _compute_summary(self, trades_df: pd.DataFrame, final_balance: float) -> Dict[str, Any]:
        """Calculates performance statistics."""
        if trades_df.empty:
            return {"TotalTrades": 0, "WinRate": 0.0, "NetProfit": 0.0, "ROI": 0.0, "MaxDrawdown": 0.0}

        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['PnL'] > 0])
        losing_trades = len(trades_df[trades_df['PnL'] < 0])
        win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

        net_profit = final_balance - self.initial_deposit
        roi = (net_profit / self.initial_deposit) * 100.0

        # Maximum Drawdown calculation
        trades_df['Peak'] = trades_df['RunningBalance'].cummax()
        trades_df['Drawdown'] = trades_df['Peak'] - trades_df['RunningBalance']
        trades_df['DrawdownPct'] = (trades_df['Drawdown'] / trades_df['Peak']) * 100.0
        max_drawdown_pct = trades_df['DrawdownPct'].max()
        max_drawdown_usd = trades_df['Drawdown'].max()

        gross_profit = trades_df[trades_df['PnL'] > 0]['PnL'].sum()
        gross_loss = abs(trades_df[trades_df['PnL'] < 0]['PnL'].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

        # Save CSV
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
        self.logger.info(f"BACKTEST RESULTS: {self.target_name} ({self.symbol})")
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
    parser = argparse.ArgumentParser(description="NY-Open 12 EMA Trend Bot Backtester")
    parser.add_argument("--symbol", type=str, default=None, help="Target: NAS100 or XAUUSD")
    parser.add_argument("--bars", type=int, default=25000, help="Number of historical M5 bars to fetch")
    args = parser.parse_args()

    if not mt5.initialize():
        print("Failed to initialize MT5!")
        return

    # Auto-resolve symbols
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
            print(f"Error: Could not find broker symbol for {target}")
            continue
        tester = NY12EMABacktester(symbol=broker_sym, target_name=target)
        tester.run(num_bars=args.bars)

    mt5.shutdown()


if __name__ == "__main__":
    main()
