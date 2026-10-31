"""
NY-Open Momentum Bot v1.0 - Main Application Entrypoint
======================================================
Automated Expert Advisor for MetaTrader 5 executing the New York Open
Momentum strategy on NAS100 (Nasdaq 100).

Author: Antigravity Algorithmic Trading Systems
Version: 1.0
Language: Python 3.8+
"""

import sys
import time
import signal
from datetime import datetime
import pytz

import config
from trade_logger import setup_logger, TradeHistoryRecorder
from mt5_manager import MT5Manager
from strategy import NYOpenMomentumStrategy


def print_banner(logger, symbol_name):
    """Displays stylized startup banner with configuration parameters."""
    banner = f"""
================================================================================
          NY-OPEN MOMENTUM BOT v1.0 (NAS100 M15 / M5 BREAKOUT)
================================================================================
 [Broker Symbol]         : {symbol_name}
 [Execution Timeframe]   : {config.EXECUTION_TIMEFRAME_NAME} Candle Close
 [Range Calculation]     : M5 (09:30 - 09:35 ET)
 [Timing Window]         : 09:30 - 09:35 ET (Breakout Box) | Trade Window: {config.TRADE_WINDOW_START} - {config.TRADE_WINDOW_END} ET
 [Lot Sizing Mode]     : {'Dynamic (' + str(config.RISK_PERCENT) + '% Risk per Trade)' if config.USE_DYNAMIC_LOT else 'Fixed (' + str(config.LOT_SIZE) + ' lots)'}
 [Min Range Filter]      : {config.MIN_RANGE_POINTS} index points (skip low volatility)
 [Stop Loss Buffer]      : {config.SL_BUFFER_POINTS} index points beyond box
 [Trailing Trigger]      : +{config.TRAILING_TRIGGER_POINTS} points profit
 [Trailing Distance]     : {config.TRAILING_DISTANCE_POINTS} points behind price
 [Trailing Step]         : {config.TRAILING_STEP_POINTS} points incremental move
 [Max Daily Loss]        : -{config.MAX_DAILY_LOSS_POINTS} points
 [Max Trades / Day]      : {config.MAX_TRADES_PER_DAY} trade
 [Magic Number]          : {config.MAGIC_NUMBER}
 [CSV History]           : {config.CSV_HISTORY_PATH}
================================================================================
"""
    for line in banner.strip().split("\n"):
        logger.info(line)


def main():
    logger = setup_logger(config.LOG_FILE_PATH)
    logger.info("Initializing NY-Open Momentum Bot v1.0...")

    # Initialize MT5 Connection & Auto-detection
    mt5_mgr = MT5Manager(logger)
    if not mt5_mgr.initialize():
        logger.critical(
            "Could not connect to MetaTrader 5 terminal. "
            "Please ensure MT5 is installed, open, and 'Allow Algo Trading' is enabled."
        )
        sys.exit(1)

    print_banner(logger, mt5_mgr.symbol)

    recorder = TradeHistoryRecorder(config.CSV_HISTORY_PATH, logger)
    strategy = NYOpenMomentumStrategy(mt5_mgr, recorder, logger)

    # Graceful shutdown handler
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        logger.warning("\nShutdown signal received (Ctrl+C). Terminating bot gracefully...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ny_tz = pytz.timezone(config.TIMEZONE_STR)
    last_heartbeat_minute = -1

    logger.info("Bot is active and running. Press Ctrl+C in terminal to stop.")

    try:
        while running:
            # Execute one strategy cycle
            strategy.on_tick()

            # Periodic status heartbeat logged every 10 minutes during waiting phases
            now_ny = datetime.now(ny_tz)
            if now_ny.minute % 10 == 0 and now_ny.minute != last_heartbeat_minute:
                last_heartbeat_minute = now_ny.minute
                tick = mt5_mgr.get_current_tick()
                tick_str = f"Bid: {tick[0]:.2f} / Ask: {tick[1]:.2f}" if tick else "N/A"
                logger.info(
                    f"[HEARTBEAT] NY Time: {now_ny.strftime('%Y-%m-%d %H:%M:%S ET')} | "
                    f"Symbol: {mt5_mgr.symbol} ({tick_str}) | "
                    f"Range Box: [{strategy.range_low:.2f} - {strategy.range_high:.2f}] (Armed: {strategy.range_valid}) | "
                    f"Trades Today: {strategy.trades_count_today}/{config.MAX_TRADES_PER_DAY}"
                )

            time.sleep(config.LOOP_SLEEP_SECONDS)

    except Exception as e:
        logger.exception(f"Unhandled runtime exception: {e}")
    finally:
        logger.info("Closing MT5 connection...")
        mt5_mgr.shutdown()
        logger.info("NY-Open Momentum Bot stopped cleanly.")


if __name__ == "__main__":
    main()

