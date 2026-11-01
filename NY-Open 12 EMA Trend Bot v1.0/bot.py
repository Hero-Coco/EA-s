"""
=============================================================================
NY-Open 12 EMA Trend Bot v1.0 - Master Control & Execution Script
=============================================================================
Strategy Overview:
- Instrument: NASDAQ 100 (NAS100 / USTECm) & Gold (XAUUSD / XAUUSDm)
- Timeframe: 5-Minute (M5)
- Entry: At 09:35 AM ET (close of 09:30-09:35 candle):
    * Close > 12 EMA -> BUY
    * Close < 12 EMA -> SELL
- Position Management:
    * Trailing Stop Loss (ATR multiplier or fixed points)
    * Take Profit: 0.0 (unlimited upside/downside, let trailing stop exit)
- Risk: Default 0.1 lots (configurable), 1 trade at a time per pair.
=============================================================================
"""

import argparse
import sys
import threading
import time
from datetime import datetime
from typing import Dict, List
import pytz

import config
from mt5_manager import MT5Manager
from strategy import NYOpen12EMAStrategy
from trade_logger import setup_logger
from backtest import NY12EMABacktester

# Global shutdown event
SHUTDOWN_EVENT = threading.Event()


def keyboard_listener():
    """Listens in background for 'stop', 'exit', or 'q' to stop bot gracefully."""
    try:
        while not SHUTDOWN_EVENT.is_set():
            cmd = input().strip().lower()
            if cmd in ["q", "quit", "stop", "exit"]:
                print("\n>>> Stop command received! Shutting down bot gracefully...")
                SHUTDOWN_EVENT.set()
                break
    except (EOFError, KeyboardInterrupt):
        SHUTDOWN_EVENT.set()


def run_live_bot(target_symbols: List[str] = None):
    """
    Runs the continuous live trading loop across specified symbols.
    """
    logger = setup_logger("Main")
    print("=" * 75)
    print("          STARTING NY-OPEN 12 EMA TREND BOT v1.0 (LIVE)")
    print("=" * 75)
    print(f" Targets             : {', '.join(target_symbols or config.ACTIVE_TARGETS)}")
    print(f" Timeframe           : {config.TIMEFRAME_NAME} (5-Minute)")
    print(f" Signal Time         : 09:35 AM ET (Close of first 5-min candle)")
    print(f" Indicator           : {config.EMA_PERIOD}-period EMA")
    print(f" Trailing Stop       : {config.TRAIL_MODE} Mode (Multiplier: {config.ATR_MULTIPLIER}x)")
    print(f" Take Profit         : NONE (Managed strictly by Trailing Stop)")
    print(f" Lot Size            : {config.DEFAULT_LOT} lots")
    print("=" * 75)
    print(">>> Bot is RUNNING! Type 'stop' or 'q' and press [ENTER] to STOP.")
    print(">>> (Or press Ctrl+C anytime to shutdown safely.)\n")

    # Start keyboard listener thread
    listener_thread = threading.Thread(target=keyboard_listener, daemon=True)
    listener_thread.start()

    mt5_mgr = MT5Manager()
    if not mt5_mgr.initialize():
        logger.error("Failed to initialize MT5 terminal. Exiting.")
        return

    resolved_symbols = mt5_mgr.resolve_symbols()
    if not resolved_symbols:
        logger.error("No target symbols could be resolved on your broker. Exiting.")
        mt5_mgr.shutdown()
        return

    # Instantiate strategies for requested targets
    targets = target_symbols if target_symbols else list(resolved_symbols.keys())
    strategies: Dict[str, NYOpen12EMAStrategy] = {}

    for target in targets:
        broker_sym = resolved_symbols.get(target)
        if broker_sym:
            strat = NYOpen12EMAStrategy(target, broker_sym, mt5_mgr)
            strategies[target] = strat
            logger.info(f"Initialized 12 EMA strategy instance for {target} ({broker_sym})")
        else:
            logger.warning(f"Skipping {target}: no broker symbol resolved.")

    if not strategies:
        logger.error("No active strategies initialized. Exiting.")
        mt5_mgr.shutdown()
        return

    ny_tz = pytz.timezone(config.TIMEZONE_NAME)
    last_heartbeat_min = -1

    logger.info("Bot is active and polling M5 bars & tick quotes...")

    try:
        while not SHUTDOWN_EVENT.is_set():
            now_ny = datetime.now(ny_tz)

            # Heartbeat every 5 minutes
            if now_ny.minute % 5 == 0 and now_ny.minute != last_heartbeat_min:
                quotes_summary = []
                for tgt, strat in strategies.items():
                    quote = mt5_mgr.get_market_quote(strat.symbol)
                    if quote:
                        quotes_summary.append(f"{strat.symbol}:{quote[0]:.2f}/{quote[1]:.2f}")
                logger.info(
                    f"[HEARTBEAT] NY Time: {now_ny.strftime('%Y-%m-%d %H:%M:%S ET')} | "
                    f"Quotes: {' | '.join(quotes_summary)}"
                )
                last_heartbeat_min = now_ny.minute

            # Execute on_tick for each active strategy
            for target, strat in strategies.items():
                try:
                    strat.on_tick()
                except Exception as e:
                    logger.error(f"Error executing strategy tick for {target}: {e}", exc_info=True)

            # Sleep briefly (1 second polling interval)
            time.sleep(1.0)

    except KeyboardInterrupt:
        logger.info("Ctrl+C detected! Stopping bot...")
    finally:
        SHUTDOWN_EVENT.set()
        logger.info("Terminating MT5 connection...")
        mt5_mgr.shutdown()
        logger.info("NY-Open 12 EMA Trend Bot shutdown cleanly.")


def run_backtest_cli(target_symbols: List[str] = None):
    """Runs historical backtesting for target symbols."""
    print("\n======================================================================")
    print("            HISTORICAL BACKTEST ENGINE (M5 DATA)")
    print("======================================================================")

    mt5_mgr = MT5Manager()
    if not mt5_mgr.initialize():
        print("Failed to initialize MT5 for backtesting.")
        return

    resolved = mt5_mgr.resolve_symbols()
    targets = target_symbols if target_symbols else config.ACTIVE_TARGETS

    for target in targets:
        broker_sym = resolved.get(target)
        if not broker_sym:
            print(f"Skipping {target}: could not resolve broker symbol.")
            continue
        print(f"\n--- Backtesting {target} ({broker_sym}) ---")
        tester = NY12EMABacktester(broker_sym, target)
        tester.run(num_bars=25000)

    mt5_mgr.shutdown()


def print_menu():
    """Displays interactive CLI control panel."""
    print("\n" + "=" * 70)
    print("       NY-OPEN 12 EMA TREND BOT v1.0 - CONTROL PANEL")
    print("=" * 70)
    print(" [1] Start Live Trading (Both NAS100 & XAUUSD)")
    print(" [2] Start Live Trading (NAS100 Only)")
    print(" [3] Start Live Trading (XAUUSD Gold Only)")
    print(" [4] Run Historical Backtest (Analyzes past 3+ months)")
    print(" [5] Test MT5 Connection & Account Status")
    print(" [6] Exit")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="NY-Open 12 EMA Trend Bot v1.0")
    parser.add_argument("--live", action="store_true", help="Launch live trading directly")
    parser.add_argument("--backtest", action="store_true", help="Run historical backtest directly")
    parser.add_argument("--symbol", type=str, default=None, help="Target symbol (NAS100 or XAUUSD)")
    args = parser.parse_args()

    if args.live:
        targets = [args.symbol] if args.symbol else config.ACTIVE_TARGETS
        run_live_bot(targets)
        return

    if args.backtest:
        targets = [args.symbol] if args.symbol else config.ACTIVE_TARGETS
        run_backtest_cli(targets)
        return

    # Interactive Menu
    while True:
        print_menu()
        choice = input("Enter choice [1-6]: ").strip()

        if choice == "1":
            run_live_bot(config.ACTIVE_TARGETS)
            break
        elif choice == "2":
            run_live_bot(["NAS100"])
            break
        elif choice == "3":
            run_live_bot(["XAUUSD"])
            break
        elif choice == "4":
            run_backtest_cli(config.ACTIVE_TARGETS)
        elif choice == "5":
            mgr = MT5Manager()
            if mgr.initialize():
                mgr.resolve_symbols()
                mgr.shutdown()
        elif choice == "6":
            print("Exiting. Happy Trading!")
            sys.exit(0)
        else:
            print("Invalid choice, please select [1-6].")


if __name__ == "__main__":
    main()

