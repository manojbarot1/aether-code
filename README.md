# 🔮 Aether Lite

[![Python](https://img.shields.io/badge/Python-3.11%2B-3393CC?logo=python&logoColor=white)](https://python.org)
[![macOS](https://img.shields.io/badge/macOS-Ventura%2B-black?logo=apple)](https://apple.com/macos)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Liquid Glass UI](https://img.shields.io/badge/UI-Liquid%20Glass-8a2be2.svg)](#)

**A native macOS desktop team-chat console for AI engineers — Liquid Glass UI, multi-engine orchestration, live tool observability.**

---

## What is Aether Lite?

Aether Lite is a **pywebview desktop app** that wraps a Liquid-Glass chat UI around any combination of AI coding CLIs:

- **Claude Code** (`claude`) — Anthropic's agentic coding CLI
- **Antigravity** (`agy`) — multi-model CLI supporting Gemini, GPT, Claude
- **IBM Bob** (`bob`) — IBM's internal AI coding assistant
- **Any OpenAI-compatible API** — OpenAI, Ollama, LM Studio, OpenRouter

Engineers are configured in `~/.aether-lite/config.json`. A built-in orchestrator routes each prompt to the best available engineer, streams output in real time, and auto-recovers from quota/auth failures.

---

## Features

| Feature | Description |
|---|---|
| 🔮 **Liquid Glass UI** | Frosted glass design, ambient light orbs, dark/light mode, specular rim lighting |
| 🧠 **Multi-engineer orchestration** | Routes prompts by capability, speed, and reliability |
| ⚡ **Live streaming** | Tool invocations and text stream token-by-token via pywebview JS bridge |
| 🔀 **Four modes** | Chat · Plan · Edit · Auto |
| 💾 **Persistent sessions** | SQLite-backed sessions, messages, shared memory |
| 🖥️ **SSH remote execution** | Run any engineer on a remote Linux/Mac host |
| 📋 **Session memory** | `REMEMBER:` facts persist across sessions |
| 🛡️ **Outage detection** | Quota/auth errors auto-pause an engineer; work shifts to others |
| 🍎 **macOS native** | WKWebView, Dock icon, Edit menu (⌘C/⌘V/⌘Z), App Nap prevention |

---

## Quick Start

```bash
git clone https://github.com/manojbarot1/aether-code.git
cd aether-code

# Create virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install pywebview pillow pyobjc

# Launch
./run.sh
```

On first launch, open **Settings (⚙)** and paste your API key for any engineer to get started.

→ Full setup guide: [docs/ADDING_ENGINEERS.md](docs/ADDING_ENGINEERS.md)

---

## File Structure

```
aether-lite/
├── app.py               # Main app, JS API bridge, engineer spawner
├── orchestrate.py       # Routing brain — classify, assess, choose_lead
├── api_engineer.py      # Built-in OpenAI-compatible API client
├── freeport.py          # Port utility
├── ui.html              # Single-file Liquid Glass UI (HTML + CSS + JS, no build step)
├── ctxmenu.js           # Context menu for the webview
├── run.sh               # Launch: .venv/bin/python app.py
├── run-v2.sh            # Launch: v2/ide.py
├── assets/
│   ├── AetherLite.icns  # macOS Dock icon
│   └── icon_1024.png    # Source PNG
├── v2/                  # v2 IDE (in development)
└── docs/
    ├── ARCHITECTURE.md      # Full architecture & data-flow diagrams
    ├── ADDING_ENGINEERS.md  # Step-by-step guide to add AI engineers
    ├── CONFIGURATION.md     # Complete config reference
    └── CHANGELOG.md         # Version history
```

Runtime data (not in repo):
```
~/.aether-lite/
├── lite.db        # SQLite: sessions, messages, memory
├── config.json    # Engineers + SSH hosts
└── secrets.json   # API keys (mode 0600)
```

---

## Supported Providers

| Provider | Binary | Auth Variable | Notes |
|---|---|---|---|
| `claude_cli` | `claude` | `ANTHROPIC_API_KEY` | Full agentic tools support |
| `antigravity_cli` | `agy` | `GEMINI_API_KEY` | Gemini, GPT, Claude via one CLI |
| `openai_api` | *(built-in)* | `AETHER_API_KEY` | OpenAI, Ollama, OpenRouter, LM Studio |
| `bob_cli` | `bob` | `BOBSHELL_API_KEY` | IBM Bob; Docker fallback on macOS |
| `custom` | *(any binary)* | `key_env` field | Reads prompt on stdin, writes JSON on stdout |

---

## Keyboard Shortcuts & Slash Commands

| Input | Action |
|---|---|
| `Enter` | Send prompt |
| `Shift + Enter` | Insert newline |
| `Esc` | Stop current engineer turn |
| `/plan <task>` | Force plan mode for this message |
| `/shell <cmd>` | Run a bash command in the session's working directory |
| `/btw <note>` | Queue a note without triggering a response |
| `/cost` | Show token counts and turn duration |
| `/clear` | Clear session messages |
| `/help` | Show built-in reference |

---

## Adding Engineers

→ **Complete step-by-step guide:** [docs/ADDING_ENGINEERS.md](docs/ADDING_ENGINEERS.md)

Quick example — add Ollama (local, no API key):

```json
{
  "id": "ollama",
  "name": "Llama 3.2",
  "provider": "openai_api",
  "command": "",
  "model": "llama3.2",
  "base_url": "http://localhost:11434/v1",
  "role": "Local Engineer",
  "color": "#a78bfa",
  "avatar": "⬡",
  "args": ""
}
```

---

## Architecture

```
ui.html (WKWebView)
    │  pywebview JS API bridge
    ▼
app.py  ──► orchestrate.py (route to best engineer)
    │
    ├── subprocess: claude / agy / bob
    └── HTTP: api_engineer.py → OpenAI / Ollama / OpenRouter
```

→ Full diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Requirements

| Requirement | Version |
|---|---|
| macOS | Ventura 13+ |
| Python | 3.11+ |
| pywebview | 5.x or 6.x |
| pyobjc | 10+ |

At least one AI engineer CLI must also be installed. See [docs/ADDING_ENGINEERS.md](docs/ADDING_ENGINEERS.md).

---

## License

MIT © 2026 Manoj Barot
