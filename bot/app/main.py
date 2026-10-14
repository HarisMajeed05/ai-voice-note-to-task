"""Entry point. Run from the bot folder: python -m app.main"""
import threading
import time

import requests

from . import config, scheduler, telegram_api
from .handlers import handle_update


def main():
    if not config.TELEGRAM_BOT_TOKEN or not config.GROQ_API_KEY:
        print("Set TELEGRAM_BOT_TOKEN and GROQ_API_KEY in bot/.env")
        return
    me = telegram_api.get_me()
    print(f"Bot @{me['username']} running. Default timezone: {config.TIMEZONE}")
    if not config.ALLOWED_CHAT_IDS:
        print("Warning: allowed_chat_ids is empty, anyone can use this bot.")

    threading.Thread(target=scheduler.run_forever, daemon=True).start()

    offset = None
    while True:
        try:
            for update in telegram_api.get_updates(offset):
                offset = update["update_id"] + 1
                handle_update(update)
        except KeyboardInterrupt:
            print("Stopped.")
            return
        except (requests.RequestException, RuntimeError) as exc:
            print(f"[error] polling: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
