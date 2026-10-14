"""Date and time helpers: parsing, validation and display."""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_TIME_AMPM = re.compile(r"^(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\.?$", re.I)
_TIME_24H = re.compile(r"^(?:at\s+)?(\d{1,2}):(\d{2})$")
_BARE_HOUR = re.compile(r"^(?:at\s+)?\d{1,2}$")


def _clean(text):
    return text.strip().rstrip(".,!?").strip()


def parse_time(text):
    """Parses '3pm', '3:30 pm' or '15:30'. Returns 'HH:MM' or None."""
    text = _clean(text)
    m = _TIME_AMPM.match(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not (1 <= hour <= 12 and 0 <= minute <= 59):
            return None
        if m.group(3).lower() == "p" and hour != 12:
            hour += 12
        if m.group(3).lower() == "a" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    m = _TIME_24H.match(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None


def is_bare_hour(text):
    """True for replies like '5' where am or pm is unclear."""
    return bool(_BARE_HOUR.match(_clean(text)))


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def parse_hhmm(value):
    try:
        h, m = str(value).split(":")
        return time(int(h), int(m))
    except (TypeError, ValueError):
        return None


def evaluate(due_date, due_time, remind_date, remind_time, now_local, tz):
    """Checks a task's date and time.

    Returns (remind_at_utc_iso or None, needs_clarification, reason).
    Reasons: date, time, past.
    """
    d = parse_date(due_date)
    if d is None:
        return None, True, "date"
    t = parse_hhmm(due_time) if due_time else None
    if t is None:
        return None, True, ("past" if d < now_local.date() else "time")
    zone = ZoneInfo(tz)
    due_dt = datetime.combine(d, t, tzinfo=zone)
    if due_dt <= now_local:
        return None, True, "past"
    rd = parse_date(remind_date) or d
    rt = parse_hhmm(remind_time) if remind_time else t
    rt = rt or t
    remind_dt = datetime.combine(rd, rt, tzinfo=zone)
    if remind_dt <= now_local:
        return None, True, "past"
    return remind_dt.astimezone(timezone.utc).isoformat(), False, None


def day_label(d, today):
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    return d.strftime("%a, %b %d")


def format_due(due_date, due_time, today):
    d = parse_date(due_date)
    if d is None:
        return "date not set"
    label = day_label(d, today)
    t = parse_hhmm(due_time) if due_time else None
    if t is None:
        return label
    return f"{label}, {t.strftime('%I:%M %p').lstrip('0')}"
