# NY-Open Momentum Bot v1.0 (Multi-Asset Portfolio EA)

A fully automated, institutional-grade Expert Advisor for **MetaTrader 5 (MT5)** developed in **Python 3.8+** using the official `MetaTrader5` API and `pytz`.

The bot specializes in high-velocity intraday momentum capturing at the **New York Cash Open (09:30 - 09:35 ET)** across major liquid instruments:
- 📈 **Nasdaq 100 Index (`USTECm` / `NAS100`)**
- 🥇 **Gold (`XAUUSDm` / `GOLD`)**
- ₿ **Bitcoin (`BTCUSDm` / `BTCUSD`)**
- 💶 **Euro / US Dollar (`EURUSDm`)**

---

## ⏰ Market Timing & Bangladesh Time (BST) Conversion

The strategy is strictly bound to the New York Cash Open. The bot uses `datetime.now(pytz.timezone('US/Eastern'))` to auto-adjust for US Daylight Saving Time (DST) changes.

| Event | US / Eastern Time (ET) | BD Time (Winter / Current) | BD Time (Summer / DST) |
|---|---|---|---|
| **Pre-Market Standby** | Before 09:30 AM | Before 08:30 PM | Before 07:30 PM |
| **5-Min Range Formation** | **09:30 AM – 09:35 AM** | **08:30 PM – 08:35 PM** | **07:30 PM – 07:35 PM** |
| **Breakout Box Finalized** | **09:35 AM** | **08:35 PM** | **07:35 PM** |
| **Trade Execution Window** | **09:35 AM – 11:00 AM** | **08:35 PM – 10:00 PM** | **07:35 PM – 09:00 PM** |
| **Session End / EOD Exit** | 04:00 PM | 03:00 AM (Next Day) | 02:00 AM (Next Day) |

> [!NOTE]
> **No manual clock adjustment is required.** The internal `pytz` engine automatically syncs with US Eastern Time regardless of where the bot is hosted.

---

## 📈 Core Strategy Architecture

```
09:30 ET (8:30 PM BD)        09:35 ET (8:35 PM BD)                                 11:00 ET (10:00 PM BD)
---|----------------------------|-------------------------------------------------------|--->
   │  09:30-09:35 M5 Candle     │                Breakout Execution Phase               │
   │  Forming "Breakout Box"   │  • Candle Close > Range High  --> BUY (SL: Low - Buffer)│
   │                            │  • Candle Close < Range Low   --> SELL (SL: High + Buffer)│
   │                            │  • Dynamic Trailing Stop (+Trigger, Trail Distance)   │
   │                            │  • Max 1 Trade / Day per Pair, Max Daily Loss Cap     │
```

### 1. Timing Filter & Calendar Shield
- Evaluates the opening 5-minute candle at **09:30 – 09:35 ET**.
- **Weekend & Holiday Filter**: Automatically suppresses trading on Saturdays, Sundays, and official US Market Holidays (NYSE / NASDAQ calendar).

### 2. 5-Minute Range Box Analysis
- At **09:35 ET (08:35 PM BD)**, the bot records the `Range High` and `Range Low` of the completed M5 candle.
- **Volatility Threshold**: If the range is smaller than the asset's minimum requirement, the day is classified as low-volatility and no trades are taken.

### 3. Breakout Entry (Candle Close Only)
- **Long Entry**: Price breaks and **closes** strictly above the 5-min Range High.
- **Short Entry**: Price breaks and **closes** strictly below the 5-min Range Low.
- **No Wick Whipsaws**: Execution requires a confirmed candle close (default `M15`, configurable to `M5`).
- **Cap**: Strictly **1 trade per day per asset**.

### 4. Trade Management & Trailing Stop
- **Initial Stop Loss**: Placed at the opposite boundary of the 5-minute box (+/- buffer).
- **Dynamic Trailing Stop**:
  - Activates when unrealized profit reaches the threshold.
  - Trails behind current market price.
  - Updates MT5 Stop Loss in defined step increments.
- **Take Profit**: No fixed TP. The trailing stop captures maximum trend expansion.

### 5. Dynamic Position Sizing (Risk Management)
- **Dynamic Lot Sizing** (`USE_DYNAMIC_LOT = True`): Automatically sizes every position to risk a fixed percentage (default `1.0%`) of account equity based on Stop Loss distance:
  $$\text{Lots} = \frac{\text{Account Balance} \times \text{Risk \%}}{\text{Stop Loss Distance (pts)} \times \text{Point Value}}$$
- Clamps and snaps to broker constraints (`volume_min`, `volume_step`, `volume_max`).
- **Fixed Lot Sizing** fallback supported (`USE_DYNAMIC_LOT = False`, `LOT_SIZE = 0.1`).

---

## 📊 Multi-Asset Portfolio Backtest Comparison

Backtested directly on broker historical tick and M5 data (**20,000 bars, ~3 Months: July 22 – Oct 30, 2026**) on an active Exness account with **$1,000 Starting Capital (1.0% Risk / Trade)**:

| Symbol | Asset Class | Trades | Win Rate % | Net P&L ($) | Return (ROI) | Profit Factor | Max Drawdown % |
|---|---|---|---|---|---|---|---|
| **`XAUUSDm`** | **Gold vs US Dollar** | **71** | **80.28%** 🏆 | **+$729.49** | **+72.95%** | **1.69** | **16.27%** |
| **`BTCUSDm`** | **Bitcoin vs USD** | **49** | **61.22%** | **+$200.51** | **+20.05%** | **2.06** | **4.23%** 🛡️ |
| **`USTECm`** | **Nasdaq 100 Index** | **69** | **68.12%** | **+$2.16** | **+0.22%** | **1.01** | **5.71%** |
| **`EURUSDm`** | **Euro vs US Dollar** | **8** | **0.00%** | **-$21.70** | **-2.17%** | **0.00** | **3.96%** |

> [!TIP]
> **Key Finding**: **Gold (`XAUUSDm`)** and **Bitcoin (`BTCUSDm`)** show extraordinary opening range momentum during New York Open, generating **+72.95%** and **+20.05%** returns with strong win rates!

---

## 🌐 Asset Class Profiles ([`config.py`](file:///e:/EA's/NY-Open%20Momentum%20Bot%20v1.0/config.py))

| Parameter | USTECm (Nasdaq) | XAUUSDm (Gold) | BTCUSDm (Bitcoin) | EURUSDm (Forex) |
|---|---|---|---|---|
| **Magic Number** | `930101` | `930102` | `930103` | `930104` |
| **Min Range Filter** | 30.0 pts | 3.0 pts ($3.00) | 150.0 pts ($150) | 0.0008 (8 pips) |
| **Stop Loss Buffer** | 10.0 pts | 1.0 pt ($1.00) | 50.0 pts ($50) | 0.0003 (3 pips) |
| **Trailing Trigger** | +50.0 pts | +5.0 pts ($5.00) | +250.0 pts ($250) | +0.0015 (15 pips) |
| **Trailing Distance**| 30.0 pts | 3.0 pts ($3.00) | 150.0 pts ($150) | 0.0010 (10 pips) |
| **Trailing Step** | 5.0 pts | 0.5 pt ($0.50) | 25.0 pts ($25) | 0.0002 (2 pips) |

---

## 🚀 How to Run the Bot

Navigate to the bot folder in your terminal:
```cmd
cd /d "E:\EA's\NY-Open Momentum Bot v1.0"
```

### 1. Interactive Control Panel (Recommended)
```cmd
python bot.py
```
This presents the master terminal menu:
```text
===========================================================================
           NY-OPEN MOMENTUM BOT v1.0 - PORTFOLIO CONTROL PANEL
===========================================================================
 [1] Start Live Trading on ALL 4 Pairs (USTEC, Gold, BTC, EURUSD)
 [2] Start Live Trading on a SINGLE Pair (Select one)
 [3] Run Historical Backtest (Single Pair or All 4 Pairs Comparison)
 [4] Test MT5 Connection & Account Status
 [5] View Live Trade History & Results
 [6] Exit
===========================================================================
```

### 2. Direct Live Bot Execution
```cmd
python bot.py --live
```
*(To stop the bot safely anytime, simply type **`stop`** or **`q`** and press **Enter**, or press **Ctrl+C**)*.

### 3. Run Backtests Anytime
- **Backtest All 4 Pairs together**:
  ```cmd
  python backtest.py --all --deposit 1000 --risk 1.0
  ```
- **Backtest Gold only**:
  ```cmd
  python backtest.py --pair XAUUSDm --deposit 1000 --risk 1.0
  ```
- **Backtest Bitcoin only**:
  ```cmd
  python backtest.py --pair BTCUSDm --deposit 1000 --risk 1.0
  ```

---

## 📁 Project File Layout

```
e:\EA's\NY-Open Momentum Bot v1.0\
│
├── config.py             # Portfolio pairs, risk scaling, asset profiles & broker settings
├── bot.py                # Unified Interactive Controller & single-file launcher
├── strategy.py           # Core ORB momentum logic, trailing stops & PortfolioStrategyManager
├── backtest.py           # Multi-asset backtest engine with drawdown and compounding stats
├── mt5_manager.py        # MetaTrader 5 API integration, order execution & dynamic lot calculation
├── holidays_filter.py    # Weekend and NYSE/NASDAQ holiday calendar validation
├── trade_logger.py       # Multi-channel logger (console & file) and CSV trade recorder
├── check_mt5_connection.py # Standalone MT5 connection & broker symbol diagnostics
├── test_strategy.py      # Unit test suite for offline math & holiday validations
├── requirements.txt      # Python dependencies (MetaTrader5, pytz, pandas)
├── run_bot.bat           # Windows one-click launcher
└── README.md             # Complete documentation
```
