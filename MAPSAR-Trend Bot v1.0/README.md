# MAPSAR-Trend Bot v1.0 (MT5 Python Expert Advisor)

Pure Python 3.8 replication of MQL5 built-in EA **`ExpertMAPSAR.mq5`** (Magic 14598) featuring:
- **Signal**: 12 SMA (Shift=6) applied to Close
- **Trailing Stop**: Parabolic SAR (`Step=0.02`, `Maximum=0.2`)
- **Execution**: Bar-by-bar candle close (`Expert_EveryTick = false`)
- **Risk Management**: Dynamic lot sizing based on account balance & Parabolic SAR distance

## 🚀 How to Run
```powershell
cd "E:\EA's\MAPSAR-Trend Bot v1.0"
py -3.8 bot.py
```
Or double-click `run_bot.bat`.
