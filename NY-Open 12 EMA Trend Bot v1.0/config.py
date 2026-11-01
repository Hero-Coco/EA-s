"""
=============================================================================
NY-Open 12 EMA Trend Bot v1.0 - Configuration Module
=============================================================================
Strategy Rules:
1. Entry on the close of the FIRST 5-minute candle after New York open (09:30 ET -> 09:35 ET close).
2. Indicator: 12-period Exponential Moving Average (12 EMA) on 5-Minute timeframe.
3. Signal:
   - Close > 12 EMA -> BUY
   - Close < 12 EMA -> SELL
4. Position & Exit:
   - Trailing Stop: Automatic trailing stop via ATR multiplier or fixed points.
   - Take Profit: None (0.0). Trailing stop manages and closes the trade.
5. Risk:
   - Default lot: 0.1 (configurable).
   - Max 1 trade at a time per pair.
=============================================================================
"""

from datetime import time
from pathlib import Path
import MetaTrader5 as mt5

# Base project paths
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE_PATH = BASE_DIR / "ny_open_12ema.log"
TRADES_CSV_PATH = BASE_DIR / "trades_history.csv"

# Timezone settings
TIMEZONE_NAME = "America/New_York"

# Timeframe for execution and indicators
TIMEFRAME = mt5.TIMEFRAME_M5
TIMEFRAME_NAME = "M5"

# Trading Session Windows (New York Eastern Time)
# NY Cash Open: 09:30 AM ET
# First 5-min candle covers 09:30:00 to 09:34:59 ET, closing at 09:35:00 ET
NY_OPEN_TIME = time(9, 30)
ENTRY_SIGNAL_TIME = time(9, 35)

# End of day trade session cut-off (if any position remains open until NY close)
SESSION_CLOSE_TIME = time(16, 0)

# Indicator Settings
EMA_PERIOD = 12

# Trailing Stop Configuration
# TRAIL_MODE: "ATR" or "POINTS"
TRAIL_MODE = "ATR"

# ATR Trailing Settings
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5           # Distance from Bid/Ask = 1.5 * ATR
INITIAL_SL_ATR_MULT = 1.5      # Initial Stop Loss = 1.5 * ATR from entry

# Fixed Points Trailing Settings (used if TRAIL_MODE == "POINTS")
TRAIL_POINTS_DEFAULT = 150.0   # Fixed points distance for trailing
INITIAL_SL_POINTS = 200.0      # Fixed points initial SL

# Trailing step threshold (minimum points price must advance before sending MT5 modify request)
MIN_TRAIL_STEP_POINTS = 10.0

# Take Profit: Strictly 0.0 (let trailing stop ride the momentum)
TAKE_PROFIT_POINTS = 0.0

# Risk Management
DEFAULT_LOT = 0.1              # Configurable default lot size (0.1 lots)
MAX_TRADES_PER_DAY = 1         # Max 1 trade per pair per day
MAX_ACTIVE_TRADES_PER_PAIR = 1 # Only 1 trade at a time per pair

# Magic Numbers (Distinguishes this bot's orders from other EAs)
MAGIC_NUMBERS = {
    "USTECm": 940101,
    "NAS100": 940101,
    "US100": 940101,
    "XAUUSDm": 940102,
    "XAUUSD": 940102,
}

# Broker Symbol Aliases (Auto-matched with Exness, FTMO, IC Markets, etc.)
CANDIDATE_SYMBOLS = {
    "NAS100": [
        "USTECm", "USTEC", "NAS100m", "NAS100", "US100m", "US100",
        "NDX100", "NQ", "USTEC.pro", "NAS100.cash"
    ],
    "XAUUSD": [
        "XAUUSDm", "XAUUSD", "GOLDm", "GOLD", "XAUUSD.pro", "XAUUSD.a"
    ]
}

# Active target pairs for live trading
ACTIVE_TARGETS = ["NAS100", "XAUUSD"]

# Per-pair custom overrides for optimal performance
PAIR_PROFILES = {
    "NAS100": {
        "trail_mode": "ATR",
        "atr_multiplier": 1.5,
        "initial_sl_atr_mult": 1.5,
        "fixed_trail_points": 150.0,
        "min_trail_step": 15.0,
        "lot_size": 0.1,
    },
    "XAUUSD": {
        "trail_mode": "ATR",
        "atr_multiplier": 1.5,
        "initial_sl_atr_mult": 1.5,
        "fixed_trail_points": 120.0,
        "min_trail_step": 10.0,
        "lot_size": 0.1,
    }
}
