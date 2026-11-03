"""
=============================================================================
MAPSAR-Trend Bot v1.0 - Configuration
=============================================================================
Replicates MQL5 built-in EA: ExpertMAPSAR.mq5 (Magic 14598)
- Signal: 12 SMA (Shift=6) Trend Breakout
- Trailing Stop: Parabolic SAR (Step=0.02, Maximum=0.2)
=============================================================================
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "mapsar.log"

# Signal MA Parameters
SIGNAL_MA_PERIOD = 12
SIGNAL_MA_SHIFT = 6
SIGNAL_MA_METHOD = "SMA"

# Trailing Parabolic SAR Parameters
SAR_STEP = 0.02
SAR_MAXIMUM = 0.2

# Bar Evaluation (Candle Close Discipline)
EVERY_TICK = False
CHECK_INTERVAL_SECONDS = 2.0

# Risk & Money Management
USE_DYNAMIC_LOT = True
RISK_PERCENT = 1.0
MIN_BALANCE_THRESHOLD = 10.0

TARGET_PROFILES = {
    "XAUUSD": {
        "broker_symbol_candidates": ["XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.m"],
        "timeframe": "M15",
        "fallback_lot": 0.01,
        "magic_number": 970101,
        "description": "Gold (Spot Gold / USD) - M15 12 SMA + Parabolic SAR"
    },
    "BTCUSD": {
        "broker_symbol_candidates": ["BTCUSDm", "BTCUSD", "BTCUSD.m", "Bitcoin"],
        "timeframe": "M15",
        "fallback_lot": 0.01,
        "magic_number": 970102,
        "description": "Bitcoin (BTC / USD) - M15 12 SMA + Parabolic SAR"
    },
    "USTEC": {
        "broker_symbol_candidates": ["USTECm", "USTEC", "NAS100", "US100", "NAS100m"],
        "timeframe": "M15",
        "fallback_lot": 0.1,
        "magic_number": 970103,
        "description": "Nasdaq 100 Index - M15 12 SMA + Parabolic SAR"
    }
}
