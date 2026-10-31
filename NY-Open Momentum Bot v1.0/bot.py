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
from strategy import NYOpenMomentumStrategy
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
                    tick = self.mt5_mgr.get_current_tick()
                    tick_str = f"Bid: {tick[0]:.2f} / Ask: {tick[1]:.2f}" if tick else "N/A"
                    self.logger.info(
                        f"[HEARTBEAT] NY Time: {now_ny.strftime('%Y-%m-%d %H:%M:%S ET')} | "
                        f"{self.mt5_mgr.symbol} ({tick_str}) | "
                        f"Trades Today: {self.strategy.trades_count_today}/{config.MAX_TRADES_PER_DAY}"
                    )

                # Sleep responsive to stop_event
                self.stop_event.wait(config.LOOP_SLEEP_SECONDS)

        except Exception as e:
            self.logger.exception(f"Error in live worker loop: {e}")
        finally:
            self.logger.info("Live worker loop ended.")

    def start_live_bot(self):
        """Starts the live trading bot with interactive stop listening."""
        print("\n" + "=" * 75)
        print("            STARTING NY-OPEN MOMENTUM BOT v1.0 (LIVE)")
        print("=" * 75)
        print(f" Symbol               : {config.FORCED_SYMBOL or 'Auto-Detect'}")
        print(f" Execution Timeframe  : {config.EXECUTION_TIMEFRAME_NAME} Candle Close")
        print(f" NY Range Window      : 09:30 - 09:35 ET")
        lot_info = f"Dynamic ({config.RISK_PERCENT}% Risk of Balance)" if config.USE_DYNAMIC_LOT else f"Fixed ({config.LOT_SIZE} lots)"
        print(f" Position Sizing      : {lot_info}")
        print("=" * 75)
        print(">>> Bot is RUNNING! Type 'stop' or 'q' and press [ENTER] to STOP.")
        print(">>> (Or press Ctrl+C anytime to shutdown safely.)\n")

        self.mt5_mgr = MT5Manager(self.logger)
        if not self.mt5_mgr.initialize():
            print("[ERROR] Could not connect to MT5. Ensure MT5 is running with Algo Trading enabled.")
            return

        recorder = TradeHistoryRecorder(config.CSV_HISTORY_PATH, self.logger)
        self.strategy = NYOpenMomentumStrategy(self.mt5_mgr, recorder, self.logger)

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
    print("=" * 70)
    print("           NY-OPEN MOMENTUM BOT v1.0 - CONTROL PANEL")
    print("=" * 70)
    print(" [1] Start Live Trading Bot  (Type 'stop' or 'q' to stop cleanly)")
    print(" [2] Run Historical Backtest (Analyzes past 3+ months of data)")
    print(" [3] Test MT5 Connection & Account Status")
    print(" [4] View Live Trade History & Results")
    print(" [5] Exit")
    print("=" * 70)


def main():
    controller = BotController()

    # Support CLI arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--live", "-l", "live", "start"]:
            controller.start_live_bot()
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
            choice = input("Enter choice [1-5]: ").strip()
            if choice == "1":
                controller.start_live_bot()
            elif choice == "2":
                dep_input = input("Enter starting deposit in USD [Default: 1000]: ").strip()
                deposit = float(dep_input) if dep_input.replace(".", "", 1).isdigit() else 1000.0
                mode_input = input("Use Dynamic Lot sizing? (y/n) [Default: y]: ").strip().lower()
                use_dynamic = (mode_input != "n")
                risk = 1.0
                if use_dynamic:
                    risk_input = input("Enter Risk % per trade [Default: 1.0]: ").strip()
                    risk = float(risk_input) if risk_input.replace(".", "", 1).isdigit() else 1.0
                bars_input = input("Enter number of M5 bars to backtest [Default: 20000 ~ 3 months]: ").strip()
                bars = int(bars_input) if bars_input.isdigit() else 20000
                engine = NYOpenBacktester(
                    lookback_bars=bars,
                    initial_deposit=deposit,
                    use_dynamic_lot=use_dynamic,
                    risk_percent=risk
                )
                engine.run_backtest()
            elif choice == "3":
                controller.check_connection_action()
            elif choice == "4":
                controller.view_history_action()
            elif choice == "5":
                print("Exiting NY-Open Momentum Bot. Goodbye!")
                break
            else:
                print("[!] Invalid choice. Please enter a number between 1 and 5.\n")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting NY-Open Momentum Bot. Goodbye!")
            break


if __name__ == "__main__":
    main()

