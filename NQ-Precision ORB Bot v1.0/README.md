# NQ-Precision ORB Bot v1.0

Institutional Opening Range Breakout (ORB) strategy with dual volatility & volume filters, 09:59:55 ET snapshot entry, dynamic lot sizing, 8-minute time-stop, and automatic cross-crash state recovery for MetaTrader 5 (MT5).

---

## 🎯 সমর্থিত ইন্সট্রুমেন্ট (Supported Assets)

| টার্গেট অ্যাসেট | ব্রোকার সিম্বল ক্যান্ডিডেট | ডিফল্ট ম্যাজিক নাম্বার | টাইমফ্রেম |
| :--- | :--- | :--- | :--- |
| **USTEC** (Nasdaq 100) | `USTECm`, `USTEC`, `NAS100`, `US100` | `980101` | M1 (1-Minute) |
| **XAUUSD** (Gold) | `XAUUSDm`, `XAUUSD`, `GOLD`, `XAUUSD.m` | `980102` | M1 (1-Minute) |
| **BTCUSD** (Bitcoin) | `BTCUSDm`, `BTCUSD`, `Bitcoin` | `980103` | M1 (1-Minute) |

---

## 🧠 স্ট্র্যাটেজি ও কাজের লজিক (How the Strategy Works)

1. **Opening Range তৈরি (09:30 - 09:45 ET):**
   - নিউ ইয়র্ক ক্যাশ মার্কেট ওপেনিংয়ের প্রথম ১৫ মিনিটের (M1 ক্যান্ডেলস্টিক ধরে) সর্বোচ্চ প্রাইস (High) এবং সর্বনিম্ন প্রাইস (Low) ট্র্যাক করে একটি রেঞ্জ তৈরি করে।
   - ০৯:৪৫ ET-তে রেঞ্জটি লক (স্থির) হয়ে যায়।

2. **Snapshot Breakout Trigger (09:59:55 ET):**
   - ঠিক ০৯:৫৯:৫৫ ET-তে বট বর্তমান প্রাইসের একটি সিঙ্গেল স্ন্যাপশট নেয়:
     - প্রাইস যদি রেঞ্জ High-এর উপরে থাকে $\rightarrow$ **BUY**
     - প্রাইস যদি রেঞ্জ Low-এর নিচে থাকে $\rightarrow$ **SELL**
     - প্রাইস যদি রেঞ্জের ভেতরে থাকে $\rightarrow$ **No Trade** (ঐদিনের মতো কোনো ট্রেড নেওয়া হবে না)।

3. **ডুয়াল ফিল্টার (Dual Institutional Filters):**
   - **RVOL (Relative Volume):** ১৪-বারের গড় ভলিউমের সাথে বর্তমান ভলিউমের অনুপাত অবশ্যই `0.5` থেকে `1.5` এর মধ্যে থাকতে হবে।
   - **ATR Regime:** শর্ট ATR(14) ভাগ লং ATR(50) এর মান অবশ্যই `1.0` থেকে `2.5` এর মধ্যে থাকতে হবে (অতিরিক্ত ডেড বা অতিমাত্রায় বিশৃঙ্খল চপি মার্কেট ফিল্টার করে)।

4. **রিস্ক ম্যানেজমেন্ট ও এক্সিট (Risk & Exits):**
   - **Stop Loss (SL):** $2.2 \times \text{ATR}(14)$
   - **Take Profit (TP):** $0.3 \times \text{ATR}(14)$
   - **Time-Stop (8 মিনিট):** ট্রেড নেওয়ার পর ৮ মিনিট পার হয়ে গেলে এবং SL/TP হিট না করলে বট স্বয়ংক্রিয়ভাবে মার্কেট প্রাইসে পজিশন ক্লোজ করে ফ্ল্যাট হয়ে যায়।
   - **Dynamic Lot Sizing:** অ্যাকাউন্টের ব্যালেন্স/ইকুইটির ১.০% রিস্ক এবং স্টপ লস দূরত্বের ওপর ভিত্তি করে ব্রোকার-অ্যাকুরেট লট সাইজ স্বয়ংক্রিয়ভাবে হিসাব করে।

5. **স্টেট রিকভারি (State Recovery on Restart):**
   - বট কোনো কারণে বন্ধ হয়ে গেলে বা রিস্টার্ট দিলে এটি সাথে সাথে MT5 টার্মিনাল স্ক্যান করে নিজের `magic_number`-এর রানিং পজিশন খুঁজে নেয়।
   - পজিশনটিকে এডপ্ট (Adopt) করে তার অরিজিনাল ওপেন টাইম অনুযায়ী বাকি সময় মনিটর করে এবং ৮ মিনিট পার হলে স্বয়ংক্রিয়ভাবে ক্লোজ করে দেয়।
   - একই দিনে দ্বিতীয়বার ভুলবশত ডুপ্লিকেট ট্রেড নেওয়া পুরোপুরি বন্ধ রাখে।

---

## 🚀 রান করার নিয়ম (How to Run)

### লাইভ বট চালু করতে:
```bash
python bot.py
```
অথবা সরাসরি **`run_bot.bat`** ডাবল ক্লিক করে চালু করুন।

### হিস্টোরিক্যাল ব্যাকটেস্ট করতে:
```bash
# Nasdaq 100 ব্যাকটেস্ট
python backtest.py --target USTEC --bars 20000

# গোল্ড ব্যাকটেস্ট
python backtest.py --target XAUUSD --bars 20000

# বিটকয়েন ব্যাকটেস্ট
python backtest.py --target BTCUSD --bars 20000
```
