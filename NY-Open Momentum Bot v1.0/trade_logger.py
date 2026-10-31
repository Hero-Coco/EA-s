"""
NY-Open Momentum Bot v1.0 - Logger & CSV Trade History Module
=============================================================
Manages console output, file logs, and structured CSV trade history.
"""

import os
import csv
import logging
from datetime import datetime


def setup_logger(log_file_path: str) -> logging.Logger:
    """Configures multi-channel logger writing to console and log file."""
    logger = logging.getLogger("NYOpenMomentumBot")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File Handler
    try:
        fh = logging.FileHandler(log_file_path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: Could not create file logger at {log_file_path}: {e}")

    return logger


class TradeHistoryRecorder:
    """Records executed and closed trades to a structured CSV file."""

    CSV_HEADERS = [
        "TradeID",
        "Timestamp",
        "Symbol",
        "Action",
        "Lots",
        "EntryPrice",
        "InitialSL",
        "ExitPrice",
        "CloseTime",
        "PnL_Points",
        "PnL_Currency",
        "ExitReason",
        "MagicNumber"
    ]

    def __init__(self, csv_path: str, logger: logging.Logger):
        self.csv_path = csv_path
        self.logger = logger
        self._ensure_file_initialized()

    def _ensure_file_initialized(self):
        """Ensures CSV exists and has appropriate header row."""
        try:
            if not os.path.exists(self.csv_path):
                os.makedirs(os.path.dirname(os.path.abspath(self.csv_path)), exist_ok=True)
                with open(self.csv_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(self.CSV_HEADERS)
        except Exception as e:
            self.logger.error(f"Failed to initialize CSV history file at {self.csv_path}: {e}")

    def record_trade(
        self,
        trade_id: int,
        timestamp: str,
        symbol: str,
        action: str,
        lots: float,
        entry_price: float,
        initial_sl: float,
        exit_price: float,
        close_time: str,
        pnl_points: float,
        pnl_currency: float,
        exit_reason: str,
        magic: int
    ):
        """Appends a closed trade record to the CSV file."""
        row = [
            trade_id,
            timestamp,
            symbol,
            action,
            f"{lots:.2f}",
            f"{entry_price:.2f}",
            f"{initial_sl:.2f}",
            f"{exit_price:.2f}",
            close_time,
            f"{pnl_points:.2f}",
            f"{pnl_currency:.2f}",
            exit_reason,
            magic
        ]

        try:
            with open(self.csv_path, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row)
            self.logger.info(
                f"Trade #{trade_id} saved to CSV: {action} on {symbol} | "
                f"Points P&L: {pnl_points:+.2f} pts | Currency: ${pnl_currency:+.2f}"
            )
        except Exception as e:
            self.logger.error(f"Failed to write trade to CSV: {e}")

