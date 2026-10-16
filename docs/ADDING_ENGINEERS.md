# Adding AI Engineers to Aether Lite

> This guide walks you through every way to add a new AI engineer to Aether Lite —
> from the UI settings panel to editing `config.json` by hand, including all provider types,
> API key setup, and SSH remote engineers.

---

## Table of Contents

1. [Quick Overview — What is an Engineer?](#1-quick-overview--what-is-an-engineer)
2. [Add an Engineer via the UI](#2-add-an-engineer-via-the-ui)
3. [Add an Engineer via config.json](#3-add-an-engineer-via-configjson)
4. [Provider Types Reference](#4-provider-types-reference)
5. [Step-by-Step: Add Anthropic Claude](#5-step-by-step-add-anthropic-claude)
6. [Step-by-Step: Add Google Gemini (via agy)](#6-step-by-step-add-google-gemini-via-agy)
7. [Step-by-Step: Add ChatGPT / OpenAI API](#7-step-by-step-add-chatgpt--openai-api)
8. [Step-by-Step: Add IBM Bob](#8-step-by-step-add-ibm-bob)
9. [Step-by-Step: Add Ollama (local LLM)](#9-step-by-step-add-ollama-local-llm)
10. [Step-by-Step: Add a Custom CLI Engineer](#10-step-by-step-add-a-custom-cli-engineer)
11. [Step-by-Step: Add a Remote SSH Engineer](#11-step-by-step-add-a-remote-ssh-engineer)
12. [Engineer Fields Reference](#12-engineer-fields-reference)
13. [API Keys Reference](#13-api-keys-reference)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Quick Overview — What is an Engineer?

An **engineer** in Aether Lite is an entry in `~/.aether-lite/config.json` that describes:

- **Which CLI binary or API** to use (Claude Code, `agy`, `bob`, OpenAI endpoint, or any custom command)
- **Role and persona** shown in the chat UI
- **Which model** to request
- **Which API key** to pass as an environment variable

When you send a prompt, Aether Lite's orchestrator picks the best available engineer, spawns
it as a subprocess (or calls the API), and streams its output back into the chat.

---

## 2. Add an Engineer via the UI

The fastest way for most users.

1. **Open Aether Lite** — run `./run.sh` from your `aether-lite` directory.
2. **Click the ⚙ gear icon** in the bottom-left of the sidebar to open **Settings**.
3. **Scroll to the Engineers section** and click **+ Add Engineer**.
4. Fill in the fields:
   - **Name** — display name in chat (e.g. `Gemini Pro`)
   - **Provider** — dropdown: `claude_cli`, `antigravity_cli`, `openai_api`, `bob_cli`, `custom`
   - **Command** — the binary to run (e.g. `claude`, `agy`, `bob`)
   - **Model** — model name to pass to the CLI (leave blank for provider default)
   - **Role** — short description shown under the engineer's name (e.g. `Senior Architect`)
   - **Avatar** — a single emoji or unicode glyph (e.g. `✦`)
   - **Color** — hex colour for the engineer's chat bubble (e.g. `#5ab8f5`)
5. **Click Save**.
6. Go to **Settings → API Keys** and paste the API key for the engineer's provider.
7. The engineer is immediately available — send a prompt to test.

---

## 3. Add an Engineer via config.json

For scripting, deployment, or bulk changes.

**Location:** `~/.aether-lite/config.json`

Open in any editor:

```bash
nano ~/.aether-lite/config.json
# or
code ~/.aether-lite/config.json
```

Add a new object to the `"engineers"` array:

```json
{
  "engineers": [
    {
      "id": "my-engineer",
      "name": "My Engineer",
      "provider": "antigravity_cli",
      "command": "agy",
      "model": "gemini-2.5-pro",
      "role": "Senior Data Engineer",
      "color": "#f5a524",
      "avatar": "◈",
      "args": ""
    }
  ]
}
```

Save the file, then **restart Aether Lite** for the change to take effect.

> **Tip:** You can also set `"key_env": "MY_CUSTOM_VAR"` to use a non-standard environment
> variable for the API key instead of the provider default.

---

## 4. Provider Types Reference

| `provider` | Binary | What it does |
|---|---|---|
| `claude_cli` | `claude` | Anthropic Claude Code CLI — full agent with tools |
| `antigravity_cli` | `agy` | Antigravity CLI — Gemini, GPT-4o, Claude via one binary |
| `openai_api` | *(built-in)* | Direct HTTP to any OpenAI-compatible endpoint |
| `bob_cli` | `bob` | IBM Bob CLI — or Docker image if not installed |
| `custom` | *(your binary)* | Any executable that reads prompt on stdin, writes JSON on stdout |

---

## 5. Step-by-Step: Add Anthropic Claude

### Prerequisites

```bash
# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code
# or
pip install claude-code

# Verify
claude --version
```

### Get Your API Key

1. Go to [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key
2. Copy the key (starts with `sk-ant-…`)

### Add to Aether Lite

**Option A — UI:**
1. Settings → Engineers → + Add Engineer
2. Name: `Claude`, Provider: `claude_cli`, Command: `claude`, Model: `claude-sonnet-4-5`
3. Settings → API Keys → Anthropic → paste your key → Save

**Option B — config.json:**
```json
{
  "id": "claude",
  "name": "Claude",
  "provider": "claude_cli",
  "command": "claude",
  "model": "claude-sonnet-4-5",
  "role": "Principal Software Engineer",
  "color": "#e8825f",
  "avatar": "✳",
  "args": ""
}
```

Then set the key:
```bash
# The key is stored in secrets.json, not as a shell variable
# Use the Aether Lite UI: Settings → API Keys → Anthropic
# Or set it in your shell for the current session:
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Available Models

| Model | Speed | Best For |
|---|---|---|
| `claude-haiku-4-5` | ⚡ Fast | Quick questions, boilerplate |
| `claude-sonnet-4-5` | ⚖ Balanced | Code review, implementation |
| `claude-opus-4-5` | 🧠 Deep | Complex architecture, reasoning |

---

## 6. Step-by-Step: Add Google Gemini (via agy)

### Prerequisites

```bash
# Install Antigravity (agy) CLI
pip install antigravity
# or via brew
brew install antigravity

# Verify
agy --version
```

### Get Your API Key

1. Go to [aistudio.google.com](https://aistudio.google.com) → Get API Key
2. Copy the key (starts with `AIza…`)

### Add to Aether Lite

**config.json:**
```json
{
  "id": "gemini",
  "name": "Gemini",
  "provider": "antigravity_cli",
  "command": "agy",
  "model": "gemini-2.5-flash",
  "role": "Senior Developer & Research Engineer",
  "color": "#5ab8f5",
  "avatar": "✦",
  "args": ""
}
```

Set the key: **Settings → API Keys → Gemini** → paste → Save

### Available Models

| Model | Speed | Best For |
|---|---|---|
| `gemini-3.8-flash-medium` | ⚡ Fast (default) | Most tasks |
| `gemini-2.5-flash` | ⚡ Fast | Quick responses |
| `gemini-2.5-pro` | 🧠 Deep | Long-context, complex reasoning |

---

## 7. Step-by-Step: Add ChatGPT / OpenAI API

### Prerequisites

No CLI needed — Aether Lite has a built-in OpenAI-compatible HTTP client (`api_engineer.py`).

### Get Your API Key

1. Go to [platform.openai.com](https://platform.openai.com) → API Keys → Create new secret key
2. Copy the key (starts with `sk-…`)

### Add to Aether Lite

**config.json:**
```json
{
  "id": "chatgpt",
  "name": "ChatGPT",
  "provider": "openai_api",
  "command": "",
  "model": "gpt-4o",
  "role": "Senior Software Architect",
  "color": "#35c9a0",
  "avatar": "◎",
  "args": "",
  "base_url": "https://api.openai.com/v1"
}
```

Set the key: **Settings → API Keys → OpenAI** → paste → Save

The `base_url` field tells the built-in client where to send requests. Change it to point at
Ollama, LM Studio, OpenRouter, or any other compatible endpoint.

### Using OpenRouter (multiple models, one key)

```json
{
  "id": "openrouter-llama",
  "name": "Llama 3.1",
  "provider": "openai_api",
  "command": "",
  "model": "meta-llama/llama-3.1-405b-instruct",
  "base_url": "https://openrouter.ai/api/v1",
  "key_env": "OPENROUTER_API_KEY",
  ...
}
```

---

## 8. Step-by-Step: Add IBM Bob

### Prerequisites

**Option A — Native install (Linux only):**
Follow the IBM Bob installation guide at your IBM internal portal.

**Option B — Docker (macOS recommended):**
```bash
# Pull the aether-ai-team image that bundles bob
docker pull localhost/aether-ai-team:latest
# or build it
cd aether-ai-team && docker compose up -d
```

### Add to Aether Lite

**config.json:**
```json
{
  "id": "bob",
  "name": "IBM Bob",
  "provider": "bob_cli",
  "command": "bob",
  "model": "",
  "role": "IBM Platform Engineer",
  "color": "#0f62fe",
  "avatar": "◆",
  "args": ""
}
```

Set the key: **Settings → API Keys → Bob** → paste `BOBSHELL_API_KEY` → Save

Aether Lite automatically falls back to the Docker image (`localhost/aether-ai-team:latest`)
if `bob` is not installed natively on macOS.

---

## 9. Step-by-Step: Add Ollama (local LLM)

Run models 100% locally with no API key.

### Prerequisites

```bash
# Install Ollama
brew install ollama
# Pull a model
ollama pull llama3.2
ollama pull codestral
# Start Ollama server (runs on http://localhost:11434)
ollama serve
```

### Add to Aether Lite

```json
{
  "id": "ollama-llama",
  "name": "Llama 3.2",
  "provider": "openai_api",
  "command": "",
  "model": "llama3.2",
  "base_url": "http://localhost:11434/v1",
  "key_env": "",
  "role": "Local Engineer",
  "color": "#a78bfa",
  "avatar": "⬡",
  "args": ""
}
```

No API key needed — leave the key field blank or set `"key_env": ""`.

> **Note:** Ollama serves plain HTTP. Use `http://` not `https://` in `base_url`.

---

## 10. Step-by-Step: Add a Custom CLI Engineer

Any executable that reads a prompt on stdin and writes JSON events on stdout can be an engineer.

### Required Output Protocol

Your binary must write newline-delimited JSON to stdout:

```json
{"type": "text",    "text": "partial response text..."}
{"type": "thought", "text": "internal reasoning..."}
{"type": "result",  "ok": true,  "error": null}
```

On error:
```json
{"type": "result", "ok": false, "error": "Something went wrong"}
```

### Add to Aether Lite

**config.json:**
```json
{
  "id": "my-custom-ai",
  "name": "My AI",
  "provider": "custom",
  "command": "/usr/local/bin/my-ai-cli",
  "model": "my-model-v1",
  "role": "Custom AI Assistant",
  "color": "#f59e0b",
  "avatar": "★",
  "args": "--verbose",
  "key_env": "MY_AI_API_KEY"
}
```

Set the key:
```bash
export MY_AI_API_KEY="your-key-here"
# Or add it to ~/.aether-lite/secrets.json via the UI
```

The engineer receives the prompt via stdin and must exit 0 on success.

---

## 11. Step-by-Step: Add a Remote SSH Engineer

Run AI agents on a remote server (e.g. a Linux VM with GPU, a cloud instance, or an IBM i box).

### Prerequisites

- SSH key authentication set up to the remote host (`ssh-copy-id user@host`)
- The target CLI (`claude`, `agy`, `bob`) installed on the remote machine
- The remote host added to `~/.ssh/config` (optional but recommended)

### Add an SSH Host

**Via UI:** Settings → SSH Hosts → + Add Host
- **Label**: `my-server`
- **Host**: `192.168.1.100` or `myserver.example.com`
- **User**: `ubuntu`
- **Port**: `22`
- **Identity file**: `~/.ssh/id_ed25519`

**Via config.json:**
```json
{
  "ssh": [
    {
      "id": "my-server",
      "label": "My Server",
      "host": "192.168.1.100",
      "user": "ubuntu",
      "port": 22,
      "identity": "~/.ssh/id_ed25519"
    }
  ]
}
```

### Assign an Engineer to Run Remotely

In the session settings panel (the ⚙ icon in the chat header), set the **Target** dropdown
to the SSH host. All engineer commands in that session will be proxied over SSH.

Aether Lite builds the SSH command as:
```bash
ssh -i <identity> -p <port> -o StrictHostKeyChecking=accept-new <user>@<host> \
  "cd <remote_cwd> && <engineer_command> <args>"
```

---

## 12. Engineer Fields Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✅ | Unique ID (no spaces, lowercase, hyphens OK) |
| `name` | string | ✅ | Display name in chat UI |
| `provider` | string | ✅ | `claude_cli` \| `antigravity_cli` \| `openai_api` \| `bob_cli` \| `custom` |
| `command` | string | ✅ | Executable name or full path (leave blank for `openai_api`) |
| `model` | string | | Model name passed to the CLI (blank = provider default) |
| `role` | string | | Short role description shown in chat |
| `color` | string | | Hex colour for chat bubble (e.g. `#5ab8f5`) |
| `avatar` | string | | Single character/emoji shown next to name |
| `args` | string | | Extra CLI arguments appended after standard flags |
| `key_env` | string | | Custom env variable name for API key (overrides provider default) |
| `base_url` | string | | API base URL for `openai_api` provider |

---

## 13. API Keys Reference

Keys are stored encrypted in `~/.aether-lite/secrets.json` (mode 0600).

| Provider | Default env variable | Where to get the key |
|---|---|---|
| `claude_cli` | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `antigravity_cli` | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| `openai_api` | `AETHER_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `bob_cli` | `BOBSHELL_API_KEY` | IBM internal portal |

To use a different variable name, set `"key_env": "MY_VAR"` in the engineer config and
ensure the key is saved under that name in **Settings → API Keys**.

---

## 14. Troubleshooting

### Engineer shows "Command not found"

The CLI binary is not on `PATH`. Aether Lite extends PATH with:
`~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`, `/bin`

Fix: install the CLI in one of those locations or provide the full absolute path in `command`.

### Engineer shows "not responding (no output for N min)"

The process started but produced no output within the idle timeout:
- CLI engineers: 15 min default
- API engineers: 4 min default

Fix: check the model name, network connectivity, and API key.

### Engineer shows "HTTP 401: Check the API key"

The API key is missing or invalid. Go to **Settings → API Keys** and re-enter it.

### Engineer is grayed out / skipped

The orchestrator marked it down due to a quota limit or auth error. It will auto-recover after:
- Quota/rate-limit: 30 minutes
- Auth error: 10 minutes

You can clear this immediately: **Settings → Engineers → [engineer] → Reset Status**

### Changes to config.json not appearing

Restart Aether Lite. Config is loaded once at startup.

### Multiple engineers replying at the same time

This is by design in `auto` mode — engineers collaborate in parallel. Use `chat` mode for single-engineer responses.
