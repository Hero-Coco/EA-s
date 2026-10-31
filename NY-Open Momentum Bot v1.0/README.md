# NY-Open Momentum Bot v1.0 (NAS100 M15 Breakout)

A fully automated, institutional-grade Expert Advisor for **MetaTrader 5 (MT5)** developed in **Python 3.8+** using the official `MetaTrader5` API and `pytz`.

The bot specializes in high-velocity intraday momentum capturing on **NAS100 (Nasdaq 100)** during the official New York Cash Open (09:30 - 09:35 ET).

---

## 📈 Core Strategy Architecture

```
09:30 ET                     09:35 ET                                               11:00 ET
---|----------------------------|-------------------------------------------------------|--->
   │  09:30-09:35 M5 Candle     │                Breakout Execution Phase               │
   │  Forming "Breakout Box"   │  • Candle Close > Range High  --> BUY (SL: Low - 10)  │
   │                            │  • Candle Close < Range Low   --> SELL (SL: High + 10)│
   │                            │  • Active Trailing Stop (+50 pt trigger, 30 pt trail) │
   │                            │  • Max 1 Trade / Day, Max Daily Loss -200 pts         │
```

### 1. Timing Filter
- **New York Cash Open**: 09:30 - 09:35 ET (14:30 - 14:35 UTC).
- Uses `datetime.now(pytz.timezone('US/Eastern'))` to guarantee broker-independent time conversion.
- Built-in **Weekend & US Market Holiday Filter** prevents execution on Saturdays, Sundays, and major US exchange holidays (New Year's Day, MLK Day, Presidents' Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas).

### 2. 5-Minute Range Box Analysis
- At **09:35 ET**, the bot fetches the completed `09:30-09:35` M5 candle.
- Records `Range High` and `Range Low` establishing the **Breakout Box**.
- **Volatility Filter**: If `Range Size < 30.0 points`, the day is marked as low-volatility and trading is halted for the day.

### 3. Breakout Entry (Candle Close Only)
- **Long Entry**: Price breaks and **closes** strictly above the 5-min range high.
- **Short Entry**: Price breaks and **closes** strictly below the 5-min range low.
- **No Wick Breaks**: Execution occurs strictly on a confirmed candle close (default `M15`, configurable to `M5`).
- **Frequency Limit**: Strictly **1 trade per day**.

### 4. Trade Management
- **Initial Stop Loss**: Opposite boundary of the 5-min range box:
  - **Long**: `SL = 5-min Range Low - 10 points buffer`
  - **Short**: `SL = 5-min Range High + 10 points buffer`
- **Dynamic Trailing Stop**:
  - Activates when position is **+50 points** in profit.
  - Trails **30 points** behind current market price.
  - Updates MT5 Stop Loss in **5-point steps** as price moves in favor.
- **Take Profit**: No fixed TP. Let the trailing stop capture maximum trend extension.

### 5. Strict Risk Controls
- **Lot Size**: `0.1` lots (configurable in `config.py`).
- **Max Daily Loss**: `-200 points`. If cumulative loss reaches -200 points, all trading is stopped for the remainder of the day.

---

## 📁 Project Directory Structure

```
e:\EA's\NY-Open Momentum Bot v1.0\
│
├── config.py             # Global configuration, risk rules, symbol candidates & time parameters
├── main.py               # Main bot loop, heartbeat monitor, and signal handler
├── strategy.py           # Core ORB momentum logic, trailing stop engine, daily state manager
├── mt5_manager.py        # MetaTrader 5 API integration, auto-symbol detection, order handling
├── holidays_filter.py    # Weekend and NYSE/NASDAQ holiday calendar validation
├── trade_logger.py       # Multi-channel logger (console & file) and CSV trade recorder
├── test_strategy.py      # Standalone unit tests for math, timing, SL, and trailing logic
├── requirements.txt      # Python dependencies (MetaTrader5, pytz, pandas)
├── run_bot.bat           # One-click Windows launcher
└── README.md             # Complete documentation and strategy guide
```

---

## ⚙️ Installation & Requirements

### 1. Prerequisites
- **Operating System**: Windows 10 / 11 or Windows Server.
- **Python**: Python 3.8+ (64-bit).
- **MetaTrader 5 Terminal**: Installed with an active Demo or Live account.

### 2. Enable Algo Trading in MetaTrader 5
1. Open your **MetaTrader 5** terminal.
2. Navigate to **Tools** -> **Options** (or press `Ctrl+O`).
3. Click on the **Expert Advisors** tab.
4. Check **"Allow Algo Trading"**.
5. Ensure **NAS100** (or your broker's symbol variant) is visible in the **Market Watch** window (`Ctrl+M`).

### 3. Install Python Dependencies
Open PowerShell or Command Prompt in this folder and run:
```bash
py -3.8 -m pip install -r requirements.txt
```

---

## 🚀 Running the Bot (Single File Controller)

You can run everything via **`bot.py`**:

```bash
py -3.8 bot.py
```
This launches the **Interactive Control Panel**:

```text
======================================================================
           NY-OPEN MOMENTUM BOT v1.0 - CONTROL PANEL
======================================================================
 [1] Start Live Trading Bot  (Type 'stop' or 'q' to stop cleanly)
 [2] Run Historical Backtest (Analyzes past 3+ months of data)
 [3] Test MT5 Connection & Account Status
 [4] View Live Trade History & Results
 [5] Exit
======================================================================
```

### Direct CLI Commands
* **Start Live Bot directly**:
  ```bash
  py -3.8 bot.py --live
  ```
  *(To stop the bot at any time, simply type `stop` or `q` and press **Enter**, or press **Ctrl+C**)*.

* **Run Historical Backtest**:
  ```bash
  py -3.8 bot.py --backtest
  ```
  *(Or run `py -3.8 backtest.py`)*

* **Check MT5 Connection & Available Symbols**:
  ```bash
  py -3.8 bot.py --check
  ```

---

## 📊 Multi-Asset Portfolio Backtest Comparison

A comprehensive backtest was run across all 4 supported instruments on Exness historical M5 data ($1,000 Starting Deposit, 1.0% Dynamic Risk):

| Symbol | Asset Class | Trades | Win Rate % | Net P&L ($) | Return (ROI) | Profit Factor | Max Drawdown % |
|---|---|---|---|---|---|---|---|
| **`XAUUSDm`** | **Gold / USD** | **71** | **80.28%** 🏆 | **+$729.49** | **+72.95%** | **1.69** | **16.27%** |
| **`BTCUSDm`** | **Bitcoin / USD** | **49** | **61.22%** | **+$200.51** | **+20.05%** | **2.06** | **4.23%** 🛡️ |
| **`USTECm`** | **Nasdaq 100** | **69** | **68.12%** | **+$2.16** | **+0.22%** | **1.01** | **5.71%** |
| **`EURUSDm`** | **Euro / USD** | **8** | **0.00%** | **-$21.70** | **-2.17%** | **0.00** | **3.96%** |

> **Key Takeaway**: **Gold (`XAUUSDm`)** and **Bitcoin (`BTCUSDm`)** exhibit exceptional opening range momentum at the 09:30 ET New York open, delivering +72.95% and +20.05% net returns respectively with strong win rates!

---

## 🌐 Supported Asset Profiles & Volatility Settings

| Parameter | USTECm (Nasdaq) | XAUUSDm (Gold) | BTCUSDm (Bitcoin) | EURUSDm (Forex) |
|---|---|---|---|---|
| **Min Range Filter** | 30.0 pts | 3.0 pts ($3.00) | 150.0 pts ($150) | 0.0008 (8 pips) |
| **Stop Loss Buffer** | 10.0 pts | 1.0 pt ($1.00) | 50.0 pts ($50) | 0.0003 (3 pips) |
| **Trailing Trigger** | +50.0 pts | +5.0 pts ($5.00) | +250.0 pts ($250) | +0.0015 (15 pips) |
| **Trailing Distance**| 30.0 pts | 3.0 pts ($3.00) | 150.0 pts ($150) | 0.0010 (10 pips) |
| **Trailing Step** | 5.0 pts | 0.5 pt ($0.50) | 25.0 pts ($25) | 0.0002 (2 pips) |

---

## 🛠️ Configuration Options (`config.py`)

All key parameters can be customized directly in `config.py`:

| Parameter | Default | Description |
|---|---|---|
| `SYMBOL_CANDIDATES` | `["NAS100", "NAS100.m", ...]` | Auto-detected Nasdaq symbols |
| `FORCED_SYMBOL` | `None` | Set to `"NAS100"` to bypass auto-detection |
| `LOT_SIZE` | `0.1` | Fixed lot size per trade |
| `EXECUTION_TIMEFRAME_NAME` | `"M15"` | Candle close timeframe (`"M15"` or `"M5"`) |
| `MIN_RANGE_POINTS` | `30.0` | Minimum 5-min range to allow trading |
| `SL_BUFFER_POINTS` | `10.0` | Buffer beyond opposite side of breakout box |
| `TRAILING_TRIGGER_POINTS` | `50.0` | Profit threshold to turn on trailing stop |
| `TRAILING_DISTANCE_POINTS` | `30.0` | Trailing distance behind market price |
| `TRAILING_STEP_POINTS` | `5.0` | Minimum incremental advance to modify SL |
| `MAX_DAILY_LOSS_POINTS` | `200.0` | Maximum cumulative loss allowed per day |
| `MAX_TRADES_PER_DAY` | `1` | Daily trade execution cap |

---

## 📊 CSV Trade Logging Output

Closed trades are logged in real-time to `trades_history.csv` with the following columns:

```csv
TradeID,Timestamp,Symbol,Action,Lots,EntryPrice,InitialSL,ExitPrice,CloseTime,PnL_Points,PnL_Currency,ExitReason,MagicNumber
1098421,2026-11-02 09:45:00,NAS100,BUY,0.10,20520.50,20465.00,20595.00,2026-11-02 10:15:20 ET,+74.50,+$149.00,Trailing Stop,930100
```

---

## 🧪 Running Unit Tests

To run the offline test suite:
```cmd
py -3.8 test_strategy.py
```
Outputs validation for US holidays, weekend rules, SL buffer offsets, range filtering, and step-wise trailing stop calculations.

