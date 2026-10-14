"""Settings loaded from config.yaml and the .env file."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

with open(BASE_DIR / "config.yaml", encoding="utf-8") as _f:
    _cfg = yaml.safe_load(_f) or {}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

TIMEZONE = _cfg.get("timezone", "Asia/Karachi")
ALLOWED_CHAT_IDS = {int(x) for x in _cfg.get("allowed_chat_ids", []) or []}
LANGUAGE = _cfg.get("language", "") or ""
MAX_VOICE_SECONDS = int(_cfg.get("max_voice_seconds", 300))
REMINDER_CHECK_SECONDS = int(_cfg.get("reminder_check_seconds", 20))
DEFAULT_SNOOZE_MINUTES = int(_cfg.get("default_snooze_minutes", 30))
CATEGORIES = _cfg.get("categories") or ["Work", "Personal", "Education", "Shopping", "Other"]
MAX_TASKS_PER_MESSAGE = 20

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
