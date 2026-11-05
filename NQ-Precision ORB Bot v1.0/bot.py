"""
=============================================================================
NQ-Precision ORB Bot v1.0 - Main Master Execution Engine
=============================================================================
Runs continuous multi-pair trading across:
- USTEC / NAS100 (Nasdaq 100 Index)
- XAUUSD (Gold)
- BTCUSD (Bitcoin)

Features:
- 09:30 - 09:45 ET M1 Opening Range construction
- 09:59:55 ET Breakout Snapshot Entry Trigger
- Institutional RVOL & ATR Regime filters
- Dynamic Lot sizing based on account balance & ATR Stop Loss
- 8-Minute Time-Stop Auto-Close
- Automatic State Recovery of open positions on restart
=============================================================================
"""

import logging
import sys
import threading
import time
from datetime import datetime
from typing import Dict, List
import pytz

import config
from mt5_manager import MT5Manager
from strategy import NQPrecisionORBStrategy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("NQPrecisionMaster")

SHUTDOWN_EVENT = threading.Event()


def keyboard_listener():
    """Listens in background for 'q', 'quit', 'stop', or 'exit' command."""
    try:
        while not SHUTDOWN_EVENT.is_set():
            cmd = input().strip().lower()
            if cmd in ["q", "quit", "stop", "exit"]:
                logger.info("Stop command received! Shutting down gracefully...")
                SHUTDOWN_EVENT.set()
                break
    except (EOFError, KeyboardInterrupt):
        SHUTDOWN_EVENT.set()


def run_bot(targets: List[str] = None):
    """Main execution loop for all enabled asset profiles."""
    selected_targets = targets or list(config.TARGET_PROFILES.keys())

    print("=" * 75)
    print("       STARTING NQ-PRECISION ORB BOT v1.0 (MULTI-ASSET)")
    print("=" * 75)
    print(f" Target Pairs      : {', '.join(selected_targets)}")
    print(f" Timeframe         : {config.TIMEFRAME} (1-Minute)")
    print(f" ORB Window        : 09:30:00 - 09:45:00 ET (Range Lock)")
    print(f" Trigger Snapshot  : 09:59:55 ET (Cash Open + 30m Breakout)")
    print(f" Stop Loss (SL)    : 2.2x ATR(14)")
    print(f" Take Profit (TP)  : 0.3x ATR(14)")
    print(f" Time-Stop Close   : {config.CLOSE_AFTER_MIN} Minutes (Auto-Flat)")
    print(f" Lot Sizing        : {'Dynamic (1.0% Equity Risk)' if config.USE_DYNAMIC_LOT else 'Fixed'}")
    print(f" State Recovery    : ACTIVE (Adopts open positions upon bot restart)")
    print("=" * 75)
    print(">>> Bot is active! Type 'stop' or 'q' and press [ENTER] to exit safely.")
    print(">>> (Or press Ctrl+C anytime)\n")

    listener = threading.Thread(target=keyboard_listener, daemon=True)
    listener.start()

    mt5_mgr = MT5Manager(logger=logger)
    if not mt5_mgr.initialize():
        logger.error("Failed to initialize MT5 terminal. Exiting.")
        return

    strategies: Dict[str, NQPrecisionORBStrategy] = {}
    for tgt in selected_targets:
        strat = NQPrecisionORBStrategy(tgt, mt5_mgr, logger=logger)
        if strat.initialize():
            strategies[tgt] = strat
            logger.info(f"Initialized strategy instance for {tgt} ({strat.symbol})")
        else:
            logger.warning(f"Could not initialize strategy for {tgt}; skipping.")

    if not strategies:
        logger.error("No active strategies could be initialized. Exiting.")
        mt5_mgr.shutdown()
        return

    ny_tz = pytz.timezone(config.TIMEZONE_NAME)
    last_heartbeat_min = -1

    try:
        while not SHUTDOWN_EVENT.is_set():
            now_ny = datetime.now(ny_tz)

            # Heartbeat every 5 minutes
            if now_ny.minute % 5 == 0 and now_ny.minute != last_heartbeat_min:
                last_heartbeat_min = now_ny.minute
                quotes = []
                for tgt, strat in strategies.items():
                    tick = mt5_mgr.mt5.symbol_info_tick(strat.symbol) if hasattr(mt5_mgr, 'mt5') else None
                    info = mt5_mgr.get_symbol_info(strat.symbol)
                    t = mt5_mgr.mt5_manager_tick if hasattr(mt5_mgr, 'mt5_manager_tick') else None
                    tick = mt5_mgr.get_symbol_info(strat.symbol)
                    quotes.append(f"{tgt}:{strat.symbol}")
                logger.info(f"[HEARTBEAT] NY Time: {now_ny.strftime('%Y-%m-%d %H:%M:%S ET')} | Active pairs: {len(strategies)}")

            # Execute tick cycle for each active pair
            for tgt, strat in strategies.items():
                try:
                    strat.on_tick()
                except Exception as e:
                    logger.error(f"Error in {tgt} on_tick: {e}")

            time.sleep(1.0)

    except KeyboardInterrupt:
        logger.info("Ctrl+C detected! Shutting down...")
    finally:
        mt5_mgr.shutdown()
        logger.info("NQ-Precision ORB Bot shut down cleanly.")


if __name__ == "__main__":
    run_bot()
