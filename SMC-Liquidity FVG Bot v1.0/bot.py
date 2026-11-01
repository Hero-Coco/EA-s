"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - Master Control & Execution Script
=============================================================================
Specializing in Smart Money Concepts (SMC):
- Target Assets: NIFTY (IN50m), Gold (XAUUSDm), Bitcoin (BTCUSDm)
- Timeframe: 5-Minute (M5)
- Concepts:
    1. Liquidity Sweep Detection (20-candle swing extreme break & close back)
    2. Market Structure Shift (MSS) Confirmation
    3. Fair Value Gap (FVG) >= min size points
    4. FVG Mitigation & Engulfing Candle Confirmation
    5. SL: Beyond FVG | TP: Opposite liquidity pool | Max 2 trades/day
=============================================================================
"""

import argparse
import sys
import threading
import time
from datetime import datetime
from typing import Dict, List
import pandas as pd

import config
from mt5_manager import MT5Manager
from strategy import SMCLiquidityStrategy
from trade_logger import setup_logger
from backtest import SMCBacktester

# Global shutdown event
SHUTDOWN_EVENT = threading.Event()


def keyboard_listener():
    """Listens in background for 'stop', 'exit', or 'q' to stop bot gracefully."""
    try:
        while not SHUTDOWN_EVENT.is_set():
            cmd = input().strip().lower()
            if cmd in ["q", "quit", "stop", "exit"]:
                print("\n>>> Stop command received! Shutting down SMC Bot gracefully...")
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
    print("          STARTING SMC-LIQUIDITY FVG BOT v1.0 (LIVE)")
    print("=" * 75)
    print(f" Targets             : {', '.join(target_symbols or config.ACTIVE_TARGETS)}")
    print(f" Timeframe           : {config.TIMEFRAME_NAME} (5-Minute)")
    print(f" Swing Lookback      : {config.SWING_LOOKBACK} candles")
    print(f" Lot Size            : {config.DEFAULT_LOT} lots")
    print(f" Max Trades / Day    : {config.MAX_TRADES_PER_DAY} trades")
    print("=" * 75)
    print(">>> Bot is RUNNING! Type 'stop' or 'q' and press [ENTER] to STOP.")
    print(">>> (Or press Ctrl+C anytime to shutdown safely.)\n")

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

    targets = target_symbols if target_symbols else list(resolved_symbols.keys())
    strategies: Dict[str, SMCLiquidityStrategy] = {}

    for target in targets:
        broker_sym = resolved_symbols.get(target)
        if broker_sym:
            strat = SMCLiquidityStrategy(target, broker_sym, mt5_mgr)
            strategies[target] = strat
            logger.info(f"Initialized SMC strategy instance for {target} ({broker_sym})")
        else:
            logger.warning(f"Skipping {target}: no broker symbol resolved.")

    if not strategies:
        logger.error("No active strategies initialized. Exiting.")
        mt5_mgr.shutdown()
        return

    logger.info("SMC Bot is active and monitoring M5 candle closes...")
    last_heartbeat_min = -1

    try:
        while not SHUTDOWN_EVENT.is_set():
            now = datetime.now()

            # Heartbeat every 5 minutes
            if now.minute % 5 == 0 and now.minute != last_heartbeat_min:
                quotes_summary = []
                for tgt, strat in strategies.items():
                    quote = mt5_mgr.get_market_quote(strat.symbol)
                    if quote:
                        quotes_summary.append(f"{strat.symbol}:{quote[0]:.2f}/{quote[1]:.2f}")
                logger.info(
                    f"[HEARTBEAT] Local Time: {now.strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"Quotes: {' | '.join(quotes_summary)}"
                )
                last_heartbeat_min = now.minute

            # Run tick logic for each active strategy
            for target, strat in strategies.items():
                try:
                    strat.on_tick()
                except Exception as e:
                    logger.error(f"Error executing SMC tick for {target}: {e}", exc_info=True)

            # Sleep briefly (1.5 second polling interval)
            time.sleep(1.5)

    except KeyboardInterrupt:
        logger.info("Ctrl+C detected! Stopping bot...")
    finally:
        SHUTDOWN_EVENT.set()
        logger.info("Terminating MT5 connection...")
        mt5_mgr.shutdown()
        logger.info("SMC-Liquidity FVG Bot shutdown cleanly.")


def run_backtest_cli(target_symbols: List[str] = None):
    """Runs historical backtesting for target symbols."""
    print("\n======================================================================")
    print("         SMC HISTORICAL BACKTEST ENGINE (M5 DATA)")
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
        tester = SMCBacktester(broker_sym, target)
        tester.run(num_bars=25000)

    mt5_mgr.shutdown()


def print_menu():
    """Displays interactive CLI control panel."""
    print("\n" + "=" * 70)
    print("       SMC-LIQUIDITY FVG BOT v1.0 - CONTROL PANEL")
    print("=" * 70)
    print(" [1] Start Live SMC Trading (All: NIFTY, Gold, BTC)")
    print(" [2] Start Live SMC Trading (NIFTY Only)")
    print(" [3] Start Live SMC Trading (Gold Only)")
    print(" [4] Start Live SMC Trading (BTC Only)")
    print(" [5] Run Historical Backtest (Analyzes past 3+ months)")
    print(" [6] Test MT5 Connection & Account Status")
    print(" [7] Exit")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="SMC-Liquidity FVG Bot v1.0")
    parser.add_argument("--live", action="store_true", help="Launch live trading directly")
    parser.add_argument("--backtest", action="store_true", help="Run historical backtest directly")
    parser.add_argument("--symbol", type=str, default=None, help="Target symbol (NIFTY, XAUUSD, BTCUSD)")
    args = parser.parse_args()

    if args.live:
        targets = [args.symbol] if args.symbol else config.ACTIVE_TARGETS
        run_live_bot(targets)
        return

    if args.backtest:
        targets = [args.symbol] if args.symbol else config.ACTIVE_TARGETS
        run_backtest_cli(targets)
        return

    # Interactive Menu Loop
    while True:
        print_menu()
        choice = input("Enter choice [1-7]: ").strip()

        if choice == "1":
            run_live_bot(config.ACTIVE_TARGETS)
            break
        elif choice == "2":
            run_live_bot(["NIFTY"])
            break
        elif choice == "3":
            run_live_bot(["XAUUSD"])
            break
        elif choice == "4":
            run_live_bot(["BTCUSD"])
            break
        elif choice == "5":
            run_backtest_cli(config.ACTIVE_TARGETS)
        elif choice == "6":
            mgr = MT5Manager()
            if mgr.initialize():
                mgr.resolve_symbols()
                mgr.shutdown()
        elif choice == "7":
            print("Exiting. Happy Trading!")
            sys.exit(0)
        else:
            print("Invalid choice, please select [1-7].")


if __name__ == "__main__":
    main()
