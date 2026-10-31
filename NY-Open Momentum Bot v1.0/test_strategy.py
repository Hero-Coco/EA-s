"""
Unit & Simulation Tests for NY-Open Momentum Bot v1.0
===================================================
Tests core mathematical, timing, trailing stop, and holiday logic
independently of live MT5 terminal connectivity.
"""

import os
import unittest
from datetime import date, datetime, time
try:
    import pytz
except ImportError:
    # Minimal fallback mock for test environment prior to pip install
    from datetime import timezone as dt_timezone, timedelta as dt_timedelta
    class _MockPytz:
        utc = dt_timezone.utc
        @staticmethod
        def timezone(name):
            return dt_timezone(dt_timedelta(hours=-4), name)
    pytz = _MockPytz

import config
from holidays_filter import is_trading_day, get_us_market_holidays


class TestHolidaysAndTiming(unittest.TestCase):
    def test_weekend_detection(self):
        # Saturday
        sat = date(2026, 10, 31)
        is_open, reason = is_trading_day(sat)
        self.assertFalse(is_open)
        self.assertIn("Saturday", reason)

        # Sunday
        sun = date(2026, 11, 1)
        is_open, reason = is_trading_day(sun)
        self.assertFalse(is_open)
        self.assertIn("Sunday", reason)

    def test_regular_trading_day(self):
        # Regular Wednesday
        wed = date(2026, 10, 28)
        is_open, reason = is_trading_day(wed)
        self.assertTrue(is_open)
        self.assertEqual(reason, "Market Open")

    def test_holidays_2026(self):
        holidays_2026 = get_us_market_holidays(2026)
        # New Year's Day
        self.assertIn(date(2026, 1, 1), holidays_2026)
        # Christmas Day
        self.assertIn(date(2026, 12, 25), holidays_2026)
        # 4th Thursday of November 2026 is Thanksgiving (Nov 26)
        self.assertIn(date(2026, 11, 26), holidays_2026)


class TestStrategyLogic(unittest.TestCase):
    def test_range_volatility_filter(self):
        # Case 1: Range is 25 points (< 30 min required) -> Must fail
        high = 20525.0
        low = 20500.0
        range_size = high - low
        self.assertLess(range_size, config.MIN_RANGE_POINTS)

        # Case 2: Range is 55 points (>= 30 required) -> Must pass
        high = 20555.0
        low = 20500.0
        range_size = high - low
        self.assertGreaterEqual(range_size, config.MIN_RANGE_POINTS)

    def test_stop_loss_calculation(self):
        range_high = 20550.0
        range_low = 20500.0
        buffer = config.SL_BUFFER_POINTS  # 10 points

        # Long Entry SL: Range Low - 10 points
        long_sl = range_low - buffer
        self.assertEqual(long_sl, 20490.0)

        # Short Entry SL: Range High + 10 points
        short_sl = range_high + buffer
        self.assertEqual(short_sl, 20560.0)

    def test_trailing_stop_math_long(self):
        entry_price = 20500.0
        # Price moves to +40 points (no trailing yet, threshold is +50)
        curr_price = 20540.0
        profit = curr_price - entry_price
        self.assertFalse(profit >= config.TRAILING_TRIGGER_POINTS)

        # Price moves to +55 points -> Trailing triggers!
        curr_price = 20555.0
        profit = curr_price - entry_price
        self.assertTrue(profit >= config.TRAILING_TRIGGER_POINTS)

        # Trail distance = 30 points behind current price
        new_sl = curr_price - config.TRAILING_DISTANCE_POINTS
        self.assertEqual(new_sl, 20525.0)

        # Price advances by 4 points (less than 5-point step) -> Do not update
        next_price = 20559.0
        step = next_price - curr_price
        self.assertLess(step, config.TRAILING_STEP_POINTS)

        # Price advances by 6 points (>= 5-point step) -> Update SL!
        next_price = 20561.0
        step = next_price - curr_price
        self.assertGreaterEqual(step, config.TRAILING_STEP_POINTS)
        updated_sl = next_price - config.TRAILING_DISTANCE_POINTS
        self.assertEqual(updated_sl, 20531.0)

    def test_trailing_stop_math_short(self):
        entry_price = 20500.0
        # Price drops to 20440 (+60 points profit on short)
        curr_price = 20440.0
        profit = entry_price - curr_price
        self.assertTrue(profit >= config.TRAILING_TRIGGER_POINTS)

        # Trail distance = 30 points above current price
        new_sl = curr_price + config.TRAILING_DISTANCE_POINTS
        self.assertEqual(new_sl, 20470.0)


if __name__ == "__main__":
    unittest.main()
