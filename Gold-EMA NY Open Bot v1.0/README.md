# Gold-EMA NY Open Bot v1.0 (XAUUSD M5)

Expert Advisor designed for XAUUSD (Gold) on the M5 timeframe combining the **Forex/Gold New York Market Open (08:00 - 08:05 ET / 13:00 UTC / 19:00 BD Time)** with a **50-period Exponential Moving Average (EMA 50)** confluence.

---

## 🎯 Core Strategy Architecture

### 1. Timing Filter (Forex/Gold New York Open)
- **Active Window:** 08:00 - 08:05 ET (13:00 - 13:05 UTC / 19:00 - 19:05 BD Time).
- Uses `pytz.timezone('US/Eastern')` for exact New York market time synchronization.
- All outside signals are strictly ignored. Only 1 trade per day.

### 2. EMA 50 Calculation
- 50-period Exponential Moving Average calculated on completed M5 candle closes.
- Function: `calculate_ema(df, period=50)`.

### 3. 5-Minute Candle Analysis (at 08:05 ET Close)
- **Long Entry:** 5-min candle CLOSE > EMA 50
- **Short Entry:** 5-min candle CLOSE < EMA 50
- **Volatility Filter:** Skip trade if candle range < 300 points ($3.00 / 30 pips).
- Function: `detect_ny_open_setup(df, symbol, ny_now)`.

### 4. Trade & Trailing Stop Management
- **Initial Stop Loss:**
  - Long: 5-min candle Low - 200 points ($2.00 / 20 pips) buffer.
  - Short: 5-min candle High + 200 points ($2.00 / 20 pips) buffer.
- **Dynamic Trailing Stop:**
  - Activates when trade reaches **+400 points ($4.00 / 40 pips)** profit.
  - Trails by **300 points ($3.00 / 30 pips)** behind current price.
  - Steps SL by **50 points ($0.50 / 5 pips)** increments as price moves in favor.
- **Take Profit:** Open-ended (captured via trailing stop for full 6-hour trend run).
- Function: `place_trade_with_trailing(symbol, direction, entry_price, sl_price, lot)`.

### 5. Risk & Protection Rules
- **Lot Size:** 0.05 lots (configurable).
- **Max Daily Loss:** -$500.00 daily loss limit (trading stops if reached).
- **Spread Filter:** Skip trade if spread > 250 points ($2.50 / 25 pips).
- **Weekend / Holiday Protection:** Built-in.
- **Reporting:** Daily console summary and trade recording in `trades_history.csv`.

---

## 🚀 How to Run

### Live Trading
```powershell
cd "E:\EA's\Gold-EMA NY Open Bot v1.0"
py -3.8 bot.py
```
Or double-click `run_bot.bat`.

### Historical Backtest
```powershell
py -3.8 backtest.py
```
Outputs complete statistics and generates `backtest_results.csv`.

