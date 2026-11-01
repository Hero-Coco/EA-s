# NY-Open 12 EMA Trend Bot v1.0 📈

An institutional-grade, fully automated algorithmic Expert Advisor for **MetaTrader 5 (MT5)** developed in Python 3.8. 

The bot is designed to capture high-momentum directional moves on **NASDAQ 100 (NAS100 / USTEC)** and **Gold (XAUUSD)** right at the New York Cash Market Open (09:30 AM ET).

---

## 🎯 Strategy Rules & Execution Logic

### 1. Entry Logic
* **Time**: At the close of the **FIRST 5-minute candle** after the New York market open (**09:30 - 09:35 AM ET**).
* **Indicator**: 12-period Exponential Moving Average (**12 EMA**) calculated dynamically on the 5-minute timeframe.
* **Signals**:
  * If `Candle Close > 12 EMA` ➔ **Open BUY Position** (Market Order)
  * If `Candle Close < 12 EMA` ➔ **Open SELL Position** (Market Order)
  * If `Candle Close == 12 EMA` ➔ Neutral (No trade)

### 2. Position Management & Trailing Stop
* **Take Profit**: Strictly **None (0.0)**. The trade runs without arbitrary profit caps to capture large trending runners.
* **Stop Loss**: Automatic dynamic **Trailing Stop** based on ATR (Average True Range, 14-period) multiplier:
  * Initial Stop Loss = `Entry Price ± (1.5 × ATR)`
  * As price advances favorably, the Stop Loss trails behind at `1.5 × ATR`.
  * For BUY: SL only steps upward.
  * For SELL: SL only steps downward.
* Exit occurs when price retraces and hits the trailing stop.

### 3. Risk Management
* **Lot Size**: Configurable default of **0.1 lots** (supports fractional broker steps).
* **Trade Frequency**: Exactly **1 trade per day per asset** to prevent overtrading.

---

## 🕒 New York to Bangladesh Time (BST / UTC+6) Schedule

| Market Event | US Eastern Time (ET) | BD Time (Winter / Standard Time) | BD Time (Summer / Daylight Saving) |
| :--- | :--- | :--- | :--- |
| **New York Cash Open** | 09:30 AM ET | **08:30 PM BST** | 07:30 PM BST |
| **First 5-Min Candle Closes** | 09:35 AM ET | **08:35 PM BST** | 07:35 PM BST |
| **Entry Signal & Execution** | 09:35 AM ET | **08:35 PM BST** | 07:35 PM BST |
| **Trailing Stop Management** | 09:35 - 16:00 ET | **08:35 PM - 03:00 AM BST** | 07:35 PM - 02:00 AM BST |

---

## 📊 Historical Backtest Performance (3+ Months, 25,000 M5 Bars)

*Starting Balance: **$1,000.00** | Timeframe: **M5** | Lot Size: **0.1 Lots***

| Metric | Gold (`XAUUSDm`) | NASDAQ 100 (`USTECm`) |
| :--- | :--- | :--- |
| **Initial Balance** | $1,000.00 | $1,000.00 |
| **Final Balance** | **$1,822.65** | $950.20 |
| **Net Profit ($)** | **+$822.65** | -$49.80 |
| **Net ROI (%)** | **+82.26%** | -4.98% |
| **Total Trades** | 91 | 91 |
| **Winning Trades** | 36 | 33 |
| **Profit Factor** | **1.24** | 0.79 |
| **Max Drawdown ($)** | $909.06 | $58.43 |
| **Max Drawdown (%)** | 46.70% | 5.89% |
| **Detailed Log CSV** | [`backtest_XAUUSD.csv`](backtest_XAUUSD.csv) | [`backtest_NAS100.csv`](backtest_NAS100.csv) |

---

## 📂 Project Architecture

```
NY-Open 12 EMA Trend Bot v1.0/
├── bot.py                  # Master entrypoint with interactive menu & graceful keyboard shutdown
├── config.py               # Configurable strategy parameters (EMA, ATR mult, lot size, magic numbers)
├── strategy.py             # 12 EMA signal evaluation & dynamic ATR trailing stop logic
├── mt5_manager.py          # MT5 terminal connection, order placement, volume clamping & SL modification
├── backtest.py             # Historical backtesting engine over M5 MT5 rates
├── trade_logger.py         # Thread-safe console & file logger + CSV trade history export
├── run_bot.bat             # One-click Windows launcher detecting Python 3.8
├── backtest_XAUUSD.csv     # Verified historical backtest trade logs for Gold
├── backtest_NAS100.csv     # Verified historical backtest trade logs for Nasdaq
└── README.md               # Complete documentation & usage guide
```

---

## 🚀 How to Run

### Method 1: One-Click Windows Launcher
Double-click [`run_bot.bat`](run_bot.bat).

### Method 2: Command Line
```powershell
# Open terminal inside the bot directory
cd "E:\EA's\NY-Open 12 EMA Trend Bot v1.0"

# Launch interactive control panel
py -3.8 bot.py

# Or launch directly in live mode
py -3.8 bot.py --live

# Or run historical backtests
py -3.8 bot.py --backtest
```

### Clean Stop:
To safely shutdown the bot while running live, simply type `stop` or `q` and press **[Enter]**, or press **Ctrl+C**.

