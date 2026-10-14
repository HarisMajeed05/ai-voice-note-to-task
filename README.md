# AI Voice Note to Task (Telegram + Groq)

Send a voice note to a Telegram bot. It transcribes it, splits it into tasks, understands dates, saves them, and sends reminders.

## Setup
1. Telegram: open @BotFather, send `/newbot`, copy the token.
2. Groq: create an API key at https://console.groq.com/keys
3. From the project root:
```
conda env create -f environment.yml
conda activate ai-voice-note-to-task
cd bot
copy .env.example .env        (Windows)   |   cp .env.example .env
```
4. Fill `TELEGRAM_BOT_TOKEN` and `GROQ_API_KEY` in `bot/.env`.
5. Run: `python -m app.main`
6. Open your bot in Telegram and send `/start`. It shows your chat ID. Put it in `allowed_chat_ids` in `bot/config.yaml` so only you can use the bot, then restart.

The bot and reminders only work while this program is running.

## Commands
| Command | What it does |
|---|---|
| voice or text message | Creates tasks |
| `/tasks` | Lists open tasks |
| `/done T001` | Marks done |
| `/snooze T001 [minutes]` | Reminds again later (default 30) |
| `/cancel T001` | Cancels |
| `/time T001 tomorrow 3pm` | Sets or fixes date and time |
| `/timezone Asia/Karachi` | Changes timezone for the chat |

## How it behaves
- Multiple tasks in one voice note become separate tasks.
- A task is saved even without a time. A reminder is scheduled only when date and time are both known.
- Missing date, missing time, vague time ("morning") or a past time: the bot asks. Reply with a text or a voice note like `3pm`.
- Deadline and reminder time are stored separately. Say "remind me Monday 9 about the Friday 5pm report" to set both.
- Empty or unclear audio, non-task chat, duplicate Telegram updates, and impossible dates are handled with a clear reply.
- Urdu and mixed Urdu-English work through Whisper auto-detect. Set `language` in `config.yaml` to force one language.
- Relative dates are calculated from the real current time in the chat timezone (default Asia/Karachi).

## Test (offline, no keys needed)
```
cd bot
python -m unittest discover -s tests
```

## Files
- `bot/app/main.py` polling loop
- `bot/app/handlers.py` voice, text and commands
- `bot/app/extractor.py` AI task extraction
- `bot/app/timeutil.py` date and time rules
- `bot/app/scheduler.py` reminder loop
- `bot/app/db.py` SQLite storage in `bot/data/tasks.db`

## Models
Set in `.env`. Defaults: `whisper-large-v3` for speech, `qwen/qwen3.8-27b` for task extraction. Groq changes its model list, so check https://console.groq.com/docs/models if a call fails. The `reason` is printed in the console.
