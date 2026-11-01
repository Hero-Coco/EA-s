"""
=============================================================================
NY-Open 12 EMA Trend Bot v1.0 - Trade & System Logger
=============================================================================
"""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import config


def setup_logger(name: str = "NYOpen12EMABot") -> logging.Logger:
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
    Appends executed and closed trade records into trades_history.csv.
    """
    csv_file = config.TRADES_CSV_PATH
    headers = [
        "ticket", "symbol", "direction", "lot_size", "open_time",
        "open_price", "close_time", "close_price", "ema12_at_entry",
        "trail_mode", "pnl", "comment"
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
                "close_time": trade_info.get("close_time", ""),
                "close_price": trade_info.get("close_price", 0.0),
                "ema12_at_entry": trade_info.get("ema12_at_entry", 0.0),
                "trail_mode": trade_info.get("trail_mode", ""),
                "pnl": trade_info.get("pnl", 0.0),
                "comment": trade_info.get("comment", "")
            }
            writer.writerow(row)
    except Exception as e:
        logging.getLogger("NYOpen12EMABot").error(f"Failed to record trade to CSV: {e}")
