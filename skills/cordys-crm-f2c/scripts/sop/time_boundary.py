"""Cordys CRM business-date conversion with an explicit UTC+8 boundary."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone


TIMEZONE_NAME = "Asia/Shanghai"
TIMEZONE_OFFSET = "+08:00"
CRM_TIMEZONE = timezone(timedelta(hours=8), TIMEZONE_NAME)
DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


class TimeBoundaryError(ValueError):
    """A business date cannot be converted without guessing its timezone."""


def _parse_datetime(value, formats=DATETIME_FORMATS):
    if not isinstance(value, str) or not value.strip():
        raise TimeBoundaryError("日期时间必须是非空字符串")
    normalized = value.strip()
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=CRM_TIMEZONE)
        except ValueError:
            continue
    raise TimeBoundaryError(
        "日期时间格式无效；仅支持 YYYY-MM-DD、YYYY-MM-DD HH:MM 或 "
        "YYYY-MM-DD HH:MM:SS，禁止 CST 等歧义时区缩写"
    )


def _parse_date(value):
    if not isinstance(value, str) or not value.strip():
        raise TimeBoundaryError("日期必须是非空字符串")
    normalized = value.strip()
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").replace(tzinfo=CRM_TIMEZONE)
    except ValueError as exc:
        raise TimeBoundaryError("日期格式无效；仅支持 YYYY-MM-DD，禁止 CST 等时区缩写") from exc


def parse_datetime_ms(value, formats=DATETIME_FORMATS):
    """Interpret a timezone-less CRM business datetime as fixed UTC+8."""
    return int(_parse_datetime(value, formats).timestamp() * 1000)


def parse_date_ms(value):
    """Return UTC epoch milliseconds for midnight on a China business date."""
    return int(_parse_date(value).timestamp() * 1000)


def date_range(value_start, value_end):
    """Build a closed millisecond range for two inclusive business dates."""
    start = _parse_date(value_start)
    end = _parse_date(value_end)
    if end < start:
        raise TimeBoundaryError("结束日期不能早于开始日期")
    start_ms = int(start.timestamp() * 1000)
    end_ms = int((end + timedelta(days=1)).timestamp() * 1000) - 1
    return {
        "timezone": TIMEZONE_NAME,
        "offset": TIMEZONE_OFFSET,
        "startDate": value_start.strip(),
        "endDate": value_end.strip(),
        "startMs": start_ms,
        "endMs": end_ms,
        "value": [start_ms, end_ms],
    }


def timestamp_value(value):
    timestamp_ms = parse_datetime_ms(value)
    return {
        "timezone": TIMEZONE_NAME,
        "offset": TIMEZONE_OFFSET,
        "input": value.strip(),
        "timestampMs": timestamp_ms,
    }


def format_date_ms(value):
    if isinstance(value, bool):
        raise TimeBoundaryError("毫秒时间戳必须是整数")
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError) as exc:
        raise TimeBoundaryError("毫秒时间戳必须是整数") from exc
    if not 100_000_000_000 <= timestamp_ms <= 9_999_999_999_999:
        raise TimeBoundaryError("时间戳必须是毫秒级整数")
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=CRM_TIMEZONE).strftime("%Y-%m-%d")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 2 and args[0] == "date-ms":
            result = timestamp_value(args[1])
        elif len(args) == 3 and args[0] == "date-range":
            result = date_range(args[1], args[2])
        else:
            raise TimeBoundaryError(
                "用法：time_boundary.py date-ms '<YYYY-MM-DD[ HH:MM[:SS]]>'；"
                "或 time_boundary.py date-range <开始日期> <结束日期>"
            )
    except TimeBoundaryError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
