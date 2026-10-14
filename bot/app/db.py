"""SQLite storage for tasks, chat settings and processed update IDs."""
import sqlite3
import threading

from . import config

_local = threading.local()

_COLUMNS = {
    "title", "category", "due_date", "due_time", "remind_at", "reminder_sent",
    "status", "needs_clarification", "clarification_reason",
}


def conn():
    """One connection per thread."""
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(config.DATA_DIR / "tasks.db")
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                due_date TEXT,
                due_time TEXT,
                remind_at TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                needs_clarification INTEGER NOT NULL DEFAULT 0,
                clarification_reason TEXT,
                tz TEXT NOT NULL,
                transcript TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, timezone TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS processed (update_id INTEGER PRIMARY KEY);
            """
        )
        c.commit()
        _local.conn = c
    return c


def mark_processed(update_id):
    """Returns False when the update was already handled."""
    try:
        with conn():
            conn().execute("INSERT INTO processed (update_id) VALUES (?)", (update_id,))
        return True
    except sqlite3.IntegrityError:
        return False


def get_timezone(chat_id):
    row = conn().execute("SELECT timezone FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
    return row["timezone"] if row else config.TIMEZONE


def set_timezone(chat_id, tz):
    with conn():
        conn().execute("INSERT OR REPLACE INTO chats (chat_id, timezone) VALUES (?, ?)", (chat_id, tz))


def add_task(chat_id, title, category, due_date, due_time, remind_at,
             needs_clarification, reason, tz, transcript, created_at):
    with conn():
        cur = conn().execute(
            """INSERT INTO tasks (chat_id, title, category, due_date, due_time, remind_at,
               needs_clarification, clarification_reason, tz, transcript, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (chat_id, title, category, due_date, due_time, remind_at,
             int(needs_clarification), reason, tz, transcript, created_at),
        )
    return cur.lastrowid


def get_task(chat_id, task_id):
    return conn().execute(
        "SELECT * FROM tasks WHERE id=? AND chat_id=?", (task_id, chat_id)
    ).fetchone()


def open_tasks(chat_id):
    return conn().execute(
        "SELECT * FROM tasks WHERE chat_id=? AND status IN ('pending','snoozed') ORDER BY id",
        (chat_id,),
    ).fetchall()


def first_needing_clarification(chat_id):
    return conn().execute(
        """SELECT * FROM tasks WHERE chat_id=? AND needs_clarification=1
           AND status IN ('pending','snoozed') ORDER BY id LIMIT 1""",
        (chat_id,),
    ).fetchone()


def update_task(task_id, **fields):
    bad = set(fields) - _COLUMNS
    if bad:
        raise ValueError(f"Unknown columns: {bad}")
    sets = ", ".join(f"{k}=?" for k in fields)
    with conn():
        conn().execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), task_id))


def due_reminders(now_iso):
    return conn().execute(
        """SELECT * FROM tasks WHERE status IN ('pending','snoozed') AND reminder_sent=0
           AND remind_at IS NOT NULL AND remind_at <= ? ORDER BY remind_at""",
        (now_iso,),
    ).fetchall()


def mark_reminder_sent(task_id):
    with conn():
        conn().execute(
            """UPDATE tasks SET reminder_sent=1,
               status=CASE WHEN status='snoozed' THEN 'pending' ELSE status END WHERE id=?""",
            (task_id,),
        )
