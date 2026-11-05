# Shifted-MA Trend Master v1.0 (MT5 Python Expert Advisor)

Pure Python 3.8 replication of the high-performing MQL5 built-in EA **`ExpertMAMA.mq5`** (CSignalMA Period=12, Shift=6 + CTrailingMA Period=12, Shift=0, SMA) with dynamic lot sizing, broker symbol auto-resolving, and multi-symbol concurrent execution.

---

## 🌟 Strategy Architecture (কৌশলের মূল ভিত্তি)

MT5 এর বিল্ট-ইন `ExpertMAMA.mq5` যেভাবে স্বয়ংক্রিয়ভাবে লাভজনক ট্রেড নেয়, এই পাইথন বটটিতে ঠিক সেই একই গাণিতিক অ্যালগরিদম কার্যকর করা হয়েছে:

### 1. Signal Moving Average (12 SMA, Shift=6)
- **Period**: 12
- **Shift**: 6
- **Method**: Simple Moving Average (SMA)
- **Applied Price**: Close
- **Entry Logic**:
  - **BUY**: যখন সমাপ্ত ক্যান্ডেলের ক্লোজ (Bar 1 Close) ৬-বার শিফট করা ১২ SMA এর উপরে ক্রস করে।
  - **SELL**: যখন সমাপ্ত ক্যান্ডেলের ক্লোজ (Bar 1 Close) ৬-বার শিফট করা ১২ SMA এর নিচে ক্রস করে।
  - শিফটেড মুভিং এভারেজ মার্কেট নয়েজ দূর করে আসল ট্রেন্ড ডিরেকশন নিখুঁতভাবে ফিল্টার করে।

### 2. Dynamic Trailing Stop (12 SMA, Shift=0)
- **Period**: 12
- **Shift**: 0 (Unshifted)
- **Method**: SMA
- **Trailing Stop Logic**:
  - **BUY Positions**: প্রতি ক্যান্ডেল ক্লোজে বার ১ এর আনশিফটেড ১২ SMA ভ্যালুতে স্টপ লস আপডেট করা হয় (`new_sl = 12 SMA`). মার্কেট যতক্ষণ উপরে যাবে, স্টপ লস স্বয়ংক্রিয়ভাবে প্রফিট লক করে পিছু পিছু উপরে উঠবে।
  - **SELL Positions**: প্রতি ক্যান্ডেল ক্লোজে বার ১ এর ১২ SMA + Spread ভ্যালুতে স্টপ লস নিচে নামানো হয়।
  - প্রাইস ১২ SMA ব্রেক করলেই সাথে সাথে লাভ সুরক্ষিত করে পজিশন ক্লোজ হয়ে যায়।

### 3. Reversal & False-Breakout Protection
- যদি কোনো পজিশন চালু থাকা অবস্থায় বিপরীত সিগন্যাল আসে (যেমন BUY থাকা অবস্থায় SELL ক্রস), বট সাথে সাথে আগের পজিশনটি মার্কেট প্রাইসে ক্লোজ করে নতুন দিকে পজিশন ওপেন করে।
- **Candle Close Discipline**: `Expert_EveryTick = false` নীতির কারণে বট প্রতি টিক-এ নয়েজ ট্রেড নেয় না; কেবল সম্পন্ন হওয়া (Completed Bar) ক্যান্ডেলের ওপর ভিত্তি করে সিদ্ধান্ত নেয়।

### 4. Dynamic Lot Sizing
- ব্যালেন্স বা ইকুইটির নির্দিষ্ট রিস্ক পার্সেন্টেজ (ডিফল্ট: ১.০%) এবং স্টপ লসের দূরত্বের ভিত্তিতে স্বয়ংক্রিয়ভাবে সঠিক লট সাইজ নির্ধারণ করে।

---

## 📂 Project Structure

```
Shifted-MA Trend Master v1.0/
├── config.py             # Strategy parameters, targets, timeframe, risk %
├── mt5_manager.py        # MT5 terminal IPC, symbol mapper, order & trailing stop engine
├── strategy.py           # Indicator calculations, crossover evaluation, bar-by-bar handler
├── backtest.py           # Historical bar-by-bar simulator with CSV reporting
├── bot.py                # Interactive CLI live trading engine
├── run_bot.bat           # One-click Windows runner
└── README.md             # Complete documentation
```

---

## 🚀 How to Run

### ১. লাইভ বট চালু করা (Interactive CLI)
ডাবল ক্লিক করুন `run_bot.bat` অথবা টার্মিনালে রান করুন:
```powershell
cd "E:\EA's\Shifted-MA Trend Master v1.0"
py -3.8 bot.py
```
মেনু থেকে পছন্দ করুন:
- `1` Gold (XAUUSD / XAUUSDm) - M15
- `2` Bitcoin (BTCUSD / BTCUSDm) - M15
- `3` Nasdaq 100 (USTEC / USTECm) - M15
- `4` Multi-Pair Portfolio (একসাথে ৩টি পেয়ার ট্রেড করার জন্য)
- `5` Historical Backtest

### ২. ঐতিহাসিক ব্যাকটেস্ট রান করা
```powershell
py -3.8 backtest.py --target XAUUSD --bars 3000 --balance 1000
```
স্বয়ংক্রিয়ভাবে `backtest_XAUUSD.csv` ফাইল তৈরি হবে যাতে প্রতিটি ট্রেডের এন্ট্রি, এক্সিট, PnL এবং রানিং ব্যালেন্স রেকর্ড থাকে।

---

## 🛡️ Target Magic Numbers
- **960101**: XAUUSD (Gold)
- **960102**: BTCUSD (Bitcoin)
- **960103**: USTEC / NAS100 (Nasdaq)

