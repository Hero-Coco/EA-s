"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - Trade & System Logger
=============================================================================
"""

import csv
import logging
import os
from typing import Dict, Any
import config


def setup_logger(name: str = "SMCBot") -> logging.Logger:
    """Configures console and file loggers."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Console Stream Handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 2. File Handler
    try:
        fh = logging.FileHandler(config.LOG_FILE_PATH, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: Could not create file logger at {config.LOG_FILE_PATH}: {e}")

    return logger


def record_trade_to_csv(trade_info: Dict[str, Any]):
    """
    Appends SMC trade records into trades_history.csv.
    """
    csv_file = config.TRADES_CSV_PATH
    headers = [
        "ticket", "symbol", "direction", "lot_size", "open_time",
        "open_price", "sl_price", "tp_price", "close_time", "close_price",
        "fvg_top", "fvg_bottom", "fvg_size", "pnl", "exit_reason"
    ]

    file_exists = os.path.exists(csv_file) and os.path.getsize(csv_file) > 0

    try:
        with open(csv_file, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()

            row = {
                "ticket": trade_info.get("ticket", ""),
                "symbol": trade_info.get("symbol", ""),
                "direction": trade_info.get("direction", ""),
                "lot_size": trade_info.get("lot_size", 0.0),
                "open_time": trade_info.get("open_time", ""),
                "open_price": trade_info.get("open_price", 0.0),
                "sl_price": trade_info.get("sl_price", 0.0),
                "tp_price": trade_info.get("tp_price", 0.0),
                "close_time": trade_info.get("close_time", ""),
                "close_price": trade_info.get("close_price", 0.0),
                "fvg_top": trade_info.get("fvg_top", 0.0),
                "fvg_bottom": trade_info.get("fvg_bottom", 0.0),
                "fvg_size": trade_info.get("fvg_size", 0.0),
                "pnl": trade_info.get("pnl", 0.0),
                "exit_reason": trade_info.get("exit_reason", "")
            }
            writer.writerow(row)
    except Exception as e:
        logging.getLogger("SMCBot").error(f"Failed to record trade to CSV: {e}")
