# Aether Lite — Changelog

All notable changes to this project are documented here.

---

## [Unreleased]

### Planned
- Model selector dropdown per session
- Pinned memory panel
- Export session as Markdown

---

## [1.2.0] — 2026-10-16

### Added
- **Reasoning effort selector** — choose Low / Medium / High effort per session
- **Session memory recall** — `REMEMBER:` facts persist across sessions and are included in context
- **Smooth auto-scroll** — messages animate into view; scroll lock disengages on manual scroll
- **`/btw` prompt queueing** — prefix a message with `/btw` to queue it without triggering a response
- **Shared memory panel** — view and edit persisted facts in the sidebar
- **`/cost` command** — display token count and turn duration metrics
- **`/clear` command** — clear current session messages and reset context

### Changed
- Context window increased from 8 → 10 messages
- `MAX_MSG_CHARS` tunable via constant (default 1500)
- Idle watchdog now logs the exact timeout duration in the error message

### Fixed
- Claude proxy mode now correctly forwards API key when routing via SSH
- Parser no longer drops last line of `agy` output if it lacks a trailing newline
- App Nap prevention now correctly keeps activity even when window is behind others

---

## [1.1.0] — 2026-10-14

### Added
- **Failover backup** — automatic `.backup-YYYYMMDD-HHMMSS/` snapshot before risky changes
- **`api_engineer.py`** — built-in OpenAI-compatible API client (no extra CLI needed)
- **Ollama support** — point `base_url` at `http://localhost:11434/v1` for local models
- **OpenRouter support** — use any model via `https://openrouter.ai/api/v1`
- **`/plan` command** — force plan mode inline without switching the session mode
- **`/help` command** — show built-in reference

### Changed
- `run-v2.sh` added for launching the v2 IDE (`v2/ide.py`)
- SSH host config moved from a flat list to objects with `id`, `label`, `user`, `port`, `identity`

### Fixed
- Fixed race condition where two engineers could both claim the same session turn
- Orchestrator now correctly resets failure count after 1 hour of clean responses

---

## [1.0.0] — 2026-10-05

### Initial Release

- **Liquid Glass UI** — single-file `ui.html` with macOS-native frosted glass aesthetics
- **Three built-in engineers** — Claude (claude_cli), Gemini (antigravity_cli), ChatGPT (antigravity_cli)
- **Orchestrator** — classify/assess/choose_lead routing with availability tracking
- **SQLite persistence** — sessions, messages, shared memory in `~/.aether-lite/lite.db`
- **macOS integration** — pywebview WKWebView, Dock icon, Edit menu, App Nap prevention
- **SSH remote execution** — run any engineer on a remote host transparently
- **IBM Bob support** — `bob_cli` provider with Docker image fallback
- **Shell commands** — `/shell <cmd>` runs bash in the session's working directory
- **Live tool cards** — tool invocations shown as expandable cards in chat
- **Watchdog** — idle engineer detection and automatic reassignment
- **Outage detection** — quota/auth error parsing with timed backoff
- **Context menu** — right-click in chat for Copy/Select All
- **Dark / Light mode** — follows macOS system preference
