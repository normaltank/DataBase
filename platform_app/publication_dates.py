"""Possible calendar intervals for publication dates with year/month/day precision."""
import calendar
import re
from datetime import date

from flask import abort


def query_range(args):
    bounds = []
    for key in ("from", "to"):
        value = args.get(key, "")
        if not value:
            bounds.append(None)
            continue
        possible = interval(value)
        if len(value) != 10 or possible is None:
            abort(400, "发布日期格式不正确，请使用 YYYY-MM-DD 的有效日期。")
        bounds.append(possible[0])
    start, end = bounds
    if start and end and start > end:
        abort(400, "发布日期起止范围不正确，起始日期不能晚于截止日期。")
    return start, end


def interval(value):
    if not re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?", value or ""):
        return None
    try:
        parts = [int(part) for part in value.split("-")]
        if len(parts) == 1:
            return date(parts[0], 1, 1), date(parts[0], 12, 31)
        if len(parts) == 2:
            year, month = parts
            return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        day = date(*parts)
        return day, day
    except ValueError:
        return None
