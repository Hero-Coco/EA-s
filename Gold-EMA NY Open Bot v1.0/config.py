"""
=============================================================================
Gold-EMA NY Open Bot v1.0 - Configuration
=============================================================================
Strategy: NY Open 5-Min Candle + 50 EMA Confluence for XAUUSD (M5)
=============================================================================
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
LOG_FILE = BASE_DIR / "gold_ema_ny_open.log"
TRADES_CSV = BASE_DIR / "trades_history.csv"

# Broker Symbol Settings
SYMBOL_CANDIDATES = ["XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.m"]
TIMEFRAME_STR = "M5"
MAGIC_NUMBER = 990101

# Timing Filter (New York Market Open)
NY_TIMEZONE = "US/Eastern"
NY_OPEN_HOUR = 9
NY_OPEN_MINUTE = 30
NY_ENTRY_MINUTE = 35          # 09:35 ET - when the first 5-min candle (09:30-09:35) closes
NY_WINDOW_END_MINUTE = 40     # Window closes at 09:40 ET

# EMA Indicator Settings
EMA_PERIOD = 50

# Price Unit Definition for XAUUSD (1 standard Gold point = $0.01 / 1 pip = $0.10)
POINT_USD_VALUE = 0.01

# Trade & Risk Management
LOT_SIZE = 0.05               # Configurable position size for XAUUSD
SL_BUFFER_POINTS = 200        # 20 pips ($2.00) buffer beyond candle high/low
TRAILING_TRIGGER_POINTS = 400 # 40 pips ($4.00) in profit to activate trailing stop
TRAILING_DISTANCE_POINTS = 300# 30 pips ($3.00) trail behind current price
TRAILING_STEP_POINTS = 50     # 5 pips ($0.50) minimum favorable move to update SL
MIN_CANDLE_RANGE_POINTS = 300 # Minimum 5-min candle range ($3.00 / 30 pips) to filter chop
MAX_SPREAD_POINTS = 250       # Max allowed spread: 250 points ($2.50 / 25 pips)
MAX_DAILY_LOSS = 500.0        # Max daily loss threshold (-$500). If hit, stop trading
MAX_TRADES_PER_DAY = 1        # Max 1 trade per day
