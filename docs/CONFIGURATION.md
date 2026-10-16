# Aether Lite — Configuration Reference

All runtime configuration lives in `~/.aether-lite/` (created automatically on first run).

---

## File Locations

| File | Purpose | Editable |
|---|---|---|
| `~/.aether-lite/config.json` | Engineers, SSH hosts, UI preferences | ✅ Yes |
| `~/.aether-lite/secrets.json` | API keys (chmod 0600) | ✅ Via UI only |
| `~/.aether-lite/lite.db` | SQLite — sessions, messages, memory | 🔧 Internal |
| `~/.aether-lite/run.pid` | PID file for single-instance enforcement | 🔧 Internal |
| `~/.aether-lite/exit.log` | Exit codes from run.sh | 🔧 Internal |

---

## config.json — Full Schema

```json
{
  "engineers": [ ... ],   // array of engineer objects (see below)
  "ssh": [ ... ],         // array of SSH host objects (see below)
  "auto_memory": true,    // persist REMEMBER: facts across sessions (default: true)
  "theme": "system"       // "light" | "dark" | "system" (follows macOS)
}
```

---

## Engineer Object

```json
{
  "id":       "claude",
  "name":     "Claude",
  "provider": "claude_cli",
  "command":  "claude",
  "model":    "claude-sonnet-4-5",
  "role":     "Principal Software Engineer",
  "color":    "#e8825f",
  "avatar":   "✳",
  "args":     "",
  "key_env":  "ANTHROPIC_API_KEY",
  "base_url": ""
}
```

### Field Descriptions

| Field | Default | Notes |
|---|---|---|
| `id` | — | Must be unique; lowercase, no spaces |
| `name` | — | Display name in chat bubbles |
| `provider` | — | See [Provider Types](#provider-types) |
| `command` | — | Binary name or absolute path |
| `model` | `""` | Blank = provider default |
| `role` | `""` | Shown in engineer tooltip |
| `color` | `#888` | Any valid hex colour |
| `avatar` | `?` | Single glyph/emoji |
| `args` | `""` | Appended to command after standard flags |
| `key_env` | provider default | Custom env var for API key |
| `base_url` | `""` | `openai_api` only: e.g. `http://localhost:11434/v1` |

---

## Provider Types

| Value | Binary | Key Env Variable |
|---|---|---|
| `claude_cli` | `claude` | `ANTHROPIC_API_KEY` |
| `antigravity_cli` | `agy` | `GEMINI_API_KEY` |
| `openai_api` | *(built-in HTTP)* | `AETHER_API_KEY` |
| `bob_cli` | `bob` | `BOBSHELL_API_KEY` |
| `custom` | *(your binary)* | `key_env` field |

---

## SSH Host Object

```json
{
  "id":       "prod-server",
  "label":    "Production VM",
  "host":     "10.0.0.5",
  "user":     "ubuntu",
  "port":     22,
  "identity": "~/.ssh/id_ed25519"
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | ✅ | Unique identifier |
| `label` | ✅ | Display name |
| `host` | ✅ | Hostname or IP |
| `user` | ✅ | SSH username |
| `port` | | Default: `22` |
| `identity` | | Path to SSH private key |

---

## secrets.json — Schema

This file is managed exclusively by the Aether Lite UI. Do not edit manually unless you know what you are doing. It is stored with mode `0600`.

```json
{
  "ANTHROPIC_API_KEY":  "sk-ant-...",
  "GEMINI_API_KEY":     "AIza...",
  "AETHER_API_KEY":     "sk-...",
  "BOBSHELL_API_KEY":   "...",
  "MY_CUSTOM_VAR":      "..."
}
```

Keys are passed to engineer subprocesses as environment variables. They are never written to `config.json`, logged, or sent to the UI.

---

## Session Settings

Each chat session stores its own settings (persisted in `sessions.settings` JSON column):

| Setting | Default | Description |
|---|---|---|
| `mode` | `"chat"` | `"chat"` \| `"plan"` \| `"edit"` \| `"auto"` |
| `cwd` | `$HOME` | Working directory for shell commands and file operations |
| `active_engs` | all | Array of engineer IDs active in this session |
| `target` | `null` | SSH host ID for remote execution |

---

## Environment Variables (app.py)

These can be set before launching to override defaults:

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Used if not set in secrets.json |
| `GEMINI_API_KEY` | — | Used if not set in secrets.json |
| `AETHER_API_KEY` | — | Used if not set in secrets.json |
| `BOBSHELL_API_KEY` | — | Used if not set in secrets.json |

---

## Tuning Constants (app.py)

These require editing `app.py` directly:

```python
CONTEXT_MESSAGES   = 10    # how many past messages to include in each prompt
MAX_MSG_CHARS      = 1500  # max chars kept per message in context window
IDLE_LIMIT         = {API: 240}  # seconds before API engineer is killed (no output)
IDLE_LIMIT_DEFAULT = 900         # seconds before CLI engineer is killed
FAST_AGY_MODEL     = "gemini-3.8-flash-medium"  # default model for quick/auto routing
```

---

## Modes

| Mode | Description | Multi-engineer? |
|---|---|---|
| `chat` | Conversational; routes to one best engineer | No |
| `plan` | Generates a step-by-step plan before acting | No |
| `edit` | File-editing focus; appends `--edit` to supported CLIs | No |
| `auto` | Orchestrator decides — may use multiple engineers in sequence | Yes |

---

## Default Engineers (out of the box)

```json
[
  {
    "id": "claude", "name": "Claude", "provider": "claude_cli",
    "command": "claude", "model": "haiku",
    "role": "Principal Software Engineer", "color": "#e8825f", "avatar": "✳"
  },
  {
    "id": "gemini", "name": "Gemini", "provider": "antigravity_cli",
    "command": "agy", "model": "",
    "role": "Senior Developer & Research Engineer", "color": "#5ab8f5", "avatar": "✦"
  },
  {
    "id": "chatgpt", "name": "ChatGPT", "provider": "antigravity_cli",
    "command": "agy", "model": "gpt-oss-120b-medium",
    "role": "Senior Software Architect", "color": "#35c9a0", "avatar": "◎"
  }
]
```

---

## Resetting Configuration

```bash
# Reset config to defaults (keeps DB and secrets)
rm ~/.aether-lite/config.json
# Full reset (wipes all sessions and keys too)
rm -rf ~/.aether-lite/
```
