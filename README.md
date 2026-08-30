# F.R.I.D.A.Y.

F.R.I.D.A.Y. is a local Windows desktop assistant with a futuristic, animated command interface. It combines a responsive text command dock, optional wake-word voice input, local memory and reminders, desktop shortcuts, and an OpenAI-compatible AI layer.

## What changed in v2

- A full neural-command HUD: animated core, state-responsive color system, live CPU/RAM/network graph, intelligence readout, and event console.
- A proper text command dock, so the assistant remains useful even without a microphone.
- A single background controller for speech recognition, text-to-speech, AI calls, and reminders. The UI stays responsive while they run.
- Local data now lives consistently in `data/`, and Google Calendar no longer opens an OAuth browser at startup.
- Safer task execution: FRIDAY only opens `http(s)` URLs and only launches its four explicit shortcuts (Notepad, Calculator, Chrome, Spotify).
- The legacy `friday.py` is now a safe compatibility launcher; it no longer contains credentials or an old, insecure command executor.
- The PyInstaller spec now packages the current `main.py` app.

## Quick start

Use Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

If PyAudio does not install automatically, install a Windows-compatible wheel for your Python version, then rerun the app. Text commands still work when no microphone is available.

## Configure AI

Copy `.env.example` to `.env`, then add one provider key. Do not put a key in Python files and do not commit `.env`.

```powershell
Copy-Item .env.example .env
```

For OpenAI, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL`. For OpenRouter or another compatible provider, set `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and (when needed) `OPENAI_BASE_URL`.

Without a key, FRIDAY still supports these local commands:

- `remember <fact>`
- `recall` or `recall <search terms>`
- `forget <memory id or search terms>`

With AI configured, FRIDAY can also create local reminders, open safe web links, launch its approved shortcuts, search YouTube, show map directions, control media, and create Google Calendar events.

## Voice and Calendar

FRIDAY listens for a phrase containing “Friday” after the microphone is ready. Set `MIC_DEVICE_INDEX` in `.env` if the default microphone is wrong.

Put your Google OAuth `credentials.json` beside `main.py` only if you want Calendar support. FRIDAY uses a valid saved `token.json` quietly; it starts the Google authorization flow only when you explicitly create a calendar event.

## Package as an app

```powershell
pyinstaller friday.spec --clean --noconfirm
```

The executable is created as `dist/FRIDAY.exe`. Keep `.env`, `credentials.json`, and `token.json` beside it when you need those integrations; they are intentionally not bundled into the app.

## Project layout

- `main.py` — application entry point and asynchronous controller
- `ui/hud.py` — animated desktop control surface
- `core/` — AI, memory, reminders, calendar, and project paths
- `modules/desktop.py` — allow-listed Windows and browser actions
- `data/` — local SQLite memory and reminder data (created on first run)

## Security notes

Your credentials and local data are intentionally excluded from source changes and packaging. If a credential was ever committed or shared, revoke or rotate it with the provider immediately.
