# FortunesAndArtBot

Small, dependency-injectable Python bot that:

- runs a shell pipeline that produces an ASCII-art *fortune* (`fortune | cowsay` + random options),
- renders the ASCII art to a **PNG** (green text on black background),
- posts that PNG to a Telegram channel using `sendPhoto`,
- attaches a standard caption: **`Your fortune cookie for the day. Epoch time: <INT>`** (HTML-escaped),
- is deliberately **image-only** (no separate `sendMessage` posts),
- designed to be testable (inject `requests` and `runner`) and run headless on Debian/Raspbian (including Raspberry Pi).

---

## Repository layout
```commandline
.
├── src/
    └── __init__.py
│   └── main.py          # FortuneBot implementation
├── tests/
│   ├── conftest.py      # fixtures: fake_requests, broken_requests, runners
│   └── test_main.py
├── README.md
└── requirements.txt
```

---

## Features

- Renders ASCII art into a PNG with green text (`RGB(0,255,0)`) on black background (`RGB(0,0,0)`).
- Robust Pillow fallbacks: measures text with `draw.textbbox`, `font.getbbox`, or `font.getmask` depending on Pillow version.
- Caption is deterministic when `time_func` is injected (handy for tests).
- Clear `run_once()` exit codes:
  - `0` — success (photo posted)
  - `2` — config error (missing env vars when run as script)
  - `3` — Telegram returned `ok:false`
  - `4` — render failed
  - `5` — network/requests error while uploading

---

## Requirements

### System packages (Debian / Raspbian)

- `python3` (3.11+ recommended)
- `python3-venv` (optional)
- `fortune-mod` / `cowsay` (optional for pipeline output — tests inject runners)
- `fonts-dejavu-core` (recommended — ensures good monospace font)
- `coreutils` and `bsdmainutils` or other packages providing `shuf`/`fmt` (commonly available on Debian/Ubuntu/Raspbian)

> The test suite uses injected runners and fake requests, so `fortune`/`cowsay` are not required to run tests.

### Python packages

Create a virtual environment and install:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Add a `requirements.txt` with at least:
```commandline
pillow
requests
pytest
```

## Quick start

1. Create a Telegram bot via BotFather and obtain its token.

2. Add your bot to the channel you want to post to (make it an admin if necessary).

3. Export environment variables:


```commandline
export TELEGRAM_BOT_TOKEN="123456:ABCDEF..."
export TELEGRAM_CHAT_ID="@your_channel_or_numeric_id"
```
4. Run once:
```commandline
python src/main.py
```

If configured correctly, the bot will run the pipeline in `DEFAULT_CMD`, render an ASCII-art PNG, and post it to the channel with the epoch caption.


## Usage as a library

You can use the `FortuneBot` class directly:

```commandline
from src.main import FortuneBot

bot = FortuneBot("TOKEN", "@chan")
rc = bot.run_once()
```

Deterministic caption for tests:

```commandline
bot = FortuneBot("TOKEN", "@chan", time_func=lambda: 1234567890)
```

You may also inject:

- `requests_module=` — a requests-like object (useful in tests)

- `runner=` — a callable that returns an object with `.stdout` and `.stderr` (e.g., a fake or `subprocess.run` wrapper)


## Testing

Run tests with pytest (virtualenv activated):


```commandline
pytest -q
```

- `tests/conftest.py` provides helpers:

- `fake_requests` and `broken_requests` fixtures simulate network success/failure.

- `runner_ok` and `runner_no_stdout` fixtures simulate subprocess output.

### Important test coverage includes:

- PNG rendering (PNG header, black background, green-ish text pixels),

- font fallback,

- Pillow API fallback,

- `post_photo` error handling,

- caption generation (deterministic via `time_func`),

- separation of image content (from `DEFAULT_CMD`) vs caption (epoch message).


## Scheduling (systemd recommended)

Create `/etc/systemd/system/fortune-bot.service`:

```commandline
[Unit]
Description=FortunesAndArtBot - post daily fortune image

[Service]
Type=oneshot
User=pi
WorkingDirectory=/path/to/your/repo
Environment=TELEGRAM_BOT_TOKEN=123:ABC...
Environment=TELEGRAM_CHAT_ID=@yourchannel
ExecStart=/path/to/venv/bin/python src/main.py
```

Create `/etc/systemd/system/fortune-bot.timer`:

```commandline
[Unit]
Description=Run FortunesAndArtBot daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Enable & start:
```commandline
sudo systemctl enable --now fortune-bot.timer
```

### Cron alternative
```commandline
0 9 * * * . /path/to/venv/bin/activate && TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=@chan python /path/to/repo/src/main.py >> /var/log/fortunebot.log 2>&1
```
## Troubleshooting & notes

- Headless / RPi: Pillow rendering is headless — no X11 required. Ensure `fonts-dejavu-core` or another monospace TTF is installed.

- Pillow versions: The renderer uses `draw.textbbox` when available and falls back to `font.getbbox` or `font.getmask`. This keeps it compatible across Pillow versions.

- If image doesn't look right: Verify `DEFAULT_CMD` produces ASCII art on your host:

```commandline
bash -c "fortune -a | fmt -80 -s | $(shuf -n 1 -e cowsay cowthink) -b -f $(cowsay -l | tail -n +2 | shuf -n1) -n"
```
Adjust to match available system utilities if needed.

- Caption safety: Captions are HTML-escaped and truncated to Telegram's limit (1024 chars).

- Return codes: `run_once()` returns small integer codes (see Features) for systemd/cron reporting.

## Development notes

- Keep the code dependency-injectable for easy unit testing.

- `time_func` enables deterministic caption testing.

- If you want to add text fallback posting later, implement a separate method (e.g., `post_text`) rather than mixing flows.

## Contributing

PRs welcome. Keep changes small, add tests, and maintain readability.
