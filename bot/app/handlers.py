"""Handles Telegram updates: voice notes, text, and commands."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, db, extractor, groq_api, telegram_api, timeutil

HELP = (
    "Send a voice note or text with your tasks. I split them, understand dates, and set reminders.\n\n"
    "Commands:\n"
    "/tasks - list open tasks\n"
    "/done ID - mark done\n"
    "/snooze ID [minutes] - remind again later\n"
    "/cancel ID - cancel a task\n"
    "/time ID <date and time> - set or fix a task time\n"
    "/timezone Area/City - change timezone, e.g. /timezone Asia/Karachi"
)


def _send(chat_id, text):
    telegram_api.send_message(chat_id, text)


def _now(tz):
    return datetime.now(ZoneInfo(tz))


def _task_id(text):
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else None


def _code(task_id):
    return f"T{task_id:03d}"


def _reminder_text(row, now_local):
    if row["needs_clarification"]:
        return {"date": "needs a date", "time": "needs a time", "past": "time has passed, needs a new one"}.get(
            row["clarification_reason"], "needs details")
    if row["remind_at"]:
        return "reminder set"
    return "no reminder"


def _task_line(row, now_local):
    due = timeutil.format_due(row["due_date"], row["due_time"], now_local.date())
    return f"{_code(row['id'])} | {row['title']} [{row['category']}]\n   {due} | {_reminder_text(row, now_local)}"


def _question(row):
    code, title = _code(row["id"]), row["title"]
    reason = row["clarification_reason"]
    if reason == "time":
        q = f"What time should I remind you for {code} ({title})? Example: 3pm or 15:30"
    elif reason == "past":
        q = f"The time for {code} ({title}) has already passed. What new date and time?"
    else:
        q = f"What date and time for {code} ({title})? Example: tomorrow 5pm"
    return q + f"\nOr /cancel {code}"


def _ask_next(chat_id):
    row = db.first_needing_clarification(chat_id)
    return _question(row) if row else None


def _create_tasks(chat_id, tasks, transcript, tz, now_local):
    lines = []
    for t in tasks:
        remind_at, needs, reason = timeutil.evaluate(
            t["due_date"], t["due_time"], t["remind_date"], t["remind_time"], now_local, tz)
        valid_date = timeutil.parse_date(t["due_date"])
        valid_time = timeutil.parse_hhmm(t["due_time"]) if t["due_time"] else None
        task_id = db.add_task(
            chat_id, t["title"], t["category"],
            valid_date.isoformat() if valid_date else None,
            valid_time.strftime("%H:%M") if valid_time else None,
            remind_at, needs, reason, tz, transcript,
            datetime.now(timezone.utc).isoformat(),
        )
        lines.append(_task_line(db.get_task(chat_id, task_id), now_local))
    return lines


def _apply_followup(chat_id, row, text, tz):
    now_local = _now(tz)
    new_date, new_time = None, None
    if row["clarification_reason"] == "time" and row["due_date"]:
        if timeutil.is_bare_hour(text):
            _send(chat_id, "Please include am or pm, for example 5pm, or use 24-hour time like 17:00.")
            return
        new_time = timeutil.parse_time(text)
    if new_time is None:
        new_date, new_time = extractor.resolve_followup(
            text, row["title"], row["due_date"], row["due_time"], now_local, tz)
    due_date = timeutil.parse_date(new_date).isoformat() if timeutil.parse_date(new_date) else row["due_date"]
    due_time = new_time or row["due_time"]
    if not new_date and not new_time:
        _send(chat_id, "I could not find a date or time in that. " + _question(row))
        return
    remind_at, needs, reason = timeutil.evaluate(due_date, due_time, None, None, now_local, tz)
    db.update_task(row["id"], due_date=due_date, due_time=due_time, remind_at=remind_at,
                   reminder_sent=0, needs_clarification=int(needs), clarification_reason=reason)
    updated = db.get_task(chat_id, row["id"])
    msg = "Updated:\n" + _task_line(updated, now_local)
    nxt = _ask_next(chat_id)
    _send(chat_id, msg + ("\n\n" + nxt if nxt else ""))


def _process_text(chat_id, text, source, tz):
    """Turns a transcript or typed text into new tasks or an answer to a pending question."""
    now_local = _now(tz)
    pending = db.first_needing_clarification(chat_id)
    if pending and (timeutil.parse_time(text) or timeutil.is_bare_hour(text)):
        _apply_followup(chat_id, pending, text, tz)
        return
    tasks = extractor.extract_tasks(text, now_local, tz)
    if tasks:
        lines = _create_tasks(chat_id, tasks, text, tz, now_local)
        head = f"Heard: \"{text}\"\n\n" if source == "voice" else ""
        count = f"{len(lines)} task{'s' if len(lines) != 1 else ''} saved:\n"
        nxt = _ask_next(chat_id)
        _send(chat_id, head + count + "\n".join(lines) + ("\n\n" + nxt if nxt else ""))
        return
    if pending:
        _apply_followup(chat_id, pending, text, tz)
        return
    if source == "voice":
        _send(chat_id, f"Heard: \"{text}\"\n\nI did not find a task in that.")
    else:
        _send(chat_id, "I did not find a task in that. Send /help to see what I can do.")


def _handle_voice(chat_id, message, tz):
    media = message.get("voice") or message.get("audio")
    if media.get("duration", 0) > config.MAX_VOICE_SECONDS:
        _send(chat_id, f"That recording is too long. Please keep it under {config.MAX_VOICE_SECONDS} seconds.")
        return
    telegram_api.send_typing(chat_id)
    name, raw = telegram_api.download_file(media["file_id"])
    try:
        transcript = groq_api.transcribe(name, raw)
    except Exception as exc:
        print(f"[error] transcription failed: {exc}")
        _send(chat_id, "I could not transcribe that audio. Please try again.")
        return
    if len(transcript.strip()) < 3:
        _send(chat_id, "I could not hear anything clear. Please record again closer to the mic.")
        return
    _process_text(chat_id, transcript.strip(), "voice", tz)


def _cmd_tasks(chat_id, tz):
    rows = db.open_tasks(chat_id)
    if not rows:
        _send(chat_id, "No open tasks.")
        return
    now_local = _now(tz)
    _send(chat_id, "Open tasks:\n\n" + "\n".join(_task_line(r, now_local) for r in rows))


def _cmd_status(chat_id, args, status, label):
    task_id = _task_id(args)
    row = db.get_task(chat_id, task_id) if task_id else None
    if not row:
        _send(chat_id, f"Task not found. Usage: /{label} T001")
        return
    db.update_task(task_id, status=status)
    _send(chat_id, f"{_code(task_id)} marked {status}: {row['title']}")


def _cmd_snooze(chat_id, args):
    parts = args.split()
    task_id = _task_id(parts[0]) if parts else None
    row = db.get_task(chat_id, task_id) if task_id else None
    if not row or row["status"] not in ("pending", "snoozed"):
        _send(chat_id, "Task not found. Usage: /snooze T001 [minutes]")
        return
    minutes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else config.DEFAULT_SNOOZE_MINUTES
    remind_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    db.update_task(task_id, remind_at=remind_at, reminder_sent=0, status="snoozed")
    _send(chat_id, f"{_code(task_id)} snoozed for {minutes} minutes.")


def _cmd_time(chat_id, args, tz):
    parts = args.split(None, 1)
    task_id = _task_id(parts[0]) if parts else None
    row = db.get_task(chat_id, task_id) if task_id else None
    if not row or row["status"] not in ("pending", "snoozed") or len(parts) < 2:
        _send(chat_id, "Usage: /time T001 tomorrow 3pm")
        return
    _apply_followup(chat_id, row, parts[1], tz)


def _cmd_timezone(chat_id, args):
    name = args.strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        _send(chat_id, "Unknown timezone. Example: /timezone Asia/Karachi")
        return
    db.set_timezone(chat_id, name)
    _send(chat_id, f"Timezone set to {name}. Existing reminders keep their original times.")


def _handle_command(chat_id, text, tz):
    cmd, _, args = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    if cmd == "/start":
        _send(chat_id, f"Hi! Your chat ID is {chat_id}.\n\n{HELP}")
    elif cmd == "/help":
        _send(chat_id, HELP)
    elif cmd == "/tasks":
        _cmd_tasks(chat_id, tz)
    elif cmd == "/done":
        _cmd_status(chat_id, args, "done", "done")
    elif cmd == "/cancel":
        _cmd_status(chat_id, args, "cancelled", "cancel")
    elif cmd == "/snooze":
        _cmd_snooze(chat_id, args)
    elif cmd == "/time":
        _cmd_time(chat_id, args, tz)
    elif cmd == "/timezone":
        _cmd_timezone(chat_id, args)
    else:
        _send(chat_id, "Unknown command. Send /help.")


def handle_update(update):
    message = update.get("message")
    if not message or not db.mark_processed(update["update_id"]):
        return
    chat_id = message["chat"]["id"]
    if config.ALLOWED_CHAT_IDS and chat_id not in config.ALLOWED_CHAT_IDS:
        _send(chat_id, f"This bot is private. Your chat ID is {chat_id}.")
        return
    tz = db.get_timezone(chat_id)
    try:
        if message.get("voice") or message.get("audio"):
            _handle_voice(chat_id, message, tz)
        elif message.get("text", "").startswith("/"):
            _handle_command(chat_id, message["text"].strip(), tz)
        elif message.get("text"):
            _process_text(chat_id, message["text"].strip(), "text", tz)
        else:
            _send(chat_id, "Send a voice note or text with your tasks.")
    except Exception as exc:
        print(f"[error] update {update.get('update_id')}: {type(exc).__name__}: {exc}")
        _send(chat_id, "Something went wrong. Please try again.")
