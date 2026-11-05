"""
=============================================================================
NQ-Precision ORB Bot v1.0 - Configuration Module
=============================================================================
Institutional Opening Range Breakout (ORB) strategy with dual filters,
ATR-based risk modeling, dynamic lot sizing, and 8-minute time-stop.

Key Strategy Components:
1. Opening Range: 09:30 - 09:45 ET (1-minute candlestick high/low).
2. Snapshot Entry Trigger: At 09:59:55 ET:
   - Price > Range High -> BUY
   - Price < Range Low  -> SELL
   - Inside Range       -> No trade today
3. Dual Breakout Filters:
   - RVOL Filter: 14-period relative volume in [0.5, 1.5]
   - ATR Regime: Short ATR(14) / Long ATR(50) in [1.0, 2.5]
4. Risk Management:
   - Dynamic Lot sizing based on account equity and 2.2x ATR stop distance
   - Stop Loss: 2.2x ATR(14)
   - Take Profit: 0.3x ATR(14)
   - Time Stop: Automatic flat exit after 8 minutes if SL/TP not hit
5. State Recovery:
   - Adopts existing open positions upon bot restart and resumes tracking
=============================================================================
"""

from datetime import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "nq_precision_orb.log"
TRADES_CSV = BASE_DIR / "trades_history.csv"

# Timezone
TIMEZONE_NAME = "America/New_York"
TIMEFRAME = "M1"

# Trading Session & ORB Window (New York Wall Clock)
RANGE_START_TIME = time(9, 30)       # 09:30:00 ET (Cash Market Open)
RANGE_END_TIME = time(9, 45)         # 09:45:00 ET (ORB Lock Time)

# Entry Trigger Mode:
# True: Takes a single snapshot at 09:59:55 ET.
# False: Takes the first breakout between 09:45 and TRADE_UNTIL_TIME.
USE_TRIGGER_TIME = True
TRIGGER_HOUR = 9
TRIGGER_MINUTE = 59
TRIGGER_SECOND = 55
TRADE_UNTIL_TIME = time(11, 0)       # 11:00:00 ET cutoff if trigger mode is False

# Dual Breakout Filters
USE_FILTERS = True
RVOL_LEN = 14                        # Rolling bars for mean volume
RVOL_MIN = 0.5                       # Minimum relative volume
RVOL_MAX = 1.5                       # Maximum relative volume

ATR_PERIOD = 14                      # Short ATR period
ATR_REGIME_LEN = 50                  # Long ATR period for regime calculation
REGIME_MIN = 1.0                     # Min ratio: Short ATR / Long ATR
REGIME_MAX = 2.5                     # Max ratio: Short ATR / Long ATR

# Risk & Order Execution Multipliers
ATR_SL_MULT = 2.2                    # Stop Loss = 2.2 * ATR(14)
ATR_TP_MULT = 0.3                    # Take Profit = 0.3 * ATR(14)

# Time-Based Close
USE_TIME_CLOSE = True
CLOSE_AFTER_MIN = 8                  # Close position if open >= 8 minutes

# Money Management & Dynamic Lot Sizing
USE_DYNAMIC_LOT = True
RISK_PERCENT = 1.0                   # 1.0% of account equity per trade
MIN_BALANCE_THRESHOLD = 10.0
MAX_TRADES_PER_DAY = 1               # Max 1 trade per day per asset

# Target Profiles
TARGET_PROFILES = {
    "USTEC": {
        "broker_symbol_candidates": ["USTECm", "USTEC", "NAS100", "US100", "NAS100m"],
        "fallback_lot": 0.1,
        "magic_number": 980101,
        "description": "Nasdaq 100 Index - M1 ORB (09:30-09:45 ET)"
    },
    "XAUUSD": {
        "broker_symbol_candidates": ["XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.m"],
        "fallback_lot": 0.01,
        "magic_number": 980102,
        "description": "Gold (Spot Gold / USD) - M1 ORB (09:30-09:45 ET)"
    },
    "BTCUSD": {
        "broker_symbol_candidates": ["BTCUSDm", "BTCUSD", "BTCUSD.m", "Bitcoin"],
        "fallback_lot": 0.01,
        "magic_number": 980103,
        "description": "Bitcoin (BTC / USD) - M1 ORB (09:30-09:45 ET)"
    }
}
