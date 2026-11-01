"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - Configuration Module
=============================================================================
Smart Money Concepts (SMC) Architecture:
1. Liquidity Sweep Detection (20-candle swing high/low break & reject)
2. Market Structure Shift (MSS) confirmation
3. Fair Value Gap (FVG) 3-candle imbalance identification (>= min points)
4. FVG Mitigation + Engulfing Candlestick entry trigger
5. SL: Beyond FVG zone | TP: Opposite liquidity level (equal highs/lows)
=============================================================================
"""

from pathlib import Path
import MetaTrader5 as mt5

# Base project paths
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE_PATH = BASE_DIR / "smc_bot.log"
TRADES_CSV_PATH = BASE_DIR / "trades_history.csv"
CHARTS_DIR = BASE_DIR / "debug_charts"

# Timeframe for SMC analysis
TIMEFRAME = mt5.TIMEFRAME_M5
TIMEFRAME_NAME = "M5"

# Swing High / Swing Low Lookback Period
SWING_LOOKBACK = 20

# Risk Management
DEFAULT_LOT = 0.1              # Default position size (0.1 lots)
MAX_TRADES_PER_DAY = 2         # Strict risk rule: Max 2 trades per day per asset
MAX_ACTIVE_TRADES_PER_PAIR = 1 # Only 1 open position at a time per pair

# Magic Numbers per Asset
MAGIC_NUMBERS = {
    "NIFTY": 950101,
    "IN50m": 950101,
    "XAUUSD": 950102,
    "XAUUSDm": 950102,
    "BTCUSD": 950103,
    "BTCUSDm": 950103,
}

# Broker Symbol Aliases
CANDIDATE_SYMBOLS = {
    "NIFTY": [
        "IN50m", "IN50", "INDIA50", "INDIA50m", "NIFTY50", "NIFTY", "IND50"
    ],
    "XAUUSD": [
        "XAUUSDm", "XAUUSD", "GOLDm", "GOLD", "XAUUSD.pro"
    ],
    "BTCUSD": [
        "BTCUSDm", "BTCUSD", "BTCUSD.pro", "XBTUSD"
    ]
}

ACTIVE_TARGETS = ["NIFTY", "XAUUSD", "BTCUSD"]

# Per-pair asset specifications & SMC thresholds
PAIR_PROFILES = {
    "NIFTY": {
        "min_fvg_points": 10.0,       # Rule: No trade if FVG < 10 points
        "sl_buffer_points": 2.0,      # SL buffer beyond FVG boundary
        "min_rr_ratio": 1.5,          # Minimum risk:reward ratio to take trade
        "lot_size": 0.1,
    },
    "XAUUSD": {
        "min_fvg_points": 1.5,        # Minimum $1.50 FVG size on Gold
        "sl_buffer_points": 0.5,      # $0.50 SL buffer
        "min_rr_ratio": 1.5,
        "lot_size": 0.1,
    },
    "BTCUSD": {
        "min_fvg_points": 50.0,       # Minimum $50 FVG size on Bitcoin
        "sl_buffer_points": 15.0,     # $15 SL buffer
        "min_rr_ratio": 1.5,
        "lot_size": 0.1,
    }
}

