# NQ-Precision ORB Bot v1.0

Institutional Opening Range Breakout (ORB) strategy with dual volatility & volume filters, 09:59:55 ET snapshot entry trigger, dynamic lot sizing, 8-minute time-stop, and automatic cross-crash state recovery for MetaTrader 5 (MT5).

---

## 🎯 Supported Instruments

| Target Asset | Broker Symbol Candidates | Default Magic Number | Timeframe |
| :--- | :--- | :--- | :--- |
| **USTEC** (Nasdaq 100) | `USTECm`, `USTEC`, `NAS100`, `US100`, `NAS100m` | `980101` | M1 (1-Minute) |
| **XAUUSD** (Spot Gold) | `XAUUSDm`, `XAUUSD`, `GOLD`, `XAUUSD.m` | `980102` | M1 (1-Minute) |
| **BTCUSD** (Bitcoin) | `BTCUSDm`, `BTCUSD`, `BTCUSD.m`, `Bitcoin` | `980103` | M1 (1-Minute) |

---

## 🧠 Core Strategy & Mechanics

### 1. Opening Range Construction (09:30 - 09:45 ET)
- Captures the 1-minute candlestick data during the first 15 minutes of the New York cash session (09:30:00 to 09:44:59 ET).
- Calculates the highest high (`range_high`) and lowest low (`range_low`).
- Exactly at 09:45:00 ET, the Opening Range is locked and frozen for the remainder of the session.

### 2. Snapshot Entry Trigger (09:59:55 ET)
- At exactly 09:59:55 ET (30 minutes after US cash open), the bot evaluates a single snapshot of the current price:
  - **Price > `range_high`** $\rightarrow$ **BUY (Long)**
  - **Price < `range_low`** $\rightarrow$ **SELL (Short)**
  - **Price inside range** $\rightarrow$ **No Trade** (No trade executed for the day).

### 3. Dual Institutional Filters
Before placing any market order, both filters must pass:
1. **RVOL Filter (Relative Volume):**
   - Compares current 1-minute volume against its 14-period rolling mean:
     $$\text{RVOL} = \frac{\text{Volume}}{\text{SMA}(\text{Volume}, 14)}$$
   - Requirement: $0.5 \le \text{RVOL} \le 1.5$ (skips low liquidity and extreme news anomalies).
2. **ATR Regime Filter:**
   - Evaluates short-term volatility relative to medium-term volatility:
     $$\text{ATR Regime} = \frac{\text{ATR}(14)}{\text{ATR}(50)}$$
   - Requirement: $1.0 \le \text{ATR Regime} \le 2.5$ (prevents entries during flat/dead markets or erratic chop).

### 4. Risk Management & Position Sizing
- **Take Profit (TP):** $0.3 \times \text{ATR}(14)$ (rapid high-probability scalping target).
- **Stop Loss (SL):** $2.2 \times \text{ATR}(14)$ (generous buffer to prevent premature shakeouts).
- **Time-Based Close (8 Minutes):**
  - If a position remains open for 8 minutes and neither SL nor TP has filled, the bot immediately closes the trade at the current market price.
- **Dynamic Lot Sizing:**
  - Sized automatically off account equity:
    $$\text{Risk Amount} = \text{Equity} \times 1.0\%$$
    $$\text{Lot Size} = \frac{\text{Risk Amount}}{\text{SL Distance} \times \text{Contract Multiplier}}$$
  - Clamped between broker minimum/maximum volume steps.

### 5. State Recovery & Crash Resilience
- If the bot process is stopped, interrupted, or restarted while a position is open:
  - Scans MT5 for open positions matching the asset and `magic_number`.
  - Adopts the running trade into active management, preserving original entry timestamp.
  - Continues the 8-minute time-stop countdown and SL/TP monitoring.
  - Sets `traded_today = True` to prevent duplicate trade executions.

---

## 📊 Historical Backtest Performance (M1 Data)

| Asset Pair | Total Trades | Win Rate | Profit Factor | Net P&L | Max Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **USTEC (Nasdaq 100)** | 9 | **88.89%** (8W / 1L) | **8.39** | **+0.98%** | $1.32 (0.13%) |
| **BTCUSD (Bitcoin)** | 4 | **100.00%** (4W / 0L) | **999.00** | **+0.56%** | $0.00 (0.00%) |
| **XAUUSD (Spot Gold)** | 5 | **80.00%** (4W / 1L) | 0.45 | -0.61% | $10.97 (1.09%) |

---

## 🚀 Execution & Usage

### 1. Run Live Bot
Run via command line:
```bash
python bot.py
```
Or double-click the Windows batch launcher:
```text
run_bot.bat
```

### 2. Run Historical Backtester
```bash
# Backtest Nasdaq 100 (USTEC)
python backtest.py --target USTEC --bars 25000

# Backtest Spot Gold (XAUUSD)
python backtest.py --target XAUUSD --bars 25000

# Backtest Bitcoin (BTCUSD)
python backtest.py --target BTCUSD --bars 25000
```

---

## ⚙️ Configuration Reference (`config.py`)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `RANGE_START_TIME` | `09:30:00 ET` | Opening range start time (US cash open) |
| `RANGE_END_TIME` | `09:45:00 ET` | Opening range lock time |
| `USE_TRIGGER_TIME` | `True` | Enables 09:59:55 ET snapshot trigger mode |
| `TRIGGER_HOUR/MIN/SEC`| `09:59:55 ET` | Exact snapshot trigger time |
| `RVOL_LEN` | `14` | Rolling bar length for mean volume |
| `RVOL_MIN` / `MAX` | `0.5` / `1.5` | Allowed relative volume bounds |
| `ATR_PERIOD` | `14` | Fast ATR period |
| `ATR_REGIME_LEN` | `50` | Slow ATR period for regime baseline |
| `REGIME_MIN` / `MAX` | `1.0` / `2.5` | Allowed ATR regime ratio bounds |
| `ATR_SL_MULT` | `2.2` | Stop Loss distance multiplier ($2.2 \times \text{ATR}$) |
| `ATR_TP_MULT` | `0.3` | Take Profit distance multiplier ($0.3 \times \text{ATR}$) |
| `USE_TIME_CLOSE` | `True` | Enables 8-minute flat close |
| `CLOSE_AFTER_MIN` | `8` | Maximum position holding time in minutes |
| `USE_DYNAMIC_LOT` | `True` | Enables equity-based 1% risk position sizing |
| `RISK_PERCENT` | `1.0` | Risk percentage of account equity |
