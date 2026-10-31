"""
MT5 Connection & Symbol Diagnostics Script
===========================================
Tests live connection to MetaTrader 5 terminal, extracts account status,
scans all broker symbols for Nasdaq 100 variants, and reports live quotes.
"""

import sys
import json
import MetaTrader5 as mt5

def main():
    print("=" * 70)
    print("         METATRADER 5 CONNECTION & SYMBOL DIAGNOSTICS")
    print("=" * 70)

    # 1. Initialize MT5
    terminal_path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    print(f"\n[1] Attempting MT5 initialization (terminal: {terminal_path})...", flush=True)
    
    # Try attaching to running terminal first with 10s timeout
    initialized = mt5.initialize(timeout=10000)
    if not initialized:
        print("    -> Default attach failed, trying with explicit terminal path...", flush=True)
        initialized = mt5.initialize(path=terminal_path, timeout=20000)

    if not initialized:
        err_code, err_desc = mt5.last_error()
        print(f"\n[FAILED] mt5.initialize() failed! Error code: {err_code}, Description: {err_desc}")
        print("Please ensure MetaTrader 5 is running or installed properly.")
        return 1

    print("[SUCCESS] MT5 initialized successfully!")
    version = mt5.version()
    print(f"    Terminal Version: {version}")

    # 2. Check Terminal & Account Info
    terminal_info = mt5.terminal_info()
    if terminal_info:
        print(f"    Terminal Connected: {terminal_info.connected}")
        print(f"    Trade Allowed in Terminal: {terminal_info.trade_allowed}")
        print(f"    Community Account: {terminal_info.community_account}")
    
    account_info = mt5.account_info()
    if account_info:
        print(f"\n[2] Account Information:")
        print(f"    Account Login   : #{account_info.login}")
        print(f"    Account Name    : {account_info.name}")
        print(f"    Broker / Server : {account_info.server} ({account_info.company})")
        print(f"    Balance         : {account_info.balance:.2f} {account_info.currency}")
        print(f"    Equity          : {account_info.equity:.2f} {account_info.currency}")
        print(f"    Leverage        : 1:{account_info.leverage}")
        print(f"    Trade Allowed   : {account_info.trade_allowed}")
        print(f"    Trade Expert    : {account_info.trade_expert} (Automated trading permission)")
    else:
        print("\n[WARNING] Could not retrieve account_info(). Please log in to your trading account in MT5.")

    # 3. Retrieve and filter all symbols for Nasdaq / US Tech
    print("\n[3] Scanning all broker symbols for Nasdaq 100 / US Tech index variants...")
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        print("[ERROR] No symbols returned from broker terminal.")
        mt5.shutdown()
        return 1

    print(f"    Total symbols available in broker catalog: {len(all_symbols)}")

    keywords = ["NAS", "100", "USTEC", "NQ", "TECH", "NDX", "US100"]
    matches = []

    for s in all_symbols:
        name_upper = s.name.upper()
        desc_upper = s.description.upper()
        # Look for relevant symbols
        if any(kw in name_upper for kw in keywords) or "NASDAQ" in desc_upper or "US TECH" in desc_upper or "USA 100" in desc_upper:
            matches.append(s)

    print(f"\n[4] Found {len(matches)} matching symbol(s) in broker catalog:")
    print("-" * 70)
    print(f"{'Symbol Name':<20} {'Digits':<7} {'Spread':<8} {'Trade Mode':<12} {'Description'}")
    print("-" * 70)

    best_match = None
    for s in matches:
        # Check if selected
        mt5.symbol_select(s.name, True)
        tick = mt5.symbol_info_tick(s.name)
        tick_str = f"Bid: {tick.bid} Ask: {tick.ask}" if tick else "No tick"
        print(f"{s.name:<20} {s.digits:<7} {s.spread:<8} {s.trade_mode:<12} {s.description} ({tick_str})")

    # Prioritize Nasdaq symbols
    for s in matches:
        upper = s.name.upper()
        if "USTEC" in upper or "NAS100" in upper or "US100" in upper:
            if "X100" not in upper and best_match is None:
                best_match = s.name

    if not best_match and matches:
        for s in matches:
            if "USTEC" in s.name.upper():
                best_match = s.name
                break

    if not best_match and matches:
        best_match = matches[0].name

    print("-" * 70)

    # 4. Test quote and candle data on best match
    if best_match:
        print(f"\n[5] Testing Market Data on Best Match Symbol: '{best_match}'...")
        mt5.symbol_select(best_match, True)
        s_info = mt5.symbol_info(best_match)
        if s_info:
            print(f"    Point Size      : {s_info.point}")
            print(f"    Digits          : {s_info.digits}")
            print(f"    Volume Min      : {s_info.volume_min}")
            print(f"    Volume Step     : {s_info.volume_step}")
            print(f"    Volume Max      : {s_info.volume_max}")
            print(f"    Trade Mode      : {s_info.trade_mode}")

        tick = mt5.symbol_info_tick(best_match)
        if tick:
            print(f"    Live Tick       : Bid={tick.bid}, Ask={tick.ask}, Spread={(tick.ask - tick.bid):.2f}")
        else:
            print("    [NOTE] No tick available right now (market may be closed for weekend).")

        # Test M5 and M15 bars
        rates_m5 = mt5.copy_rates_from_pos(best_match, mt5.TIMEFRAME_M5, 0, 5)
        if rates_m5 is not None and len(rates_m5) > 0:
            print(f"    M5 Rates Test   : Successfully retrieved {len(rates_m5)} bars. Latest Close={rates_m5[-1]['close']}")
        else:
            print("    [WARNING] Could not fetch M5 rates.")

        rates_m15 = mt5.copy_rates_from_pos(best_match, mt5.TIMEFRAME_M15, 0, 5)
        if rates_m15 is not None and len(rates_m15) > 0:
            print(f"    M15 Rates Test  : Successfully retrieved {len(rates_m15)} bars. Latest Close={rates_m15[-1]['close']}")
        else:
            print("    [WARNING] Could not fetch M15 rates.")

        print(f"\n[RECOMMENDATION] Set FORCED_SYMBOL = '{best_match}' in config.py")

    mt5.shutdown()
    print("\n[6] MT5 shutdown cleanly. Test complete.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
