"""LLM based task extraction and follow-up answer parsing."""
import json
from datetime import timedelta

from . import config, groq_api

SYSTEM = (
    "You turn spoken or typed messages into structured tasks. "
    "Reply with one JSON object only. Never invent dates or times the user did not say."
)

EXTRACT_PROMPT = """Current local date and time: {now} (timezone {tz}).
Calendar for the next 14 days:
{calendar}

Message from the user:
\"\"\"{text}\"\"\"

Return JSON in this exact shape:
{{"is_task_message": true or false,
  "tasks": [{{"title": "short action phrase",
             "category": "one of {categories}",
             "due_date": "YYYY-MM-DD or null",
             "due_time": "HH:MM 24-hour or null",
             "remind_date": "YYYY-MM-DD or null",
             "remind_time": "HH:MM 24-hour or null"}}]}}

Rules:
- Create one separate task for each thing the user needs to do.
- Calculate relative dates (tomorrow, Friday, next Monday, in two hours) from the current date and time above. Use the calendar for weekdays.
- If the user gives a vague time like morning, evening, tonight, or no time at all, set due_time to null.
- If the user gives only a vague period like "sometime next week" or no date, set due_date to null.
- Only fill remind_date and remind_time when the user asks to be reminded at a different moment than the deadline. Otherwise use null.
- If am or pm is unclear for a time, set due_time to null.
- The message may mix Urdu and English. Write titles in English and keep names as spoken.
- If the message is only chat, a question, or only gives a date or time without an action, set is_task_message to false and tasks to [].
"""

FOLLOWUP_PROMPT = """Current local date and time: {now} (timezone {tz}).
Calendar for the next 14 days:
{calendar}

Task: "{title}"
Known date: {known_date}
Known time: {known_time}

The user replied:
\"\"\"{text}\"\"\"

Return JSON: {{"due_date": "YYYY-MM-DD or null", "due_time": "HH:MM 24-hour or null"}}
Use null for anything the reply does not clearly state. If am or pm is unclear, use null for the time.
"""


def _calendar(now_local):
    lines = []
    for i in range(14):
        d = now_local.date() + timedelta(days=i)
        tag = " (today)" if i == 0 else ""
        lines.append(f"{d.strftime('%a')} {d.isoformat()}{tag}")
    return "\n".join(lines)


def llm_json(prompt):
    reply = groq_api.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt},
    ])
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON in model reply")
    return json.loads(reply[start:end + 1])


def _s(value):
    if value is None:
        return None
    value = str(value).strip()
    return None if value.lower() in {"", "null", "none"} else value


def extract_tasks(text, now_local, tz):
    """Returns a list of normalized task dicts. Empty when the message has no task."""
    prompt = EXTRACT_PROMPT.format(
        now=now_local.strftime("%A %Y-%m-%d %H:%M"), tz=tz, calendar=_calendar(now_local),
        text=text, categories=", ".join(config.CATEGORIES),
    )
    data = llm_json(prompt)
    if not data.get("is_task_message"):
        return []
    tasks = []
    for raw in (data.get("tasks") or [])[:config.MAX_TASKS_PER_MESSAGE]:
        title = _s(raw.get("title"))
        if not title:
            continue
        category = _s(raw.get("category"))
        tasks.append({
            "title": title[:200],
            "category": category if category in config.CATEGORIES else "Other",
            "due_date": _s(raw.get("due_date")),
            "due_time": _s(raw.get("due_time")),
            "remind_date": _s(raw.get("remind_date")),
            "remind_time": _s(raw.get("remind_time")),
        })
    return tasks


def resolve_followup(text, title, known_date, known_time, now_local, tz):
    """Reads the user's answer to a clarification question. Returns (date, time)."""
    prompt = FOLLOWUP_PROMPT.format(
        now=now_local.strftime("%A %Y-%m-%d %H:%M"), tz=tz, calendar=_calendar(now_local),
        title=title, known_date=known_date or "none", known_time=known_time or "none", text=text,
    )
    data = llm_json(prompt)
    return _s(data.get("due_date")), _s(data.get("due_time"))
