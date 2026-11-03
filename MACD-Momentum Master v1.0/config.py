"""
=============================================================================
MACD-Momentum Master v1.0 - Configuration
=============================================================================
Replicates MQL5 built-in EA: ExpertMACD.mq5 (Magic 10981)
- Signal: MACD Fast=12, Slow=24, Signal=9 (Signal line & zero-line crossovers)
- Fixed or dynamic SL/TP + Reversal management
=============================================================================
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "macd.log"

# MACD Indicator Parameters
MACD_FAST = 12
MACD_SLOW = 24
MACD_SIGNAL = 9

# Fixed SL/TP points (matching ExpertMACD defaults: TP=50, SL=20, scaled by symbol)
TAKE_PROFIT_POINTS = 50
STOP_LOSS_POINTS = 20

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
        "magic_number": 980101,
        "sl_points": 30.0,
        "tp_points": 60.0,
        "description": "Gold (Spot Gold / USD) - M15 MACD Momentum"
    },
    "BTCUSD": {
        "broker_symbol_candidates": ["BTCUSDm", "BTCUSD", "BTCUSD.m", "Bitcoin"],
        "timeframe": "M15",
        "fallback_lot": 0.01,
        "magic_number": 980102,
        "sl_points": 300.0,
        "tp_points": 600.0,
        "description": "Bitcoin (BTC / USD) - M15 MACD Momentum"
    },
    "USTEC": {
        "broker_symbol_candidates": ["USTECm", "USTEC", "NAS100", "US100", "NAS100m"],
        "timeframe": "M15",
        "fallback_lot": 0.1,
        "magic_number": 980103,
        "sl_points": 40.0,
        "tp_points": 80.0,
        "description": "Nasdaq 100 Index - M15 MACD Momentum"
    }
}
