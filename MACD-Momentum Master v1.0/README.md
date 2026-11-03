# MACD-Momentum Master v1.0 (MT5 Python Expert Advisor)

Pure Python 3.8 replication of MQL5 built-in EA **`ExpertMACD.mq5`** (Magic 10981) featuring:
- **Fast EMA**: 12
- **Slow EMA**: 24
- **Signal Line**: 9
- **Signal Logic**: Signal-line crossover and Zero-line crossover with reversal
- **Execution**: Completed candle close (`Expert_EveryTick = false`)
- **Risk Management**: Dynamic lot sizing with account risk % protection

## 🚀 How to Run
```powershell
cd "E:\EA's\MACD-Momentum Master v1.0"
py -3.8 bot.py
```
Or double-click `run_bot.bat`.
