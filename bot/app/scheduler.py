"""Background loop that sends reminders when they are due."""
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config, db, telegram_api, timeutil


def send_due_reminders():
    now_utc = datetime.now(timezone.utc)
    for row in db.due_reminders(now_utc.isoformat()):
        local_today = now_utc.astimezone(ZoneInfo(row["tz"])).date()
        due = timeutil.format_due(row["due_date"], row["due_time"], local_today)
        code = f"T{row['id']:03d}"
        text = (f"Reminder: {row['title']}\nDue: {due}\n\n"
                f"/done {code}   /snooze {code} {config.DEFAULT_SNOOZE_MINUTES}   /cancel {code}")
        try:
            telegram_api.send_message(row["chat_id"], text)
            db.mark_reminder_sent(row["id"])
        except Exception as exc:
            print(f"[error] reminder {code}: {exc}")


def run_forever():
    while True:
        try:
            send_due_reminders()
        except Exception as exc:
            print(f"[error] scheduler: {type(exc).__name__}: {exc}")
        time.sleep(config.REMINDER_CHECK_SECONDS)
