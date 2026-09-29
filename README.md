# 🔮 Aether Code (`aether-code`)

<p align="center">
  <img src="public/assets/icon.svg" alt="Aether Code Logo" width="96" height="96" />
</p>

<p align="center">
  <strong>Unified AI Agent Coding Console with Apple Liquid Glass Material UI & Real-Time Terminal Observability</strong>
</p>

<p align="center">
  <a href="https://nodejs.org"><img src="https://img.shields.io/badge/Node.js-20%2B-339933?logo=node.js&logoColor=white" alt="Node Version" /></a>
  <a href="https://github.com/manojbarot1/aether-code/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License" /></a>
  <a href="https://github.com/manojbarot1/aether-code"><img src="https://img.shields.io/badge/Zero-Dependencies-success.svg" alt="Zero Dependencies" /></a>
  <a href="https://github.com/manojbarot1/aether-code"><img src="https://img.shields.io/badge/UI-Liquid%20Glass-8a2be2.svg" alt="Liquid Glass UI" /></a>
</p>

---

## 🌟 Highlights

**Aether Code** is a standalone, high-performance GUI and agent console that brings the power of agentic command-line coding into an ultra-modern Apple Liquid Glass interface with full real-time observability.

- 🔮 **Liquid Glass Material UI**: Frosted glassmorphism (`backdrop-filter: blur(28px) saturate(180%)`), dynamic multi-stop mesh backdrops (**Dark Aurora**, **Apple Sonoma**, **Cyber Grid**, **Pearl Light**), organic floating orbs, and specular surface lighting.
- ⚡ **Live Bash Terminal Window**: Every tool invocation and shell command runs in an authentic macOS terminal window (`🔴 🟡 🟢`) with live prompt lines (`user@aether:~$ <cmd>`), real-time execution states (`● RUNNING`), blinking cursors, and full stdout/stderr streams.
- 🧠 **Live Chain-of-Thought**: Model thinking and tool intents are surfaced in real-time as the agent formulates its plan.
- 🔀 **Tri-Engine Switchboard**: One-click toggles and switches between **Google Gemini**, **Anthropic Claude**, and **OpenAI ChatGPT** with dedicated ON/OFF switches.
- 📁 **Smart Session Naming**: Automatically extracts human-readable chat titles directly from your prompts (no cryptic `Session <hash>` labels).
- 🛡️ **Zero External npm Dependencies**: Built with Node.js built-ins (`http`, `sqlite`, `child_process`). Fully offline-ready with bundled `marked.js` and `highlight.js`.
- 🖥️ **Desktop App & Web Ready**: Run as a native-feel desktop app (via Chrome App mode) or access remotely through any browser.

---

## 🚀 Quick Start

### Option 1: One-Click Local Setup (Recommended)

```bash
# 1. Clone repository
git clone https://github.com/manojbarot1/aether-code.git
cd aether-code

# 2. Run one-click installer (sets up desktop entry, permissions, and service)
./install.sh

# 3. Launch application window
aether-code
```

Or run directly using Node:

```bash
npm start
# Server starts at http://localhost:4567
```

---

### Option 2: Docker & Docker Compose

Deploy instantly on any cloud VPS, server, or local Docker environment:

```bash
git clone https://github.com/manojbarot1/aether-code.git
cd aether-code

# Build and start container
docker compose up -d
```

Access the UI at `http://localhost:4567`.

---

### Option 3: Linux Background Service (`systemd`)

Run Aether Code as a persistent user service that starts automatically on boot:

```bash
mkdir -p ~/.config/systemd/user
cat << 'EOF' > ~/.config/systemd/user/aether-code.service
[Unit]
Description=Aether Code Server
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/aether-code
ExecStart=/usr/bin/node server.js
Restart=on-failure
Environment=PORT=4567

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now aether-code.service
```

---

## 🎛️ Tri-Engine Switchboard

Aether Code includes an active switchboard in the top navigation bar:

| Engine | Indicator | Description | Default Model |
| :--- | :---: | :--- | :--- |
| **Google Gemini** | `✦` | Gemini multimodal agent with high reasoning speed | `gemini-3.8-flash-high` |
| **Anthropic Claude** | `✳` | Claude reasoning models for deep code synthesis | `claude-sonnet-4-6` |
| **OpenAI ChatGPT** | `⯀` | GPT models for versatile completions & workflows | `gpt-oss-120b-medium` |

- **Single Click**: Switch your active model to that engine immediately.
- **Toggle Switch**: Turn specific engines ON or OFF to filter available models in the dropdown.

---

## 💻 Live Bash Terminal Observability

Unlike typical chat applications that hide background commands behind loading spinners, Aether Code mounts a real terminal window for each command:

```text
┌── 💻 bash — Bash ────────────────────────────────────────────── [ ✓ EXIT 0 (0.03s) ] ──┐
│                                                                                        │
│  manojb@aether:~$ git status --short                                                  │
│                                                                                        │
│  M  lib/agy-manager.js                                                                │
│  M  public/style.css                                                                  │
│                                                                                        │
│  Status: Process completed with code 0 • Time: 0.03s                                   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎨 Liquid Glass Environments

Click any of the backdrop dots in the top right to change the ambient aesthetic in real time:

- **Dark Aurora**: Deep obsidian base with celestial cyan, purple, and emerald animated mesh lights.
- **Apple Sonoma**: Sunset terracotta, violet, and deep amber warm organic mesh.
- **Cyber Grid**: High-contrast matrix grid with deep neon focus.
- **Pearl Light**: Translucent soft luminescence with frosted highlights.

---

## ⌨️ Shortcuts & Commands

| Shortcut / Command | Action |
| :--- | :--- |
| `Enter` | Run command / Send prompt |
| `Shift + Enter` | Insert new line |
| `Ctrl + N` | Start new session |
| `Esc` | Stop / interrupt active agent generation |
| `/plan <task>` | Formulate a multi-step execution plan |
| `/cost` | View token counts and turn execution metrics |
| `/clear` | Clear current session and start fresh |
| `/help` | Open built-in reference documentation |

---

## 📂 Project Architecture

```text
aether-code/
├── bin/
│   └── aether-code          # Desktop & CLI launcher script
├── lib/
│   ├── agy-manager.js       # Spawns agent turns, streams SSE & watches live thoughts
│   ├── db-reader.js         # Reads sessions, histories, and derives prompt titles
│   └── models.js            # Engine and model discovery service
├── public/
│   ├── assets/              # App icons and vector assets
│   ├── vendor/              # Bundled marked.js & highlight.js (offline ready)
│   ├── index.html           # Liquid Glass UI & SVG filter definitions
│   ├── style.css            # Liquid Glass design system & animations
│   └── app.js               # Client state, SSE parser & terminal renderer
├── server.js                # Zero-dependency HTTP & SSE streaming server
├── install.sh               # One-click desktop installer script
├── Dockerfile               # Production container image
├── docker-compose.yml       # Docker Compose service definition
└── package.json             # NPM package specification
```

---

## ⚙️ Configuration & Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `PORT` | `4567` | Port for the HTTP and SSE server |
| `AETHER_PORT` | `4567` | Port alias used by the desktop launcher |
| `DEFAULT_WORKSPACE`| `$HOME` | Default root folder for file operations |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) © 2026 Manoj Barot.
