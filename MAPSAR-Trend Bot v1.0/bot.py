"""
=============================================================================
MAPSAR-Trend Bot v1.0 - Live Trading CLI
=============================================================================
"""

import os
import sys
import time
import logging
from typing import List

import config
from mt5_manager import MT5Manager
from strategy import MAPSARStrategy
from backtest import MAPSARBacktester

logger = logging.getLogger("MAPSAR_Live")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(config.LOG_FILE, encoding='utf-8')
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(stream_handler)


class MAPSARBot:
    def __init__(self, selected_targets: List[str]):
        self.selected_targets = selected_targets
        self.mt5_mgr = MT5Manager(logger=logger)
        self.strategies: List[MAPSARStrategy] = []
        self.running = False

    def setup(self) -> bool:
        if not self.mt5_mgr.initialize():
            return False

        for target in self.selected_targets:
            strat = MAPSARStrategy(target, self.mt5_mgr, logger=logger)
            if strat.initialize():
                self.strategies.append(strat)

        if not self.strategies:
            self.mt5_mgr.shutdown()
            return False
        return True

    def run(self):
        if not self.setup():
            return

        self.running = True
        logger.info("=" * 70)
        logger.info(" MAPSAR-Trend Bot v1.0 LIVE EXECUTION STARTED")
        logger.info(f" Active Targets: {', '.join(self.selected_targets)}")
        logger.info(" Press Ctrl+C to stop.")
        logger.info("=" * 70)

        try:
            while self.running:
                for strat in self.strategies:
                    strat.poll()
                time.sleep(config.CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Ctrl+C detected! Stopping bot...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        self.mt5_mgr.shutdown()
        logger.info("MAPSAR-Trend Bot v1.0 stopped cleanly.")


def display_menu():
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("\n" + "=" * 70)
        print("    MAPSAR-TREND BOT v1.0 - MT5 PYTHON EXPERT ADVISOR")
        print("    (Ported from MQL5 ExpertMAPSAR: 12 SMA Shift=6 + Parabolic SAR)")
        print("=" * 70)
        print(" [1] Run Gold (XAUUSD / XAUUSDm) - M15")
        print(" [2] Run Bitcoin (BTCUSD / BTCUSDm) - M15")
        print(" [3] Run Nasdaq (USTEC / USTECm) - M15")
        print(" [4] Run Multi-Pair Portfolio (Gold + BTC + Nasdaq)")
        print(" [5] Run Historical Backtest")
        print(" [6] Exit")
        print("=" * 70)

        choice = input(" Select an option (1-6): ").strip()
        if choice == "1":
            MAPSARBot(["XAUUSD"]).run()
            input("\nPress Enter to return...")
        elif choice == "2":
            MAPSARBot(["BTCUSD"]).run()
            input("\nPress Enter to return...")
        elif choice == "3":
            MAPSARBot(["USTEC"]).run()
            input("\nPress Enter to return...")
        elif choice == "4":
            MAPSARBot(["XAUUSD", "BTCUSD", "USTEC"]).run()
            input("\nPress Enter to return...")
        elif choice == "5":
            target = input(" Select target [XAUUSD/BTCUSD/USTEC, default XAUUSD]: ").strip() or "XAUUSD"
            MAPSARBacktester(target).run()
            input("\nPress Enter to return...")
        elif choice == "6":
            break


if __name__ == "__main__":
    display_menu()

