# Aether Lite — Architecture

> **Aether Lite** is a native macOS desktop application: a lightweight, local team-chat console
> that routes your prompts to one or more AI engineer CLIs (Claude Code, Antigravity/`agy`,
> IBM Bob, OpenAI-compatible APIs) and surfaces their output in a Liquid-Glass UI window.

---

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    macOS Desktop Process                    │
│                                                             │
│  ┌─────────────────┐        ┌──────────────────────────┐   │
│  │  pywebview      │◄──────►│  Python Backend (app.py) │   │
│  │  WKWebView      │  JS    │  (JS API bridge)         │   │
│  │  (Liquid Glass  │  API   │                          │   │
│  │   UI / ui.html) │        │  orchestrate.py          │   │
│  └─────────────────┘        │  api_engineer.py         │   │
│                             │  freeport.py             │   │
│                             └────────────┬─────────────┘   │
│                                          │ subprocess       │
│                     ┌────────────────────┼──────────────┐  │
│                     │                    │              │  │
│              ┌──────▼──────┐   ┌─────────▼────┐  ┌─────▼─┐│
│              │ claude CLI  │   │  agy CLI     │  │  bob  ││
│              │ (Anthropic) │   │ (Antigravity)│  │  CLI  ││
│              └──────┬──────┘   └─────────┬────┘  └─────┬─┘│
│                     │                    │              │  │
└─────────────────────┼────────────────────┼──────────────┼──┘
                      │                    │              │
                ┌─────▼──────┐   ┌─────────▼────┐  ┌─────▼──┐
                │ Anthropic  │   │ Google Gemini │  │  IBM   │
                │  API       │   │  / OpenAI API │  │  Bob   │
                └────────────┘   └──────────────┘  └────────┘
```

---

## Component Breakdown

### `app.py` — Main Application & JS Bridge

The single entry point. Responsibilities:

| Area | Detail |
|---|---|
| **DB init** | Creates `~/.aether-lite/lite.db` (SQLite) — sessions, messages, shared memory |
| **Config load** | Reads `~/.aether-lite/config.json` (engineers list, SSH hosts) |
| **Secrets** | Reads `~/.aether-lite/secrets.json` (API keys, chmod 600, never sent to UI) |
| **JS API** | `class Api` exposes all backend methods to `ui.html` via pywebview bridge |
| **Engineer spawn** | `Api.run()` — spawns CLI subprocess per engineer, streams output back via `emit()` |
| **Shell** | `Api._shell()` — runs raw bash commands, streams stdout/stderr to the UI |
| **macOS integration** | Dock icon, Edit menu (Undo/Redo/Cut/Copy/Paste), App Nap prevention |

Key constants in `app.py`:

```python
MODES           = ("chat", "plan", "edit", "auto")
CONTEXT_MESSAGES = 10       # messages sent as context per turn
MAX_MSG_CHARS   = 1500      # characters kept per message in context
IDLE_LIMIT      = {API: 240}         # seconds before API engineer is killed
IDLE_LIMIT_DEFAULT = 900             # seconds before CLI engineer is killed
```

---

### `ui.html` — Liquid Glass Frontend

Self-contained single-file UI (HTML + CSS + JavaScript). No build step.

| Section | Description |
|---|---|
| **CSS variables** | Liquid Glass design system — `--glass`, `--glass-rim`, `--ambient-*`, dark/light mode |
| **Layout** | Two-column grid: `#side` (session list + engineers) + `#main` (chat) |
| **JS bridge** | Calls `window.pywebview.api.<method>()` for all data operations |
| **SSE-like streaming** | `Api.emit()` in Python → `window.__aetherEvent()` in JS |
| **Modes** | Segmented control: Chat / Plan / Edit / Auto |
| **Settings panel** | Add/edit/remove engineers, SSH hosts, API keys inline |

---

### `orchestrate.py` — Routing Brain

Decides *which* engineer receives a given prompt and how much effort to apply.

```
classify(text)     → "question" | "work"
assess(text)       → QUICK | STANDARD | DEEP
choose_lead(...)   → engineer id (capability match + reliability score)
mark_down(eid, …)  → temporarily suppress a failing engineer (quota, auth, outage)
detect_outage(text)→ parse engineer output for session-limit / auth errors
```

---

### `orchestrate.py` — Engineer Selection Logic

```
Priority order for choose_lead():
  1. Engineer is not marked down (mark_down / is_down)
  2. Capability match: "research" → Gemini; "code" → Claude; "arch" → ChatGPT; default rotates
  3. Mode speed: QUICK → fast model (gemini-3.8-flash-medium)
  4. Recent reliability: engineers with recent failures are deprioritised
```

---

### `api_engineer.py` — OpenAI-Compatible API Engineer

A standalone script run as a subprocess. Accepts a prompt on stdin, streams JSON events on stdout:

```json
{"type": "text",   "text": "..."}
{"type": "thought","text": "..."}
{"type": "result", "ok": true, "error": null}
```

Supports: OpenAI, Ollama, LM Studio, FreeLLMAPI, OpenRouter, any OpenAI-compatible endpoint.

---

### `orchestrate.py` — Outage Detection Patterns

| Pattern | Action | Duration |
|---|---|---|
| Session limit / quota / rate-limit | Mark engineer down | 30 min |
| Auth failed / not logged in / expired key | Mark engineer down | 10 min |

---

## Data Flow — Single Prompt Turn

```
User types prompt → ui.html
  │
  ▼
window.pywebview.api.run(sid, prompt, engs, mode, ...)
  │
  ▼
app.py: Api.run()
  │  chooses lead engineer via orchestrate.choose_lead()
  │
  ├─► _run_engineer(sid, eng, prompt)
  │     │  spawns: subprocess (claude / agy / bob / api_engineer.py)
  │     │  stdin: wrapped prompt (wrap_stdin)
  │     │  stdout: parsed line-by-line (Parser class)
  │     │
  │     ├── Parser emits: text / thought / tool / result events
  │     │
  │     └── emit({"t":"text"|"thought"|"tool"|"end", ...})
  │              │
  │              ▼
  │         window.__aetherEvent(ev) in ui.html
  │         → appends to chat, shows tool cards
  │
  └─► _store_assistant(sid, mid, author, text, meta) → SQLite
```

---

## Database Schema (`~/.aether-lite/lite.db`)

```sql
CREATE TABLE sessions (
  id      TEXT PRIMARY KEY,
  title   TEXT,
  created REAL,
  updated REAL,
  settings TEXT,   -- JSON: {mode, cwd, active_engs, ...}
  summary TEXT DEFAULT '',
  archived INTEGER DEFAULT 0
);

CREATE TABLE messages (
  id         TEXT PRIMARY KEY,
  session_id TEXT,
  ts         REAL,
  role       TEXT,   -- 'user' | 'assistant' | 'shell' | 'system'
  author     TEXT,   -- engineer name or 'You' / 'Shell' / 'Aether'
  content    TEXT,
  meta       TEXT    -- JSON: {tools, error, eid, thoughts, dur, phase, ...}
);

CREATE TABLE memory (
  id     TEXT PRIMARY KEY,
  ts     REAL,
  text   TEXT,
  source TEXT   -- engineer name that wrote the REMEMBER: fact
);
```

---

## File Layout

```
aether-lite/
├── app.py               # Main application, JS API bridge, engineer spawner
├── orchestrate.py       # Routing brain — classify, assess, choose_lead, outage
├── api_engineer.py      # OpenAI-compatible API engineer subprocess
├── freeport.py          # Port utility (used by aserve.py)
├── aserve.py            # Lightweight HTTP dev server helper
├── ui.html              # Single-file Liquid Glass UI (HTML+CSS+JS)
├── ctxmenu.js           # Context menu helper for the webview
├── run.sh               # Launch script (venv python app.py)
├── run-v2.sh            # Launch script for v2 IDE (v2/ide.py)
├── assets/
│   ├── AetherLite.icns  # macOS app icon
│   └── icon_1024.png    # PNG source icon
├── css/
│   └── style.css        # Additional site styles (landing pages)
├── js/                  # Additional scripts (landing pages)
├── v2/
│   ├── ide.py           # v2 IDE entry point
│   └── web/             # v2 web assets
├── docs/
│   ├── ARCHITECTURE.md      ← this file
│   ├── ADDING_ENGINEERS.md  # Step-by-step guide to add AI engineers
│   ├── CONFIGURATION.md     # Full config reference
│   └── CHANGELOG.md         # Version history
└── ~/.aether-lite/          # Runtime data (not in repo)
    ├── lite.db              # SQLite: sessions, messages, memory
    ├── config.json          # Engineers + SSH hosts config
    └── secrets.json         # API keys (chmod 600, gitignored)
```

---

## Provider Types

| `provider` value | Underlying binary | Auth |
|---|---|---|
| `claude_cli` | `claude` (Anthropic Claude Code) | `ANTHROPIC_API_KEY` |
| `antigravity_cli` | `agy` (Antigravity / Gemini / GPT) | `GEMINI_API_KEY` |
| `bob_cli` | `bob` (IBM Bob) or Docker image | `BOBSHELL_API_KEY` |
| `openai_api` | `api_engineer.py` (any OpenAI endpoint) | `AETHER_API_KEY` |
| `custom` | Any executable you provide | custom `key_env` var |

---

## Security Notes

- API keys are stored in `~/.aether-lite/secrets.json` (mode 0600), never in `config.json`
- The pywebview window has no `allow_downloads`, no external navigation
- `subprocess` calls use `start_new_session=True` so killing the process group is clean
- SSH connections use the system's `ssh` binary; no passwords are stored — key auth only
