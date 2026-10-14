"""Offline tests with fake Telegram and fake AI responses."""
import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["TELEGRAM_BOT_TOKEN"] = "test"

from app import db, extractor, groq_api, handlers, telegram_api, timeutil  # noqa: E402

TZ = "Asia/Karachi"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=ZoneInfo(TZ))


class TimeTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(timeutil.parse_time("3pm"), "15:00")
        self.assertEqual(timeutil.parse_time("at 3:30 PM."), "15:30")
        self.assertEqual(timeutil.parse_time("12 am"), "00:00")
        self.assertEqual(timeutil.parse_time("15:30"), "15:30")
        self.assertIsNone(timeutil.parse_time("5"))
        self.assertTrue(timeutil.is_bare_hour("5"))
        self.assertIsNone(timeutil.parse_time("25:00"))

    def test_evaluate(self):
        ok = timeutil.evaluate("2026-10-14", "10:00", None, None, NOW, TZ)
        self.assertEqual(ok[1:], (False, None))
        self.assertEqual(ok[0], "2026-10-14T05:00:00+00:00")
        self.assertEqual(timeutil.evaluate("2026-10-16", None, None, None, NOW, TZ), (None, True, "time"))
        self.assertEqual(timeutil.evaluate(None, "10:00", None, None, NOW, TZ), (None, True, "date"))
        self.assertEqual(timeutil.evaluate("2026-10-12", "10:00", None, None, NOW, TZ), (None, True, "past"))
        self.assertEqual(timeutil.evaluate("2026-02-30", "10:00", None, None, NOW, TZ), (None, True, "date"))

    def test_separate_reminder(self):
        r = timeutil.evaluate("2026-10-20", "17:00", "2026-10-19", "09:00", NOW, TZ)
        self.assertEqual(r[0], "2026-10-19T04:00:00+00:00")


class FlowTests(unittest.TestCase):
    def setUp(self):
        db.conn().executescript("DELETE FROM tasks; DELETE FROM processed; DELETE FROM chats;")
        self.sent = []
        telegram_api.send_message = lambda chat, text: self.sent.append(text)
        telegram_api.send_typing = lambda chat: None
        telegram_api.download_file = lambda fid: ("v.oga", b"x")
        handlers._now = lambda tz: NOW
        self.transcript = ""
        groq_api.transcribe = lambda name, raw: self.transcript
        self.llm_calls = []

    def fake_llm(self, payload):
        def run(prompt):
            self.llm_calls.append(prompt)
            return payload
        extractor.llm_json = run

    def voice(self, update_id, chat=1):
        return {"update_id": update_id, "message": {"chat": {"id": chat}, "voice": {"file_id": "f", "duration": 5}}}

    def text(self, update_id, text, chat=1):
        return {"update_id": update_id, "message": {"chat": {"id": chat}, "text": text}}

    def test_multi_task_voice_clarify_done_dedupe(self):
        self.transcript = "Submit the report tomorrow at 10 and call the client on Friday."
        self.fake_llm({"is_task_message": True, "tasks": [
            {"title": "Submit report", "category": "Education", "due_date": "2026-10-14", "due_time": "10:00"},
            {"title": "Call client", "category": "Work", "due_date": "2026-10-16", "due_time": None},
        ]})
        handlers.handle_update(self.voice(100))
        handlers.handle_update(self.voice(100))  # duplicate update
        self.assertEqual(len(self.sent), 1)
        self.assertIn("2 tasks saved", self.sent[0])
        self.assertIn("reminder set", self.sent[0])
        self.assertIn("What time should I remind you", self.sent[0])
        rows = db.open_tasks(1)
        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0]["remind_at"])
        self.assertIsNone(rows[1]["remind_at"])

        handlers.handle_update(self.text(101, "5"))
        self.assertIn("am or pm", self.sent[-1])
        handlers.handle_update(self.text(102, "3pm"))
        self.assertIn("reminder set", self.sent[-1])
        self.assertIsNotNone(db.get_task(1, rows[1]["id"])["remind_at"])

        handlers.handle_update(self.text(103, f"/done T{rows[0]['id']:03d}"))
        self.assertIn("marked done", self.sent[-1])
        handlers.handle_update(self.text(104, "/tasks"))
        self.assertNotIn("Submit report", self.sent[-1])

    def test_not_a_task_and_empty_audio(self):
        self.transcript = "hello how are you"
        self.fake_llm({"is_task_message": False, "tasks": []})
        handlers.handle_update(self.voice(200))
        self.assertIn("did not find a task", self.sent[-1])
        self.transcript = ""
        handlers.handle_update(self.voice(201))
        self.assertIn("could not hear", self.sent[-1])

    def test_past_and_snooze_and_other_chat(self):
        self.fake_llm({"is_task_message": True, "tasks": [
            {"title": "Old thing", "category": "Other", "due_date": "2026-10-10", "due_time": "09:00"}]})
        handlers.handle_update(self.text(300, "old thing on the 10th at 9", chat=2))
        self.assertIn("already passed", self.sent[-1])
        row = db.open_tasks(2)[0]
        handlers.handle_update(self.text(301, f"/snooze {row['id']} 10", chat=2))
        self.assertIn("snoozed for 10", self.sent[-1])
        handlers.handle_update(self.text(302, f"/done {row['id']}", chat=3))
        self.assertIn("Task not found", self.sent[-1])


if __name__ == "__main__":
    unittest.main()
