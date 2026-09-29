"""
The time and the date, as text.

The second was padded on the wrong side - ``second += '0'`` when it was one character - so
five seconds past the minute read as ``:50``. The same three lines were copied into
``get_current_time``, ``get_date_and_time`` and ``fileio.get_last_modified_date``, and all
three said it. ``strftime`` does the padding here.

``get_time_zone`` ended with ``if not time:`` - the module, which is always there - rather
than ``if not time_zone``, so an empty answer would have been indexed anyway.

``pytz`` is gone: one function wanted one timezone, which the standard library has had since
Python 3.9, with a fallback for Maya 2022's 3.7.
"""

# python imports
import time
from datetime import datetime


#: How a date is written when nobody says otherwise.
DAY_FIRST = '{day:02d}{separator}{month:02d}{separator}{year:04d}'
YEAR_FIRST = '{year:04d}{separator}{month:02d}{separator}{day:02d}'


def get_current_time(date_and_time=True, reverse_date=False):
    """
    :param bool date_and_time: The date as well as the time.
    :param bool reverse_date: Year first rather than day first.
    :return: ``'29-09-2026 14:05:07'``.
    :rtype: str
    """

    now = datetime.now()
    clock = now.strftime('%H:%M:%S')
    if not date_and_time:
        return clock
    return '{} {}'.format(_date(now, reverse_date, '-'), clock)


def get_current_date(reverse_date=False, separator=None):
    """
    :param bool reverse_date: Year first rather than day first.
    :param str separator: What to put between the parts.
    :return: Today, as text.
    :rtype: str
    """

    return _date(datetime.now(), reverse_date, separator or '-')


def get_date_and_time(reverse_date=False, separator=None):
    """
    :param bool reverse_date: Year first rather than day first.
    :param str separator: What to put between the parts of the date.
    :return: Now, as text.
    :rtype: str
    """

    now = datetime.now()
    return '{} {}'.format(_date(now, reverse_date, separator or '-'), now.strftime('%H:%M:%S'))


def get_current_pst_time(zone='America/Los_Angeles'):
    """
    :param str zone: Which timezone.
    :return: The time there, or the local time when this Python cannot work out timezones.
    :rtype: str
    """

    try:
        from zoneinfo import ZoneInfo                                # Python 3.9 and later

        return datetime.now(ZoneInfo(zone)).strftime('%H:%M:%S')
    except Exception:                                                # noqa: BLE001
        try:
            import pytz                                              # Maya 2022's 3.7

            return datetime.now(pytz.timezone(zone)).strftime('%H:%M:%S')
        except Exception:                                            # noqa: BLE001
            return datetime.now().strftime('%H:%M:%S')


def get_time_zone():
    """
    :return: What this machine calls its timezone, or ''.
    :rtype: str
    """

    names = time.tzname or ()
    return names[0] if names else ''


def _date(when, reverse_date, separator):
    """
    :param datetime when: The moment.
    :param bool reverse_date: Year first.
    :param str separator: What to put between the parts.
    :return: The date, with every part padded to its width.
    :rtype: str
    """

    shape = YEAR_FIRST if reverse_date else DAY_FIRST
    return shape.format(day=when.day, month=when.month, year=when.year, separator=separator)
