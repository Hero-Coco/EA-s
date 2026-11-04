"""
NY-Open Momentum Bot v1.0 - Configuration Module
=================================================
Centralized parameters for MT5 connection, strategy rules, risk controls,
and timing configurations.
"""

import os
from datetime import time

# ==============================================================================
# 1. METATRADER 5 CONNECTION SETTINGS
# ==============================================================================
# Path to terminal64.exe (auto-detected on your system)
MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Optional login credentials (leave None to attach to currently logged-in account in MT5)
MT5_LOGIN = None
MT5_PASSWORD = None
MT5_SERVER = None
MT5_TIMEOUT_MS = 60000

# ==============================================================================
# 2. SYMBOL & TIMEFRAME CONFIGURATION
# ==============================================================================
# Candidates for auto-detection across different brokers (Exness, FTMO, IC Markets, etc.)
SYMBOL_CANDIDATES = [
    "USTECm",      # Exness Standard / Trial account symbol for Nasdaq 100
    "XAUUSDm",     # Gold vs US Dollar
    "BTCUSDm",     # Bitcoin vs US Dollar
    "EURUSDm",     # Euro vs US Dollar
    "USTEC",
    "XAUUSD",
    "BTCUSD",
    "EURUSD"
]

# Active single symbol override (leave None to trade all ACTIVE_PAIRS in portfolio mode)
FORCED_SYMBOL = None

# ==============================================================================
# MULTI-ASSET PORTFOLIO TRADING
# ==============================================================================
# All pairs monitored and traded SIMULTANEOUSLY in Live Trading mode:
ACTIVE_PAIRS = [
    "USTECm",      # Nasdaq 100 Index
    "XAUUSDm",     # Gold vs US Dollar
    "BTCUSDm",     # Bitcoin vs US Dollar
    "EURUSDm"      # Euro vs US Dollar
]

# Magic numbers uniquely assigned per pair to prevent cross-trade interference
MAGIC_NUMBERS = {
    "USTECm": 930101,
    "XAUUSDm": 930102,
    "BTCUSDm": 930103,
    "EURUSDm": 930104
}

# ==============================================================================
# MULTI-ASSET PROFILES & RISK SCALING
# ==============================================================================
# Customized volatility, buffer, and trailing stop profiles for each asset class
PAIR_PROFILES = {
    "USTECm": {
        "name": "USTECm",
        "description": "Nasdaq 100 Index",
        "min_range_points": 30.0,
        "sl_buffer_points": 10.0,
        "trailing_trigger_points": 50.0,
        "trailing_distance_points": 30.0,
        "trailing_step_points": 5.0,
        "index_point_size": 1.0,
        "candidates": ["USTECm", "USTEC", "NAS100", "NAS100.m", "US100"]
    },
    "XAUUSDm": {
        "name": "XAUUSDm",
        "description": "Gold vs US Dollar",
        "min_range_points": 3.0,          # $3.00 gold price move
        "sl_buffer_points": 1.0,          # $1.00 buffer
        "trailing_trigger_points": 5.0,   # $5.00 profit activation
        "trailing_distance_points": 3.0,  # $3.00 trailing distance
        "trailing_step_points": 0.5,      # $0.50 trailing step
        "index_point_size": 1.0,
        "candidates": ["XAUUSDm", "XAUUSD", "GOLD", "GOLD.m"]
    },
    "EURUSDm": {
        "name": "EURUSDm",
        "description": "Euro vs US Dollar",
        "min_range_points": 0.0008,       # 8 pips
        "sl_buffer_points": 0.0003,       # 3 pips
        "trailing_trigger_points": 0.0015,# 15 pips
        "trailing_distance_points": 0.0010,# 10 pips
        "trailing_step_points": 0.0002,   # 2 pips
        "index_point_size": 0.0001,       # 1 pip
        "candidates": ["EURUSDm", "EURUSD", "EURUSD_m"]
    },
    "BTCUSDm": {
        "name": "BTCUSDm",
        "description": "Bitcoin vs US Dollar",
        "min_range_points": 150.0,        # $150 BTC move
        "sl_buffer_points": 50.0,         # $50 buffer
        "trailing_trigger_points": 250.0, # $250 profit activation
        "trailing_distance_points": 150.0,# $150 trailing distance
        "trailing_step_points": 25.0,     # $25 trailing step
        "index_point_size": 1.0,
        "candidates": ["BTCUSDm", "BTCUSD", "BTCUSDTm", "BTCUSDT"]
    }
}

def get_pair_profile(symbol_name: str) -> dict:
    """Returns the parameter profile matching the given symbol or a sensible fallback."""
    if not symbol_name:
        return PAIR_PROFILES["USTECm"]
    upper = symbol_name.upper()
    for key, prof in PAIR_PROFILES.items():
        if key.upper() in upper or any(c.upper() in upper for c in prof["candidates"]):
            return prof
    return PAIR_PROFILES["USTECm"]

# Point definition for NAS100 index:
# On Nasdaq 100, 1 index point is 1.0 (e.g., from 20500.00 to 20501.00 is 1 point)
# Most brokers quote NAS100 with 1 or 2 decimals.
INDEX_POINT_SIZE = 1.0

# ==============================================================================
# 3. TIMING & SESSION FILTERS (US/EASTERN TIMEZONE)
# ==============================================================================
TIMEZONE_STR = "US/Eastern"

# Timing of Forex/Gold New York Market Open (08:00 AM ET / 13:00 UTC / 19:00 BD Time)
# 08:00 ET: NY Forex/Gold opens, start of 5-minute opening candle
NY_OPEN_TIME = time(8, 0)

# 08:05 ET: 5-minute candle closes, establishing the Breakout Box
NY_RANGE_END_TIME = time(8, 5)

# Session Window for Breakout Monitoring:
# 08:05 ET to 11:00 ET (allows capturing the morning momentum breakout)
# If you want to restrict strictly to the open window, adjust as needed.
TRADE_WINDOW_START = time(8, 5)
TRADE_WINDOW_END = time(11, 0)

# Execution Timeframe:
# As required: M15 for execution, M5 for 5-minute range calculation
# Set to 'M15' to check candle close on M15 bars, or 'M5' to check on M5 bars.
EXECUTION_TIMEFRAME_NAME = "M15"  # Options: "M15", "M5"

# ==============================================================================
# 4. STRATEGY PARAMETERS (MOMENTUM & BREAKOUT BOX)
# ==============================================================================
# Minimum 5-minute range in index points (skip low volatility days if < 30 points)
MIN_RANGE_POINTS = 30.0

# Stop Loss buffer in index points beyond the opposite side of the 5-min range
SL_BUFFER_POINTS = 10.0

# Trailing Stop Settings:
# Activates once trade reaches +50 points profit
TRAILING_TRIGGER_POINTS = 50.0

# Distance behind current market price
TRAILING_DISTANCE_POINTS = 30.0

# Step increment: only update MT5 Stop Loss when price advances by at least 5 points
TRAILING_STEP_POINTS = 5.0

# ==============================================================================
# 5. RISK MANAGEMENT & POSITION SIZING
# ==============================================================================
# Dynamic Lot Sizing Mode:
# If True: automatically calculates lot size based on account balance & stop loss distance
# If False: uses fixed LOT_SIZE below
USE_DYNAMIC_LOT = True

# Risk percentage per trade when USE_DYNAMIC_LOT is True (e.g. 1.0 = 1% of account balance)
RISK_PERCENT = 1.0

# Fixed position lot size (used if USE_DYNAMIC_LOT = False, or fallback)
LOT_SIZE = 0.1

# Minimum and Maximum lot limits (None to use broker limits automatically)
MIN_LOT_OVERRIDE = None
MAX_LOT_OVERRIDE = 10.0

# Maximum daily loss in index points. If cumulative loss reaches this, halt for day.
MAX_DAILY_LOSS_POINTS = 200.0

# Maximum allowed trades per calendar day
MAX_TRADES_PER_DAY = 1

# Magic Number unique to this bot instance to avoid interfering with other EAs
MAGIC_NUMBER = 930100

# Slippage tolerance in points
SLIPPAGE = 10

# Order comments
ORDER_COMMENT = "NY-Open Momentum v1.0"

# ==============================================================================
# 6. FILE PATHS & LOGGING
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, "ny_open_momentum.log")
CSV_HISTORY_PATH = os.path.join(BASE_DIR, "trades_history.csv")

# Polling interval in seconds during active hours
LOOP_SLEEP_SECONDS = 1.0

