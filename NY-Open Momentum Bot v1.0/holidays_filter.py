"""
NY-Open Momentum Bot v1.0 - Holiday & Weekend Filter Module
===========================================================
Prevents trading on weekends and official US stock market (NYSE/NASDAQ) holidays.
"""

from datetime import date, timedelta


def _easter_date(year: int) -> date:
    """Calculate Western Easter Sunday using Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """
    Find the nth occurrence of a weekday in a given month.
    weekday: 0 = Monday, ..., 6 = Sunday
    n: 1-indexed (e.g., 3 for third Monday)
    """
    first_day = date(year, month, 1)
    day_offset = (weekday - first_day.weekday()) % 7
    first_occurrence = first_day + timedelta(days=day_offset)
    return first_occurrence + timedelta(weeks=n - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Find the last occurrence of a weekday in a given month."""
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    day_offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=day_offset)


def _observed_date(d: date) -> date:
    """
    Apply US Federal / Stock Exchange observation rules:
    - If holiday lands on Saturday, observed on preceding Friday.
    - If holiday lands on Sunday, observed on following Monday.
    """
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    elif d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def get_us_market_holidays(year: int) -> dict:
    """
    Returns a dictionary of date -> holiday_name for US equity market holidays.
    """
    holidays = {}

    # New Year's Day (Jan 1)
    holidays[_observed_date(date(year, 1, 1))] = "New Year's Day"

    # Martin Luther King Jr. Day (3rd Monday of January)
    holidays[_nth_weekday_of_month(year, 1, 0, 3)] = "Martin Luther King Jr. Day"

    # Presidents' Day / Washington's Birthday (3rd Monday of February)
    holidays[_nth_weekday_of_month(year, 2, 0, 3)] = "Presidents' Day"

    # Good Friday (Friday before Easter)
    easter = _easter_date(year)
    good_friday = easter - timedelta(days=2)
    holidays[good_friday] = "Good Friday"

    # Memorial Day (Last Monday of May)
    holidays[_last_weekday_of_month(year, 5, 0)] = "Memorial Day"

    # Juneteenth National Independence Day (June 19)
    holidays[_observed_date(date(year, 6, 19))] = "Juneteenth"

    # Independence Day (July 4)
    holidays[_observed_date(date(year, 7, 4))] = "Independence Day"

    # Labor Day (1st Monday of September)
    holidays[_nth_weekday_of_month(year, 9, 0, 1)] = "Labor Day"

    # Thanksgiving Day (4th Thursday of November)
    holidays[_nth_weekday_of_month(year, 11, 3, 4)] = "Thanksgiving Day"

    # Christmas Day (Dec 25)
    holidays[_observed_date(date(year, 12, 25))] = "Christmas Day"

    return holidays


def is_trading_day(current_date: date) -> (bool, str):
    """
    Checks if current_date is a valid market trading day.
    Returns:
        (True, "Market Open") if trading is permitted.
        (False, reason_str) if market is closed (Weekend or Holiday).
    """
    # Check weekend (5 = Saturday, 6 = Sunday)
    weekday = current_date.weekday()
    if weekday == 5:
        return False, "Weekend (Saturday) - Market Closed"
    if weekday == 6:
        return False, "Weekend (Sunday) - Market Closed"

    # Check holiday
    holidays = get_us_market_holidays(current_date.year)
    if current_date in holidays:
        return False, f"US Market Holiday: {holidays[current_date]} - Market Closed"

    return True, "Market Open"

