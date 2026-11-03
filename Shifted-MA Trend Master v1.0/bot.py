"""
=============================================================================
Shifted-MA Trend Master v1.0 - Live Trading Bot CLI
=============================================================================
Automated live execution engine for Shifted-MA Trend Following strategy:
- Ported from MQL5 ExpertMAMA (12 SMA Shift=6 + 12 SMA Trailing Stop)
- Single or multi-pair concurrent execution
- Dynamic lot sizing with account protection
- Interactive terminal menu and clean shutdown handling
=============================================================================
"""

import os
import sys
import time
import signal
import logging
from typing import List, Dict, Any

import config
from mt5_manager import MT5Manager
from strategy import ShiftedMAStrategy
from backtest import ShiftedMABacktester

# Setup Logger
logger = logging.getLogger("ShiftedMA_Live")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(config.LOG_FILE, encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(stream_handler)


class ShiftedMABot:
    """Master controller for live trading."""

    def __init__(self, selected_targets: List[str]):
        self.selected_targets = selected_targets
        self.mt5_mgr = MT5Manager(logger=logger)
        self.strategies: List[ShiftedMAStrategy] = []
        self.running = False

    def setup(self) -> bool:
        """Initializes MT5 and prepares strategies."""
        if not self.mt5_mgr.initialize():
            logger.error("Failed to initialize MT5 connection.")
            return False

        for target in self.selected_targets:
            strat = ShiftedMAStrategy(target, self.mt5_mgr, logger=logger)
            if strat.initialize():
                self.strategies.append(strat)
            else:
                logger.warning(f"Could not initialize strategy for {target}")

        if not self.strategies:
            logger.error("No valid strategies could be initialized.")
            self.mt5_mgr.shutdown()
            return False

        logger.info(f"Initialized {len(self.strategies)} active strategies: {[s.target_name for s in self.strategies]}")
        return True

    def run(self):
        """Main execution loop."""
        if not self.setup():
            return

        self.running = True
        logger.info("=" * 70)
        logger.info(" Shifted-MA Trend Master v1.0 LIVE EXECUTION STARTED")
        logger.info(f" Active Targets: {', '.join(self.selected_targets)}")
        logger.info(f" Evaluation Mode: Bar-by-bar completed candle close")
        logger.info(f" Press Ctrl+C in terminal to stop gracefully.")
        logger.info("=" * 70)

        try:
            while self.running:
                for strat in self.strategies:
                    try:
                        strat.poll()
                    except Exception as e:
                        logger.error(f"Error in strategy {strat.target_name}: {e}", exc_info=True)

                time.sleep(config.CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Ctrl+C detected! Stopping bot...")
        finally:
            self.stop()

    def stop(self):
        """Graceful shutdown."""
        self.running = False
        self.mt5_mgr.shutdown()
        logger.info("Shifted-MA Trend Master v1.0 stopped cleanly.")


def display_menu():
    """Interactive command-line menu."""
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("\n" + "=" * 70)
        print("    SHIFTED-MA TREND MASTER v1.0 - MT5 PYTHON EXPERT ADVISOR")
        print("    (Ported from MQL5 ExpertMAMA: 12 SMA Shift=6 + 12 SMA Trailing)")
        print("=" * 70)
        print(" [1] Run Gold (XAUUSD / XAUUSDm) - M15 Strategy")
        print(" [2] Run Bitcoin (BTCUSD / BTCUSDm) - M15 Strategy")
        print(" [3] Run Nasdaq (USTEC / USTECm) - M15 Strategy")
        print(" [4] Run Multi-Pair Portfolio (Gold + BTC + Nasdaq concurrently)")
        print(" [5] Run Historical Backtest")
        print(" [6] Exit")
        print("=" * 70)

        choice = input(" Select an option (1-6): ").strip()

        if choice == "1":
            bot = ShiftedMABot(["XAUUSD"])
            bot.run()
            input("\nPress Enter to return to menu...")
        elif choice == "2":
            bot = ShiftedMABot(["BTCUSD"])
            bot.run()
            input("\nPress Enter to return to menu...")
        elif choice == "3":
            bot = ShiftedMABot(["USTEC"])
            bot.run()
            input("\nPress Enter to return to menu...")
        elif choice == "4":
            bot = ShiftedMABot(["XAUUSD", "BTCUSD", "USTEC"])
            bot.run()
            input("\nPress Enter to return to menu...")
        elif choice == "5":
            print("\nSelect Backtest Target:")
            print(" 1. XAUUSD (Gold)")
            print(" 2. BTCUSD (Bitcoin)")
            print(" 3. USTEC (Nasdaq 100)")
            sub_choice = input(" Select target (1-3) [default: 1]: ").strip()
            target_map = {"1": "XAUUSD", "2": "BTCUSD", "3": "USTEC"}
            selected = target_map.get(sub_choice, "XAUUSD")
            bars_input = input(" Enter number of bars [default: 2500]: ").strip()
            bars = int(bars_input) if bars_input.isdigit() else 2500

            bt = ShiftedMABacktester(selected, initial_balance=1000.0, n_bars=bars)
            bt.run()
            input("\nPress Enter to return to menu...")
        elif choice == "6":
            print("Exiting...")
            break


if __name__ == "__main__":
    display_menu()

