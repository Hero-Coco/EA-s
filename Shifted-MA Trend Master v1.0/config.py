"""
=============================================================================
Shifted-MA Trend Master v1.0 - Central Configuration
=============================================================================
Pure Python replication of the highly profitable MQL5 ExpertMAMA EA
(CSignalMA Period=12, Shift=6 + CTrailingMA Period=12, Shift=0, SMA)
=============================================================================
"""

from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.resolve()
CHARTS_DIR = BASE_DIR / "trade_charts"
LOG_FILE = BASE_DIR / "shifted_ma.log"

# Signal MA Parameters (Trend Filter & Entry Trigger)
# Exact match to MQL5 CSignalMA(Period=12, Shift=6, Method=MODE_SMA, Applied=PRICE_CLOSE)
SIGNAL_MA_PERIOD = 12
SIGNAL_MA_SHIFT = 6
SIGNAL_MA_METHOD = "SMA"       # Simple Moving Average

# Trailing MA Parameters (Dynamic Trailing Stop)
# Exact match to MQL5 CTrailingMA(Period=12, Shift=0, Method=MODE_SMA, Applied=PRICE_CLOSE)
TRAILING_MA_PERIOD = 12
TRAILING_MA_SHIFT = 0
TRAILING_MA_METHOD = "SMA"

# Bar Evaluation (Candle-Close Discipline)
# Exact match to Expert_EveryTick = false: Only evaluates signals on completed bars
EVERY_TICK = False
CHECK_INTERVAL_SECONDS = 2.0   # Polling interval in live bot loop

# Dynamic Lot Sizing & Risk Management
USE_DYNAMIC_LOT = True         # True: Calculate lot based on risk % and SL distance
RISK_PERCENT = 1.0             # Risk 1.0% of account equity per trade
MIN_BALANCE_THRESHOLD = 10.0   # Minimum balance required to take a trade

# Supported Instrument Profiles
TARGET_PROFILES = {
    "XAUUSD": {
        "broker_symbol_candidates": ["XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.m"],
        "timeframe": "M15",
        "fallback_lot": 0.01,
        "magic_number": 960101,
        "description": "Gold (Spot Gold / USD) - M15 Trend Following"
    },
    "BTCUSD": {
        "broker_symbol_candidates": ["BTCUSDm", "BTCUSD", "BTCUSD.m", "Bitcoin"],
        "timeframe": "M15",
        "fallback_lot": 0.01,
        "magic_number": 960102,
        "description": "Bitcoin (BTC / USD) - M15 Momentum Swing"
    },
    "USTEC": {
        "broker_symbol_candidates": ["USTECm", "USTEC", "NAS100", "US100", "NAS100m"],
        "timeframe": "M15",
        "fallback_lot": 0.1,
        "magic_number": 960103,
        "description": "Nasdaq 100 Index - M15 Tech Momentum"
    }
}

