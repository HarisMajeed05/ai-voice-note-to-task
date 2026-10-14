"""Minimal Telegram Bot API client using long polling."""
import requests

from . import config

_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
_FILE_BASE = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}"


def _call(method, timeout=30, **params):
    resp = requests.post(f"{_BASE}/{method}", json=params, timeout=timeout)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data["result"]


def get_me():
    return _call("getMe")


def get_updates(offset=None, poll_seconds=30):
    params = {"timeout": poll_seconds, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return _call("getUpdates", timeout=poll_seconds + 10, **params)


def send_message(chat_id, text):
    for start in range(0, len(text), 4000):
        _call("sendMessage", chat_id=chat_id, text=text[start:start + 4000])


def send_typing(chat_id):
    try:
        _call("sendChatAction", chat_id=chat_id, action="typing")
    except Exception:
        pass


def download_file(file_id):
    """Returns (file_name, bytes) for a file stored on Telegram."""
    info = _call("getFile", file_id=file_id)
    path = info["file_path"]
    resp = requests.get(f"{_FILE_BASE}/{path}", timeout=60)
    resp.raise_for_status()
    return path.rsplit("/", 1)[-1], resp.content
