"""
NY-Open Momentum Bot v1.0 - Unified Interactive Controller
=========================================================
Single-entrypoint manager to run the live bot, stop it cleanly anytime,
execute historical backtests, and test MT5 connectivity.

Usage:
  python bot.py              (Interactive Menu)
  python bot.py --live       (Start Live Bot directly)
  python bot.py --backtest   (Run Backtest directly)
  python bot.py --check      (Check MT5 Connection)
"""

import os
import sys
import time
import signal
import threading
from datetime import datetime
import pytz

import config
from trade_logger import setup_logger, TradeHistoryRecorder
from mt5_manager import MT5Manager
from strategy import NYOpenMomentumStrategy, PortfolioStrategyManager
from backtest import NYOpenBacktester
import check_mt5_connection


class BotController:
    """Manages bot execution lifecycle, keyboard controls, and interactive actions."""

    def __init__(self):
        self.stop_event = threading.Event()
        self.bot_thread = None
        self.logger = setup_logger(config.LOG_FILE_PATH)
        self.mt5_mgr = None
        self.strategy = None

    def _live_worker(self):
        """Worker thread executing the live trading strategy loop."""
        ny_tz = pytz.timezone(config.TIMEZONE_STR)
        last_heartbeat_min = -1

        lot_desc = f"Dynamic ({config.RISK_PERCENT}% Risk/Trade)" if config.USE_DYNAMIC_LOT else f"Fixed ({config.LOT_SIZE} lots)"
        self.logger.info(f"Position Sizing Mode: {lot_desc}")

        try:
            while not self.stop_event.is_set():
                self.strategy.on_tick()

                # Periodic heartbeat every 5 minutes
                now_ny = datetime.now(ny_tz)
                if now_ny.minute % 5 == 0 and now_ny.minute != last_heartbeat_min:
                    last_heartbeat_min = now_ny.minute
                    ticks_summary = []
                    for p in self.active_pairs:
                        tick = self.mt5_mgr.get_current_tick(symbol=p)
                        t_str = f"{tick[0]:.2f}/{tick[1]:.2f}" if tick else "N/A"
                        ticks_summary.append(f"{p}:{t_str}")
                    self.logger.info(
                        f"[HEARTBEAT] NY Time: {now_ny.strftime('%Y-%m-%d %H:%M:%S ET')} | "
                        f"Active Pairs: {' | '.join(ticks_summary)}"
                    )

                # Sleep responsive to stop_event
                self.stop_event.wait(config.LOOP_SLEEP_SECONDS)

        except Exception as e:
            self.logger.exception(f"Error in live worker loop: {e}")
        finally:
            self.logger.info("Live worker loop ended.")

    def start_live_bot(self, pairs: list = None):
        """Starts the live trading bot with interactive stop listening."""
        self.active_pairs = pairs or config.ACTIVE_PAIRS
        print("\n" + "=" * 78)
        print("          STARTING NY-OPEN MOMENTUM BOT v1.0 (PORTFOLIO LIVE)")
        print("=" * 78)
        print(f" Active Pairs ({len(self.active_pairs)})     : {', '.join(self.active_pairs)}")
        print(f" Execution Timeframe  : {config.EXECUTION_TIMEFRAME_NAME} Candle Close")
        print(f" NY Range Window      : 08:00 - 08:05 ET (13:00 UTC / 19:00 BD)")
        lot_info = f"Dynamic ({config.RISK_PERCENT}% Risk of Balance per Trade)" if config.USE_DYNAMIC_LOT else f"Fixed ({config.LOT_SIZE} lots)"
        print(f" Position Sizing      : {lot_info}")
        print("=" * 78)
        print(">>> Bot is RUNNING across all pairs! Type 'stop' or 'q' and press [ENTER] to STOP.")
        print(">>> (Or press Ctrl+C anytime to shutdown safely.)\n")

        self.mt5_mgr = MT5Manager(self.logger)
        if not self.mt5_mgr.initialize():
            print("[ERROR] Could not connect to MT5. Ensure MT5 is running with Algo Trading enabled.")
            return

        recorder = TradeHistoryRecorder(config.CSV_HISTORY_PATH, self.logger)
        self.strategy = PortfolioStrategyManager(self.mt5_mgr, recorder, self.logger, pairs=self.active_pairs)

        self.stop_event.clear()
        self.bot_thread = threading.Thread(target=self._live_worker, daemon=True)
        self.bot_thread.start()

        # Input listener loop for stopping the bot
        try:
            while self.bot_thread.is_alive():
                user_cmd = input().strip().lower()
                if user_cmd in ["stop", "q", "exit", "quit", "s"]:
                    print("\n[*] Stop command received from user. Stopping bot safely...")
                    self.stop_live_bot()
                    break
        except (KeyboardInterrupt, EOFError):
            print("\n[*] KeyboardInterrupt detected (Ctrl+C). Stopping bot safely...")
            self.stop_live_bot()

    def stop_live_bot(self):
        """Signals worker thread to stop and cleanly shuts down MT5."""
        self.stop_event.set()
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=3.0)

        if self.mt5_mgr:
            self.mt5_mgr.shutdown()

        print("[SUCCESS] Bot has been STOPPED cleanly. MT5 connection closed.\n")

    def run_backtest_action(self, bars: int = 20000, deposit: float = 1000.0):
        """Runs the historical backtest simulation and displays report."""
        print(f"\n[*] Starting historical backtest over {bars} M5 bars with ${deposit:,.2f} initial capital...")
        engine = NYOpenBacktester(lookback_bars=bars, initial_deposit=deposit)
        engine.run_backtest()

    def check_connection_action(self):
        """Executes full diagnostic check of MT5 terminal and symbols."""
        check_mt5_connection.main()

    def view_history_action(self):
        """Prints recent rows from trades_history.csv."""
        if not os.path.exists(config.CSV_HISTORY_PATH):
            print(f"\n[INFO] No trades recorded yet. (File {config.CSV_HISTORY_PATH} does not exist yet).")
            return

        print("\n" + "=" * 75)
        print("                 LIVE TRADES HISTORY (trades_history.csv)")
        print("=" * 75)
        with open(config.CSV_HISTORY_PATH, mode="r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-15:]:  # show last 15 entries
                print(line.strip())
        print("=" * 75 + "\n")


def display_menu():
    """Prints the main interactive control panel."""
    print("=" * 75)
    print("           NY-OPEN MOMENTUM BOT v1.0 - PORTFOLIO CONTROL PANEL")
    print("=" * 75)
    print(" [1] Start Live Trading on ALL 4 Pairs (USTEC, Gold, BTC, EURUSD)")
    print(" [2] Start Live Trading on a SINGLE Pair (Select one)")
    print(" [3] Run Historical Backtest (Single Pair or All 4 Pairs Comparison)")
    print(" [4] Test MT5 Connection & Account Status")
    print(" [5] View Live Trade History & Results")
    print(" [6] Exit")
    print("=" * 75)


def main():
    controller = BotController()

    # Support CLI arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--live", "-l", "live", "start"]:
            controller.start_live_bot(config.ACTIVE_PAIRS)
            return
        elif arg in ["--backtest", "-b", "backtest"]:
            bars = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
            controller.run_backtest_action(bars)
            return
        elif arg in ["--check", "-c", "check"]:
            controller.check_connection_action()
            return

    # Interactive Menu
    while True:
        display_menu()
        try:
            choice = input("Enter choice [1-6]: ").strip()
            if choice == "1":
                # Start All 4 Pairs simultaneously
                controller.start_live_bot(config.ACTIVE_PAIRS)
            elif choice == "2":
                print("\nAvailable Pairs:")
                for i, p in enumerate(config.ACTIVE_PAIRS, 1):
                    print(f"  [{i}] {p} ({config.PAIR_PROFILES[p]['description']})")
                p_choice = input(f"Select pair number [1-{len(config.ACTIVE_PAIRS)}]: ").strip()
                if p_choice.isdigit() and 1 <= int(p_choice) <= len(config.ACTIVE_PAIRS):
                    selected = [config.ACTIVE_PAIRS[int(p_choice) - 1]]
                    controller.start_live_bot(selected)
                else:
                    print("[!] Invalid selection, defaulting to all pairs.")
                    controller.start_live_bot(config.ACTIVE_PAIRS)
            elif choice == "3":
                sub = input("Backtest [1] All 4 Pairs Comparison or [2] Single Pair? [Default: 1]: ").strip()
                dep_input = input("Enter starting deposit in USD [Default: 1000]: ").strip()
                deposit = float(dep_input) if dep_input.replace(".", "", 1).isdigit() else 1000.0
                mode_input = input("Use Dynamic Lot sizing? (y/n) [Default: y]: ").strip().lower()
                use_dynamic = (mode_input != "n")
                risk = 1.0
                if use_dynamic:
                    risk_input = input("Enter Risk % per trade [Default: 1.0]: ").strip()
                    risk = float(risk_input) if risk_input.replace(".", "", 1).isdigit() else 1.0
                bars_input = input("Enter number of M5 bars [Default: 20000 ~ 3 months]: ").strip()
                bars = int(bars_input) if bars_input.isdigit() else 20000

                if sub == "2":
                    print("\nSelect Pair to Backtest:")
                    for i, p in enumerate(config.ACTIVE_PAIRS, 1):
                        print(f"  [{i}] {p}")
                    p_sel = input("Choice [1-4]: ").strip()
                    pair_sym = config.ACTIVE_PAIRS[int(p_sel) - 1] if p_sel.isdigit() and 1 <= int(p_sel) <= 4 else "USTECm"
                    eng = NYOpenBacktester(symbol=pair_sym, lookback_bars=bars, initial_deposit=deposit, use_dynamic_lot=use_dynamic, risk_percent=risk)
                    eng.run_backtest()
                else:
                    for p in config.ACTIVE_PAIRS:
                        eng = NYOpenBacktester(symbol=p, lookback_bars=bars, initial_deposit=deposit, use_dynamic_lot=use_dynamic, risk_percent=risk)
                        eng.run_backtest()
            elif choice == "4":
                controller.check_connection_action()
            elif choice == "5":
                controller.view_history_action()
            elif choice == "6":
                print("Exiting NY-Open Momentum Bot. Goodbye!")
                break
            else:
                print("[!] Invalid choice. Please enter a number between 1 and 6.\n")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting NY-Open Momentum Bot. Goodbye!")
            break


if __name__ == "__main__":
    main()

