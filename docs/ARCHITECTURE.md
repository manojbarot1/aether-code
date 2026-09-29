# 📐 Aether Code — System Architecture & Design

<p align="center">
  <img src="architecture.svg" alt="Aether Code Architecture Diagram" width="100%" />
</p>

## Overview

**Aether Code** is designed around a three-tier decoupled architecture:
1. **Presentation Tier (Client)**: Apple Liquid Glass Material interface, tri-engine switchboard, real-time bash terminal window, and SSE stream consumer.
2. **Server Tier (Node.js Core)**: Zero-dependency runtime handling process pooling, transcript watcher (80ms poll), and SQLite/Brain title resolution.
3. **Engine & Foundation Tier**: The underlying Antigravity CLI subprocess (`agy`) executing tools, recording transcripts, and calling foundation models (Google Gemini, Anthropic Claude, OpenAI ChatGPT).

---

## 🏗️ Component Diagram (Mermaid)

```mermaid
graph TD
    subgraph Client ["Client Presentation Tier (Browser / Chrome App)"]
        UI["Liquid Glass Interface<br/>(Backdrop Blur & Specular Sheen)"]
        Switchboard["Tri-Engine Switchboard<br/>(✦ Gemini | ✳ Claude | ⯀ ChatGPT)"]
        TerminalComp["Live Bash Terminal Window<br/>(● RUNNING -> ✓ EXIT 0)"]
        ThoughtComp["Live Reasoning & Intent Stream"]
        SSEParser["SSE Event Stream Reader"]
    end

    subgraph Server ["Server Tier (Node.js Core :4567)"]
        HTTPServer["server.js (Native HTTP & SSE)"]
        AgyManager["lib/agy-manager.js (Process Pool)"]
        TranscriptWatcher["Background Log Watcher<br/>(transcript_full.jsonl 80ms)"]
        DBReader["lib/db-reader.js<br/>(Prompt Title Extractor)"]
        ModelsReg["lib/models.js (Multi-Engine Registry)"]
    end

    subgraph Agent ["Agent Core & File System"]
        AgyCLI["Antigravity CLI (agy)<br/>--output-format stream-json<br/>--dangerously-skip-permissions"]
        BrainDir["~/.gemini/antigravity-cli/brain/<br/>transcript_full.jsonl"]
        SQLiteDB["conversation_summaries.db"]
        BashTool["Bash Terminal Sandbox"]
    end

    subgraph Models ["Foundation Models"]
        Gemini["Google Gemini 3.8 Flash High"]
        Claude["Anthropic Claude Sonnet 4.6"]
        ChatGPT["OpenAI GPT-OSS 120B"]
    end

    UI --> Switchboard
    Switchboard --> SSEParser
    SSEParser --> TerminalComp
    SSEParser --> ThoughtComp

    UI -- "POST /api/chat" --> HTTPServer
    HTTPServer --> AgyManager
    AgyManager --> AgyCLI
    AgyCLI --> BrainDir
    TranscriptWatcher -- "Tails 80ms" --> BrainDir
    TranscriptWatcher --> AgyManager
    AgyManager -- "SSE Stream" --> HTTPServer
    HTTPServer -- "text/event-stream" --> SSEParser

    DBReader --> SQLiteDB
    DBReader --> BrainDir
    HTTPServer --> DBReader

    AgyCLI --> BashTool
    AgyCLI --> Gemini
    AgyCLI --> Claude
    AgyCLI --> ChatGPT
```

---

## 🔄 Turn Execution & Real-Time Dataflow

```mermaid
sequenceDiagram
    autonumber
    actor User as Developer
    participant UI as Liquid Glass UI
    participant Server as Node.js Server
    participant Watcher as Log Watcher
    participant AGY as Antigravity CLI
    participant Disk as transcript_full.jsonl

    User->>UI: Submit prompt ("Run git status")
    UI->>Server: POST /api/chat (prompt, model, cwd)
    Server->>AGY: Spawn agy --output-format stream-json --print
    AGY-->>Server: {"event": "init", "conversation_id": "xyz"}
    Server-->>UI: data: {"type": "init", "conversationId": "xyz"}

    Server->>Watcher: Start tailing transcript_full.jsonl (80ms)
    
    AGY->>Disk: Write thinking tokens & toolAction
    Watcher->>Disk: Poll & detect new bytes
    Watcher-->>Server: Emit 'thought' event
    Server-->>UI: data: {"type": "thought", "text": "..."}
    UI->>UI: Update open 🧠 Reasoning Box live

    AGY-->>Server: {"event": "step_update", "step_type": "tool", "state": "ACTIVE"}
    Server-->>UI: data: {"type": "tool", "state": "ACTIVE", "CommandLine": "git status"}
    UI->>UI: Mount Terminal Window (● RUNNING, blinking cursor)

    AGY->>AGY: Execute bash command
    AGY-->>Server: {"event": "step_update", "step_type": "tool", "state": "DONE", "output": "..."}
    Server-->>UI: data: {"type": "tool", "state": "DONE", "duration": 0.03}
    UI->>UI: Update status (✓ EXIT 0) & stream stdout into terminal

    AGY-->>Server: {"event": "step_update", "step_type": "agent_response", "text_delta": "..."}
    Server-->>UI: data: {"type": "delta", "text": "..."}
    UI->>UI: Stream markdown tokens with syntax highlighting

    AGY-->>Server: {"event": "result", "status": "SUCCESS"}
    Server-->>UI: data: {"type": "result"}
    Server->>Watcher: Stop file watcher
```

---

## Key Design Principles

1. **True Observability**: Commands executed by the agent are not abstracted away or hidden behind static loaders. Each tool invocation creates an authentic terminal session with exact commands, status codes, and outputs.
2. **Zero Dependencies**: Standard Node.js (`http`, `sqlite`, `child_process`, `readline`) eliminates fragile npm dependency chains and vulnerabilities.
3. **Prompt-Derived Semantics**: Conversation session names are dynamically derived from user request semantics rather than randomized GUIDs.
4. **Adaptive Backdrops**: Apple Liquid Glass styling leverages SVG optical displacement maps and CSS hardware-accelerated filters.
