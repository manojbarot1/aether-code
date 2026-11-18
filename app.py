#!/usr/bin/env python3
"""Aether Lite — a light native-window team chat for AI engineers (Claude Code, Antigravity, custom CLIs).

Run:  ./run.sh        (or .venv/bin/python app.py)
Data: ~/.aether-lite/  (lite.db = sessions + messages + shared memory, config.json = engineers + SSH hosts)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import uuid
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).parent))
import orchestrate as orch  # noqa: E402
import freeport as fp  # noqa: E402
import api_engineer as apieng  # noqa: E402

HERE = Path(__file__).parent
DATA = Path.home() / ".aether-lite"
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "lite.db"
CFG_PATH = DATA / "config.json"
SECRETS_PATH = DATA / "secrets.json"   # API keys, chmod 600, never sent to the UI
KEY_ENV = {"claude_cli": "ANTHROPIC_API_KEY", "antigravity_cli": "GEMINI_API_KEY", "bob_cli": "BOBSHELL_API_KEY",
           "openai_api": "AETHER_API_KEY"}
API = "openai_api"   # engineer that is an OpenAI-compatible chat API (ChatGPT, Ollama/Llama, FreeLLMAPI…), not a CLI
BOB_IMAGE = "localhost/aether-ai-team:latest"   # ships the Linux `bob` binary; used when bob is not installed on the Mac

# GUI-launched apps get a minimal PATH; add the usual CLI install spots.
EXTRA_PATH = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
ENV = {**os.environ, "PATH": ":".join(EXTRA_PATH + [os.environ.get("PATH", "")])}

FAST_AGY_MODEL = "gemini-3.8-flash-medium"
MODES = ("chat", "plan", "edit", "auto")
IDLE_LIMIT = {API: 240}   # seconds without any output before an engineer counts as not responding
IDLE_LIMIT_DEFAULT = 900  # CLIs can be quiet while their own tools run (npm install…)
CONTEXT_MESSAGES = 10      # smaller prompts = faster replies
MAX_MSG_CHARS = 1500
# Team jobs: each engineer sees the user's request, the plan, a file listing and ITS OWN thread, not the last
# few messages of everyone (with 10 engineers those were all someone else's `cat` output).
OWN_THREAD_MESSAGES = 14
OWN_MSG_CHARS = 4000
TEAM_MAX_WORKERS = 4       # more parallel writers than this mostly wait for and overwrite each other
VERIFY_ROUNDS = 4          # verify → fix → re-verify, at most this many verifications
RUNAWAY_CHARS = 40_000     # a reply this long that is mostly repetition is cut before it floods the chat

DEFAULT_CONFIG = {
    "engineers": [
        {"id": "claude", "name": "Claude", "provider": "claude_cli", "command": "claude", "model": "haiku",
         "role": "Principal Software Engineer", "color": "#e8825f", "avatar": "✳", "args": ""},
        {"id": "gemini", "name": "Gemini", "provider": "antigravity_cli", "command": "agy", "model": "",
         "role": "Senior Developer & Research Engineer", "color": "#5ab8f5", "avatar": "✦", "args": ""},
        {"id": "chatgpt", "name": "ChatGPT", "provider": "antigravity_cli", "command": "agy",
         "model": "gpt-oss-120b-medium", "role": "Senior Software Architect", "color": "#35c9a0",
         "avatar": "◎", "args": ""},
    ],
    "ssh": [],
}


# ───────────────────────────── storage ─────────────────────────────

def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL, settings TEXT);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, session_id TEXT, ts REAL, role TEXT, author TEXT,
                                            content TEXT, meta TEXT);
        CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, ts);
        CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY, ts REAL, text TEXT, source TEXT);
        """)
        for col in ("summary TEXT DEFAULT ''", "archived INTEGER DEFAULT 0"):
            try:
                c.execute(f"ALTER TABLE sessions ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass


def load_cfg() -> dict:
    if CFG_PATH.exists():
        try:
            return json.loads(CFG_PATH.read_text())
        except ValueError:
            pass
    save_cfg(DEFAULT_CONFIG)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_secrets() -> dict:
    try:
        return json.loads(SECRETS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_secrets(sec: dict) -> None:
    SECRETS_PATH.write_text(json.dumps(sec))
    SECRETS_PATH.chmod(0o600)


def engineer_env(eng: dict) -> dict:
    key = load_secrets().get(eng.get("id", ""))
    var = eng.get("key_env") or KEY_ENV.get(eng.get("provider", ""))
    return {var: key} if key and var else {}


def save_cfg(cfg: dict) -> None:
    CFG_PATH.write_text(json.dumps(cfg, indent=2))


def default_settings(cfg: dict) -> dict:
    return {"cwd": str(Path.home()), "target": "local", "mode": "edit",
            "team": True, "autoapprove": "full", "active": [e["id"] for e in cfg["engineers"]]}


def uid() -> str:
    return uuid.uuid4().hex[:12]


def row_session(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "title": r["title"], "created": r["created"], "updated": r["updated"],
            "summary": r["summary"] or "", "archived": bool(r["archived"]),
            "settings": json.loads(r["settings"] or "{}")}


def row_msg(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "ts": r["ts"], "role": r["role"], "author": r["author"],
            "content": r["content"], "meta": json.loads(r["meta"] or "{}")}


# ───────────────────────────── engines ─────────────────────────────

_VENV_PY = Path(__file__).parent / ".venv" / "bin" / "python"
PY_FOR_TOOLS = str(_VENV_PY) if _VENV_PY.exists() else sys.executable
VERIFY_PY = PY_FOR_TOOLS + " " + str(Path(__file__).parent / "verify_web.py")


def claude_args(mode: str, eng: dict, proxy: bool = False, verify: bool = False) -> list[str]:
    modes = {
        "chat": ["--tools", ""],
        "plan": ["--tools", "Read", "Grep", "Glob", "--permission-mode", "dontAsk"],
        "edit": ["--permission-mode", "acceptEdits"],
        "auto": ["--permission-mode", "bypassPermissions"],
    }
    args = ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
            "--setting-sources", "", *modes[mode]]
    if eng.get("model"):
        args += ["--model", eng["model"]]
    allowed = []
    if proxy and mode in ("plan", "edit"):
        allowed.append("Bash(ssh:*)")
    if verify and mode in ("plan", "edit"):
        allowed += [f"Bash({VERIFY_PY}:*)", "Bash(curl:*)", "Bash(lsof:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(node --check:*)"]
    if allowed:
        args += ["--allowedTools", *allowed]
    return args


def agy_args(mode: str, eng: dict) -> list[str]:
    modes = {"chat": ["--mode", "plan"], "plan": ["--mode", "plan"], "edit": ["--mode", "accept-edits"],
             "auto": ["--dangerously-skip-permissions"]}
    args = ["--print=", "--input-format", "stream-json", "--output-format", "stream-json",
            "--disable-slash-commands", *modes[mode]]
    args += ["--model", eng.get("model") or FAST_AGY_MODEL]   # flash is ~2x faster than agy's default; pick another in the engineer's settings
    return args


def tool_summary(name: str, inp: dict) -> str:
    for k in ("command", "CommandLine", "file_path", "AbsolutePath", "TargetFile", "path", "pattern", "url", "Url",
              "query", "Query", "description"):
        if inp.get(k):
            return str(inp[k])
    return json.dumps(inp)[:200] if inp else ""


def tool_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


class Parser:
    """Turns a CLI's stdout lines into UI events: ('text', str) | ('tool', dict) | ('result', dict)."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.streamed = False
        self.text = ""
        self.tools: dict[str, dict] = {}

    def feed(self, line: str):
        if self.provider == "claude_cli":
            yield from self._claude(line)
        elif self.provider == "antigravity_cli":
            yield from self._agy(line)
        elif self.provider == "bob_cli":
            yield from self._bob(line)
        elif self.provider == API:
            yield from self._api(line)
        else:
            yield ("text", line)

    def _claude(self, line):
        try:
            ev = json.loads(line)
        except ValueError:
            return
        t = ev.get("type")
        if t == "stream_event":
            inner = ev.get("event") or {}
            d = inner.get("delta") or {}
            if inner.get("type") == "content_block_delta" and d.get("type") == "text_delta" and d.get("text"):
                self.streamed = True
                self.text += d["text"]
                yield ("text", d["text"])
            if inner.get("type") == "content_block_delta" and d.get("type") == "thinking_delta" and d.get("thinking"):
                yield ("thought", d["thinking"])
        elif t == "assistant" and not ev.get("error"):
            for b in (ev.get("message") or {}).get("content") or []:
                if b.get("type") == "text" and not self.streamed:
                    self.text += b.get("text", "")
                    yield ("text", b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool = {"id": b["id"], "name": b.get("name", "tool"), "state": "running",
                            "command": tool_summary(b.get("name", ""), b.get("input") or {}), "output": ""}
                    self.tools[b["id"]] = tool
                    self.streamed = False   # next text block arrives as a fresh message
                    yield ("tool", dict(tool))
        elif t == "user":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in self.tools:
                    tool = self.tools[b["tool_use_id"]]
                    tool["state"] = "error" if b.get("is_error") else "done"
                    tool["output"] = tool_text(b.get("content"))[:4000]
                    yield ("tool", dict(tool))
        elif t == "result":
            ok = not ev.get("is_error")
            final = ev.get("result") or ""
            if ok and not self.text and final:
                self.text += final
                yield ("text", final)
            yield ("result", {"ok": ok, "error": None if ok else (final or "Claude reported an error")})

    def _api(self, line):
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if ev.get("type") == "text":
            self.text += ev["text"]
            yield ("text", ev["text"])
        elif ev.get("type") == "thought":
            yield ("thought", ev["text"])
        elif ev.get("type") == "result":
            yield ("result", {"ok": ev.get("ok", False), "error": ev.get("error")})

    def _bob(self, line):
        clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
        if not clean:
            return
        try:
            ev = json.loads(clean)
        except ValueError:
            if clean.lower().startswith(("error", "fatal")):
                hint = " Check the API key in the engineer's settings." if re.search(r"api key|unauthori|authenticat", clean, re.I) else ""
                yield ("result", {"ok": False, "abort": True, "error": clean[:300] + hint})
            return
        if not isinstance(ev, dict):
            return
        t = ev.get("type")
        if t == "message" and ev.get("role") == "assistant":
            text = tool_text(ev.get("content"))
            if text and self.tools.pop("_after", None) and self.text and not self.text.endswith("\n"):
                text = "\n\n" + text
            self.text += text
            if text:
                yield ("text", text)
        elif t in ("tool_use", "tool_call"):
            self.tools["_after"] = True
            params = ev.get("parameters") or {}
            tid = ev.get("tool_id") or uid()
            tool = {"id": tid, "name": str(ev.get("tool_name") or ev.get("name") or "tool"), "state": "running",
                    "command": str(params.get("path") or params.get("command") or params.get("pattern") or "")[:300], "output": ""}
            self.tools[tid] = tool
            yield ("tool", dict(tool))
        elif t == "tool_result" and ev.get("tool_id") in self.tools:
            tool = self.tools[ev["tool_id"]]
            tool["state"] = "done" if ev.get("status") == "success" else "error"
            tool["output"] = str(ev.get("output") or "")[:4000]
            yield ("tool", dict(tool))
        elif t == "error":
            yield ("result", {"ok": False, "abort": True, "error": str(ev.get("message") or ev.get("error") or "error")[:300]})
        elif t == "result":
            ok = ev.get("status", "success") in ("success", "ok", "completed")
            yield ("result", {"ok": ok, "error": None if ok else str(ev.get("error") or "error")})

    def _agy(self, line):
        try:
            ev = json.loads(line)
        except ValueError:
            if "authentication required" in line.lower():
                yield ("result", {"ok": False, "abort": True,
                                  "error": "Not signed in. Run `agy` in a terminal and sign in with Google."})
            return
        kind = ev.get("event")
        if kind == "step_update":
            step = ev.get("step_update") or {}
            stype = step.get("step_type")
            if stype == "agent_response" and step.get("text_delta"):
                self.text += step["text_delta"]
                yield ("text", step["text_delta"])
            elif stype == "thinking" and step.get("text_delta"):
                yield ("thought", step["text_delta"])
            elif stype == "tool":
                info = step.get("tool_info") or {}
                done = step.get("state") in ("DONE", "ERROR")
                err = info.get("error")
                params = info.get("parameters") or {}
                yield ("tool", {
                    "id": f"step-{step.get('step_index')}", "name": step.get("tool_name") or info.get("name") or "tool",
                    "state": ("error" if err else "done") if done else "running",
                    "command": tool_summary("", params) or str(info.get("name", "")),
                    "output": ((info.get("output") or "") if done else "")[:4000]})
        elif kind == "result":
            res = ev.get("result") or {}
            ok = res.get("status") == "SUCCESS"
            resp = (res.get("response") or "").strip()
            if ok and not self.text and resp and not re.fullmatch(r"Completed \d+ actions?(\(s\))?\.?", resp, re.I):
                self.text += resp
                yield ("text", resp)
            yield ("result", {"ok": ok, "error": None if ok else (res.get("error") or f"ended with {res.get('status')}")})


def wrap_stdin(provider: str, prompt: str) -> str:
    if provider == "antigravity_cli":
        return json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
    return prompt


def build_command(eng: dict, mode: str, target: dict | None, cwd: str, proxy: bool = False, verify: bool = False) -> tuple[list[str], str | None]:
    """Returns (argv, local_cwd). Remote targets wrap the same CLI in ssh and cd on the remote side."""
    prov = eng["provider"]
    if prov == API:   # always runs on this Mac; its ```run commands go wherever the project lives
        return [sys.executable, str(HERE / "api_engineer.py"), "--base-url", eng.get("base_url") or "",
                "--model", eng.get("model") or ""], str(Path.home())
    cmd = eng.get("command") or {"claude_cli": "claude", "antigravity_cli": "agy"}.get(prov, "")
    extra = shlex.split(eng.get("args") or "")
    if prov == "claude_cli":
        argv = [cmd, *claude_args(mode, eng, proxy, verify), *extra]
    elif prov == "antigravity_cli":
        argv = [cmd, *agy_args(mode, eng), *extra]
    elif prov == "bob_cli":
        bmode = {"chat": "ask", "plan": "plan", "edit": "agent", "auto": "agent"}[mode]
        argv = [cmd or "bob", "run", "--accept-license", "--trust", "--mode", bmode, "-f", "stream-json", *extra]
        if eng.get("model"):
            argv += ["--model", eng["model"]]
        if (not target or proxy) and not shutil.which(argv[0], path=ENV["PATH"]):
            # No Mac install: run the Linux bob from the Docker image, with the working folder mounted.
            home = str(Path.home())
            ro = mode in ("chat", "plan") or Path(cwd).resolve() == Path(home)
            var = eng.get("key_env") or KEY_ENV["bob_cli"]
            argv = ["docker", "run", "--rm", "-i", "-e", var, "-v", f"{cwd}:/work{':ro' if ro else ''}", "-w", "/work",
                    "--entrypoint", "bob", BOB_IMAGE, *argv[1:]]
    else:
        argv = [cmd, *extra]
    if not target or proxy:       # proxy: engineer runs on this Mac and reaches the VM through ssh
        return argv, cwd if (not proxy and Path(cwd).is_dir()) else str(Path.home())
    keyvar = (eng.get("key_env") or KEY_ENV["bob_cli"]) if prov == "bob_cli" else None
    keyread = f"IFS= read -r {keyvar}; export {keyvar}; " if keyvar else ""
    remote = f'{keyread}export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:/usr/local/bin:$PATH"; {remote_cd(cwd)} && {shlex.join(argv)}'
    return ssh_argv(target, remote), None


def eff_cwd(st: dict, target: dict | None) -> str:
    """Local folder for local runs; a separate remote folder (default ~) for SSH targets."""
    return (st.get("rcwd") or target.get("cwd") or "~") if target else st["cwd"]


def remote_cd(path: str) -> str:
    path = path.strip() or "~"
    if path == "~":
        return "cd ~"
    if path.startswith("~/"):
        return "cd ~/" + shlex.quote(path[2:])
    return "cd " + shlex.quote(path)


def default_key() -> str:
    for n in ("id_ed25519", "id_rsa", "id_ecdsa"):
        if (Path.home() / ".ssh" / n).is_file():
            return f"~/.ssh/{n}"
    return ""


def ssh_argv(target: dict, remote_cmd: str) -> list[str]:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]
    if target.get("port"):
        argv += ["-p", str(target["port"])]
    key = os.path.expanduser(target.get("key") or "")
    if key and os.path.isfile(key):     # missing/blank key → fall back to ssh defaults, agent and ~/.ssh/config
        argv += ["-i", key]
    argv += [f'{target["user"]}@{target["host"]}' if target.get("user") else target["host"], remote_cmd]
    return argv


# ───────────────────────────── command / file blocks ─────────────────────────────

_HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def run_blocks(text: str) -> list[str]:
    """Commands from the ```run blocks in a reply. A block ends at a ``` line, but not inside a heredoc, so a
    file whose content has Markdown code fences (```) arrives whole instead of being cut off at its first fence.
    A block that is never closed (the reply was cut off mid-stream) is not run: it would write half a file."""
    out: list[str] = []
    lines = (text or "").split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"\s*```run\b(.*)$", lines[i])
        i += 1
        if not m:
            continue
        rest = m.group(1).strip()
        if rest.endswith("```"):                     # ```run ls -la ``` on one line
            if rest[:-3].strip():
                out.append(rest[:-3].strip())
            continue
        body = [rest] if rest else []
        ends = [t for _, t in _HEREDOC.findall(rest)]
        closed = False
        while i < len(lines):
            ln = lines[i]
            i += 1
            if ends:                                 # inside a heredoc: only its terminator ends it
                body.append(ln)
                if ln.strip() == ends[0]:
                    ends.pop(0)
                continue
            if ln.strip() == "```":
                closed = True
                break
            if ln.rstrip().endswith("```"):          # `ls -la ```
                body.append(ln.rstrip()[:-3])
                closed = True
                break
            body.append(ln)
            ends += [t for _, t in _HEREDOC.findall(ln)]
        cmd = "\n".join(body).strip()
        if closed and cmd:
            out.append(cmd)
    return out


def aether_block(text: str) -> dict:
    """The last ```aether {...} block in a reply (the same protocol as aether-ai-team): "files" to write and
    "commands" to run. Parsed with a real JSON decoder from the opening brace, so file content may contain
    anything, fences included. strict=False accepts raw newlines inside strings (small models emit them)."""
    dec = json.JSONDecoder(strict=False)
    for m in reversed(list(re.finditer(r"```aether[ \t]*\n", text or ""))):
        start = text.find("{", m.end())
        if start < 0:
            continue
        try:
            data, _ = dec.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    files = lenient_files(text)
    return {"files": files, "lenient": True} if files else {}


def lenient_files(text: str) -> list[dict]:
    """Files from an ```aether block whose JSON is broken: `}}}` for `}]}`, JS escapes like \\' , quotes left unescaped
    in HTML (`<a href="x">`), the closing quote forgotten before the fence. A file is only taken when its content is
    complete (a reply cut off mid-file gives nothing for that file)."""
    first = re.search(r"```aether[ \t]*\n", text or "")
    if not first:
        return []
    seg, dec, out = text[first.end():], json.JSONDecoder(strict=False), {}
    # JS-style escapes (\' \$ \`) are invalid JSON; doubling the backslash keeps the file's text exactly the same
    fix = lambda t: re.sub(r"\\(.)", lambda e: e.group(0) if e.group(1) in '"\\/bfnrtu' else "\\\\" + e.group(1), t, flags=re.S)

    def whole(s: str):
        """The string literal at the start of s, if it really ends there (followed by } or ,), else None."""
        try:
            val, end = dec.raw_decode(s, 0)
        except ValueError:
            return None
        return val if isinstance(val, str) and re.match(r"\s*[,}]", s[end:]) else None

    for pm in re.finditer(r'"path"\s*:\s*"([^"\n]{1,300})"\s*,\s*"content"\s*:\s*"', seg):
        q = pm.end() - 1
        content = whole(seg[q:])
        if content is None:
            content = whole(fix(seg[q:]))
        if content is None:
            # Unescaped quotes inside: the content runs to this file's closing `"}` before the next file or the fence.
            rest = seg[q + 1:]
            ends = [m.start() for m in (re.search(r'"\s*\}\s*,\s*\{\s*"path"', rest),
                                        re.search(r'"?(?:\s*[}\]])*\s*\n```[ \t]*(?:\n|$)', rest)) if m]
            if not ends:
                continue
            raw = rest[:min(ends)]
            raw = re.sub(r'(?<!\\)"', '\\"', raw)
            try:
                content = json.loads('"' + fix(raw) + '"', strict=False)
            except ValueError:
                continue
        if isinstance(content, str) and content.strip():
            out[pm.group(1)] = content
    return [{"path": k, "content": v} for k, v in out.items()]


def block_trouble(text: str) -> str:
    """Why a reply that tried to write files or run commands produced nothing to act on ('' when it didn't try)."""
    t = text or ""
    if t.count("```") % 2 == 1:
        kind = re.findall(r"```(\w*)", t)[-1] or "code"
        return (f"Your reply was cut off inside a ```{kind} block ({len(t):,} characters) — the provider's length limit — so "
                "NOTHING was written or run. Send ONE file per reply in an ```aether block, and keep each reply under ~12,000 "
                "characters (split a big file into modules if needed).")
    if re.search(r"```aether", t):
        dec = json.JSONDecoder(strict=False)
        for m in re.finditer(r"```aether[ \t]*\n", t):
            start = t.find("{", m.end())
            try:
                dec.raw_decode(t, start)
            except ValueError as exc:
                near = t[max(start, getattr(exc, "pos", start) - 60):getattr(exc, "pos", start) + 20].replace("\n", "⏎")
                return (f"Your ```aether block is not valid JSON ({exc.msg} near: …{near}…), so NOTHING was written. Resend "
                        'it exactly as {"files": [{"path": "…", "content": "…"}]} — escape quotes and newlines in content, '
                        "close with `\"}]}` then the ``` fence. One file per reply is safest.")
    return ""


# ───────────────────────────── API exposed to the UI ─────────────────────────────

CONVO = ("Answer the user directly and concisely (under ~150 words unless they asked for detail). "
         "Do not start building or changing anything unless they asked you to.")
QUICK = ("You are the only engineer on this request: do it yourself, end to end — build or fix it, smoke-test it, "
         "and if it is a server start it on a FREE port. Then report in a few lines with the real command output as evidence.")
RUN_NOTE = ("You cannot run shell commands yourself in this mode. When you need one (to test, start a server, list files…), "
            "end your reply with a fenced block:\n```run\nls -la\n```\n"
            "Each ```run block runs as ONE shell script (multi-line commands and heredocs work). The app asks the user to "
            "approve it, runs it where the project lives, and sends you the output so you can continue. "
            "Start with small read-only commands.\n")

API_NOTE = ("You are reached through a chat API and have no file or shell tools of your own. Only two kinds of block are "
            "acted on — any other tool-call syntax (<tool_call>, function calls) is ignored.\n"
            "1. To create or replace files, put them in ONE ```aether block at the end of your reply (JSON, each file complete):\n"
            "```aether\n{\"files\": [{\"path\": \"src/app.ts\", \"content\": \"...the whole file...\"}]}\n```\n"
            "Paths are relative to the project folder. The app writes them and tells you each size. Prefer this over heredocs: "
            "file content can contain anything (``` fences, quotes) without breaking.\n"
            "2. To run commands (install, build, test, start a server), use ```run blocks.\n"
            "Check your work (e.g. `wc -c file`, run the tests) before saying it is done.\n")

DOD = ("Definition of done: never say something works until you have actually run or opened it and can show the real "
       "command output. PORTS: never assume 8000 is free. Get a free port with `freeport 8000` (prints the first free port at or "
       "above 8000), or serve a folder with `aserve <dir>` (picks a free port and prints the real URL). Report the URL it printed. "
       "Never stop programs with pkill/killall by name; stop only servers you started, by pid.\n")

VERIFY = (
    "You are the TEAM LEAD and the only one who signs off. Do NOT trust your teammates' claims — verify everything yourself with your tools:\n"
    "1. Find what was built (list the working directory).\n"
    "2. Run it for real. Pick a FREE port with `freeport 8000` (never assume 8000 is free) — or `aserve <dir>` for a static site — and start it in the background.\n"
    f"3. For anything served over HTTP run: `{VERIFY_PY} <url>` — it loads the page in headless Chrome, reports errors, what is "
    "on screen, dialogs left open, and clicks every button. Then test the features the user asked for with scripted steps: "
    f"`{VERIFY_PY} <url> --no-clicks --steps '[{{\"click\": \"#add\"}}, {{\"expect\": \"#modal\", \"visible\": true}}, "
    "{\"type\": [\"#title\", \"Test\"]}, {\"submit\": \"#form\"}, {\"expect\": \".card\", \"text\": \"Test\"}, {\"reload\": true}, "
    "{\"expect\": \".card\", \"count\": 1}]'` (also: press KEY, drag [from, to], select [sel, value], eval JS + equals, wait MS; "
    "use the real ids/classes from the HTML). Each ```run block is a separate shell: a server you start keeps running, but "
    "`$(freeport 8000)` gives a NEW port each time — start it once with `aserve .` and use the URL it prints. "
    "Aether may already have started the page for you: see AUTOMATIC CHECKS. "
    "For other code run its tests or run it with sample input.\n"
    "4. If there is a team plan, go through its Requirements list one by one: `✓ R1 …` or `✗ R1 …`, each with evidence "
    "(the command you ran, or the file and the code that implements it). Check the pieces fit: every name one file uses from "
    "another (functions, exports, element ids, paths) must exist there — grep for them. A missing requirement, placeholder or "
    "mismatch is a FAIL.\n"
    "5. Quote the real command output as evidence.\n"
    "End with exactly one line: `VERDICT: PASS` (everything demonstrably works), `VERDICT: FAIL` (say precisely what is broken) "
    "or `VERDICT: UNVERIFIED` (you were not allowed to run the checks — say which). "
    "After VERDICT: PASS give the user the final answer: URL / how to run, and what you tested. Never write PASS without evidence from commands you ran in this step.")


SUMMARY = (
    "The job is finished. As TEAM LEAD, write the final hand-over for the user. Do not run any commands or change files now; "
    "use only what really happened in this session (the messages above) and never claim something works unless it was shown.\n"
    "Use exactly these headings:\n"
    "## Result\nOne or two lines: what was built or changed, and whether it works (say how it was checked).\n"
    "## Requirements\nIf there was a plan: each requirement with ✓ (shown working), ✗ (missing/broken) or ? (not checked). Otherwise skip this heading.\n"
    "## Where\nThe folder and the main files.\n"
    "## How to run\nThe exact commands and/or URL.\n"
    "## Who did what\nOne line per engineer.\n"
    "## Open issues\nWhat is not done, broken or unverified, and the next step. Write 'None' if there are none.")


_READY: dict[tuple[str, str], tuple[float, bool]] = {}


def remote_ready(eng: dict, target: dict) -> bool:
    """Can this engineer's CLI run *on the VM* (installed + signed in)? Cached for 2 minutes."""
    if eng["provider"] == API:
        return True      # nothing to install on the VM: the API call is made from the Mac
    key = (target["id"], eng["id"])
    hit = _READY.get(key)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    prov = eng["provider"]
    cmd = eng.get("command") or {"claude_cli": "claude", "antigravity_cli": "agy"}.get(prov, "")
    ok = False
    if cmd and not (prov == "bob_cli" and not (engineer_env(eng) or os.environ.get("BOBSHELL_API_KEY"))):   # Bob also needs its key (sent from the Mac)
        probe = {"claude_cli": f"{cmd} auth status --json 2>/dev/null | grep -q '\"loggedIn\": *true'",
                 "antigravity_cli": "test -f ~/.gemini/antigravity-cli/antigravity-oauth-token"}.get(prov, "true")
        try:
            r = subprocess.run(ssh_argv(target, f'export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:/usr/local/bin:$PATH"; '
                                                f'command -v {shlex.quote(cmd)} >/dev/null && {probe}'),
                               capture_output=True, text=True, timeout=25, env=ENV)
            ok = r.returncode == 0
        except Exception:
            ok = False
    _READY[key] = (time.time(), ok)
    return ok


class Api:
    def __init__(self) -> None:
        self.window: webview.Window | None = None
        self.procs: dict[str, list[subprocess.Popen]] = {}
        self.stopped: set[str] = set()
        self._last: dict[str, dict] = {}
        self._acted: set[str] = set()
        self._approvals: dict[str, dict] = {}
        self._allow_all: set[str] = set()
        self._outcome: dict[tuple[str, str], dict] = {}   # (session, engineer) → how its last run ended
        self._busy: dict[str, set[str]] = {}               # session → engineers running right now
        self._failed_turn: dict[str, set[str]] = {}        # session → engineers that failed during this turn
        self._request: dict[str, str] = {}                 # session → the user's request for the current turn
        self._turn_t0: dict[str, float] = {}               # session → when the current turn started
        self._plan: dict[str, str] = {}                    # session → the lead's plan for the current turn
        self._owners: dict[str, dict[str, str]] = {}       # session → {file path or dir/: engineer name}
        self._cmd_seen: dict[tuple, tuple[str, str]] = {}  # (session, engineer, command) → (project state, time)
        self._auto_url: dict[str, str] = {}                # session → URL Aether served the project at for checks
        self._final: dict[str, dict] = {}                  # session → how the last verification ended
        self._auto_cmds: dict[str, list[str]] = {}         # session → commands the automatic checks run
        self._notes: dict[str, list[str]] = {}             # session → messages the user sent while the job ran

    # ── ui plumbing
    def emit(self, ev: dict) -> None:
        if self.window:
            try:
                self.window.evaluate_js(f"window.onEvent({json.dumps(ev)})")
            except Exception:
                pass

    # ── bootstrap / sessions
    def bootstrap(self) -> dict:
        cfg = load_cfg()
        with db() as c:
            rows = c.execute("SELECT * FROM sessions ORDER BY updated DESC").fetchall()
        sessions = [row_session(r) for r in rows]
        if not sessions:
            sessions = [self.new_session()]
        return {"default_key": default_key(), "config": self._public_cfg(cfg), "sessions": sessions, "memory": self.list_memory(), "home": str(Path.home())}

    def new_session(self) -> dict:
        cfg = load_cfg()
        sid, now = uid(), time.time()
        s = {"id": sid, "title": "New session", "created": now, "updated": now, "summary": "", "archived": False,
             "settings": default_settings(cfg)}
        with db() as c:
            c.execute("INSERT INTO sessions(id,title,created,updated,settings) VALUES(?,?,?,?,?)", (sid, s["title"], now, now, json.dumps(s["settings"])))
        return s

    def load_session(self, sid: str) -> list[dict]:
        with db() as c:
            return [row_msg(r) for r in c.execute("SELECT * FROM messages WHERE session_id=? ORDER BY ts", (sid,))]

    def job_status(self, sid: str) -> dict:
        """The Project panel's Status tab: the session's current or last job (see job_status.py)."""
        import importlib
        import job_status as js
        try:   # pick up a newer job_status.py without restarting the chat (and the jobs running in it)
            mt = os.path.getmtime(js.__file__)
            if getattr(js, "_mtime", mt) != mt:
                js = importlib.reload(js)
            js._mtime = mt
        except OSError:
            pass
        cfg = load_cfg()
        st = {**default_settings(cfg), **self._session_settings(sid)}
        target = next((h for h in cfg["ssh"] if h["id"] == st["target"]), None) if st.get("target", "local") != "local" else None
        engs = cfg["engineers"]
        busy = self._busy.get(sid, set())
        live = {"running": sid in self.procs, "local": target is None, "cwd": eff_cwd(st, target),
                "engineers": [{"id": e["id"], "name": e["name"], "color": e.get("color"), "avatar": e.get("avatar")} for e in engs],
                "busy_names": [e["name"] for e in engs if e["id"] in busy],
                "down": {e["id"]: orch.down_reason(e["id"]) or "" for e in engs if orch.is_down(e["id"])}}
        try:
            return js.status(self.load_session(sid), live)
        except Exception as exc:          # the panel must never break the chat
            return {"error": str(exc)[:200]}

    def delete_session(self, sid: str) -> bool:
        self.stop(sid)
        with db() as c:
            c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
        return True

    def rename_session(self, sid: str, title: str) -> bool:
        with db() as c:
            c.execute("UPDATE sessions SET title=? WHERE id=?", (title.strip()[:80] or "Untitled", sid))
        return True

    def check_status(self) -> dict:
        """Which engineers can actually run right now (CLI present + signed in), and which SSH hosts answer."""
        cfg = load_cfg()
        out: dict = {"engineers": {}, "ssh": {}}

        def check(e: dict) -> tuple[str, dict]:
            why = orch.down_reason(e["id"])
            if why:
                return e["id"], {"state": "limit", "detail": why}
            if e["provider"] == API:
                try:
                    apieng.list_models(e.get("base_url") or "", load_secrets().get(e["id"], ""), timeout=8)
                    return e["id"], {"state": "online", "detail": "ready"}
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        return e["id"], {"state": "login", "detail": "API key missing or rejected"}
                    return e["id"], {"state": "online", "detail": f"reachable (model list: HTTP {exc.code})"}
                except Exception as exc:
                    return e["id"], {"state": "missing", "detail": (f"cannot reach {e.get('base_url')}: {getattr(exc, 'reason', exc)}"[:120]
                                                    + apieng.ssl_hint(e.get("base_url") or "", exc))}
            if e["provider"] == "bob_cli":
                has_key = bool(engineer_env(e) or os.environ.get("BOBSHELL_API_KEY"))
                native = bool(shutil.which(e.get("command") or "bob", path=ENV["PATH"]))
                docker_ok = False
                if not native:
                    try:
                        docker_ok = subprocess.run(["docker", "image", "inspect", BOB_IMAGE], capture_output=True,
                                                   timeout=10, env=ENV).returncode == 0
                    except Exception:
                        pass
                if not (native or docker_ok):
                    return e["id"], {"state": "missing", "detail": "bob not installed (and Docker image not found)"}
                return e["id"], {"state": "online" if has_key else "login",
                                 "detail": ("ready" + ("" if native else " (via Docker)")) if has_key else "add the Bob API key"}
            cmd = e.get("command") or {"claude_cli": "claude", "antigravity_cli": "agy"}.get(e["provider"], "")
            if not cmd or not shutil.which(cmd, path=ENV["PATH"]):
                return e["id"], {"state": "missing", "detail": f"`{cmd}` not installed"}
            if e["provider"] == "claude_cli":
                try:
                    r = subprocess.run([cmd, "auth", "status", "--json"], capture_output=True, text=True, timeout=15, env=ENV)
                    ok = bool(json.loads(r.stdout[r.stdout.index("{"):]).get("loggedIn"))
                except Exception:
                    ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
                return e["id"], {"state": "online" if ok else "login", "detail": "ready" if ok else "run `claude auth login`"}
            if e["provider"] == "antigravity_cli":
                tok = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
                ok = tok.is_file() or bool(os.environ.get("GEMINI_API_KEY"))
                return e["id"], {"state": "online" if ok else "login", "detail": "ready" if ok else "run `agy` and sign in"}
            return e["id"], {"state": "online", "detail": "command found"}

        def ssh_check(h: dict) -> tuple[str, dict]:
            try:
                r = subprocess.run(ssh_argv(h, "echo ok"), capture_output=True, text=True, timeout=12, env=ENV)
                return h["id"], {"state": "online" if r.returncode == 0 else "offline",
                                 "detail": "connected" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["unreachable"])[-1][:120]}
            except Exception as exc:
                return h["id"], {"state": "offline", "detail": str(exc)[:120]}

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            for k, v in ex.map(check, cfg["engineers"]):
                out["engineers"][k] = v
            for k, v in ex.map(ssh_check, cfg["ssh"]):
                out["ssh"][k] = v
        return out

    def list_models(self, eng: dict) -> dict:
        """Models an engineer's provider offers right now. Live where the CLI/API can list them, else known aliases."""
        prov, out = eng.get("provider"), []
        try:
            if prov == "antigravity_cli":
                r = subprocess.run([eng.get("command") or "agy", "models"], capture_output=True, text=True, timeout=40, env=ENV)
                for ln in r.stdout.splitlines():
                    if "\t" in ln:
                        i, label = ln.split("\t", 1)
                        out.append({"id": i.strip(), "label": label.strip()})
            elif prov == "claude_cli":
                out = [{"id": "haiku", "label": "Haiku (latest, fastest)"}, {"id": "sonnet", "label": "Sonnet (latest)"},
                       {"id": "opus", "label": "Opus (latest)"}]
                key = engineer_env(eng).get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
                if key:   # live list straight from the API when a key is available
                    import urllib.request
                    req = urllib.request.Request("https://api.anthropic.com/v1/models?limit=100",
                                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        out += [{"id": m["id"], "label": m.get("display_name") or m["id"]} for m in json.loads(resp.read())["data"]]
            elif prov == API:
                key = eng.get("api_key") or load_secrets().get(eng.get("id", ""), "")
                out = [{"id": i, "label": i} for i in sorted(apieng.list_models(eng.get("base_url") or "", key))]
            elif prov == "bob_cli":
                out = []   # Bob picks the model in the IBM portal; there is no per-call list
        except Exception as exc:
            return {"models": out, "error": str(exc)[:160]}
        return {"models": out, "error": None}

    def list_dirs(self, target_id: str, path: str) -> dict:
        """Sub-folders of `path` on this Mac or on an SSH host, for the folder browser."""
        cfg = load_cfg()
        target = next((h for h in cfg["ssh"] if h["id"] == target_id), None) if target_id != "local" else None
        try:
            if target:
                r = subprocess.run(ssh_argv(target, f"{remote_cd(path or '~')} && pwd && ls -1Ap | grep '/$'; true"),
                                   capture_output=True, text=True, timeout=20, env=ENV)
                lines = r.stdout.splitlines()
                if not lines:
                    return {"path": path, "dirs": [], "error": (r.stderr.strip().splitlines() or ["cannot open folder"])[-1]}
                cur, dirs = lines[0], [d.rstrip("/") for d in lines[1:]]
            else:
                p = Path(os.path.expanduser(path or "~")).resolve()
                cur = str(p)
                dirs = sorted(d.name for d in p.iterdir() if d.is_dir()) if p.is_dir() else []
            dirs = [d for d in dirs if not d.startswith(".")]
            parent = str(Path(cur).parent)
            return {"path": cur, "parent": parent if parent != cur else None, "dirs": sorted(dirs, key=str.lower), "error": None}
        except Exception as exc:
            return {"path": path, "dirs": [], "parent": None, "error": str(exc)[:200]}

    # Clipboard tools to try after AppKit: macOS, then Wayland and X11 on Linux.
    CLIP_PASTE = (["pbpaste"], ["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-bo"])
    CLIP_COPY = (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-bi"])

    def clip_get(self) -> str:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            return str(NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or "")
        except Exception:
            pass
        for argv in self.CLIP_PASTE:
            if shutil.which(argv[0]):
                try:
                    return subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout
                except Exception:
                    continue
        return ""

    def clip_set(self, text: str) -> bool:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(text, NSPasteboardTypeString)
            return True
        except Exception:
            pass
        for argv in self.CLIP_COPY:
            if shutil.which(argv[0]):
                try:
                    return subprocess.run(argv, input=text, text=True, timeout=5).returncode == 0
                except Exception:
                    continue
        return False

    def archive_session(self, sid: str, flag: bool = True) -> bool:
        with db() as c:
            c.execute("UPDATE sessions SET archived=? WHERE id=?", (1 if flag else 0, sid))
        return True

    def set_auto_memory(self, on: bool) -> bool:
        cfg = load_cfg()
        cfg["auto_memory"] = bool(on)
        save_cfg(cfg)
        return True

    def ssh_config_hosts(self) -> list[dict]:
        """Host aliases from ~/.ssh/config, so a VM you already ssh to can be added in one click."""
        out, cur = [], None
        p = Path.home() / ".ssh" / "config"
        if p.exists():
            for line in p.read_text(errors="ignore").splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "host" and "*" not in parts[1] and "?" not in parts[1]:
                    cur = {"name": parts[1].split()[0], "host": parts[1].split()[0], "user": "", "port": 22, "key": ""}
                    out.append(cur)
                elif cur and len(parts) == 2:
                    k, v = parts[0].lower(), parts[1].strip()
                    if k == "hostname":
                        cur["host"] = v
                    elif k == "user":
                        cur["user"] = v
                    elif k == "port" and v.isdigit():
                        cur["port"] = int(v)
                    elif k == "identityfile":
                        cur["key"] = v
        return out

    def update_settings(self, sid: str, settings: dict) -> bool:
        if settings.get("autoapprove") == "ask":
            self._allow_all.discard(sid)      # switching Auto off also cancels "allow all this session"
        with db() as c:
            c.execute("UPDATE sessions SET settings=? WHERE id=?", (json.dumps(settings), sid))
        return True

    def make_dir(self, target_id: str, path: str) -> dict:
        """Create a folder (for the folder browser's "New folder"); returns its full path."""
        cfg = load_cfg()
        target = next((h for h in cfg["ssh"] if h["id"] == target_id), None) if target_id != "local" else None
        try:
            if target:
                r = subprocess.run(ssh_argv(target, f"mkdir -p {shlex.quote(path).replace(chr(39) + '~', '~' + chr(39), 1)} && "
                                                    f"{remote_cd(path)} && pwd"), capture_output=True, text=True, timeout=20, env=ENV)
                if r.returncode:
                    return {"path": path, "error": (r.stderr.strip().splitlines() or ["mkdir failed"])[-1][:200]}
                return {"path": r.stdout.strip().splitlines()[-1], "error": None}
            p = Path(os.path.expanduser(path)).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return {"path": str(p), "error": None}
        except Exception as exc:
            return {"path": path, "error": str(exc)[:200]}

    def upload_file(self, sid: str, name: str, data_b64: str) -> dict:
        """Save a file the user attached into <working folder>/attachments/ (on the SSH host for remote sessions).
        Returns the full path, which the UI adds to the message so engineers can open it."""
        import base64
        cfg = load_cfg()
        st = {**default_settings(cfg), **self._session_settings(sid)}
        target = next((h for h in cfg["ssh"] if h["id"] == st.get("target")), None)
        safe = re.sub(r"[^\w.\- ]+", "_", Path(name or "file").name).strip(" .") or "file"
        try:
            data = base64.b64decode(data_b64 or "", validate=True)
        except Exception:
            return {"error": "could not read the file"}
        try:
            if target:
                folder = eff_cwd(st, target).rstrip("/") + "/attachments"
                q = shlex.quote(folder).replace(chr(39) + "~", "~" + chr(39), 1)
                stem, ext = os.path.splitext(safe)
                script = (f"mkdir -p {q} && cd {q} && f={shlex.quote(safe)}; n=2; "
                          f"while [ -e \"$f\" ]; do f={shlex.quote(stem)}-$n{shlex.quote(ext)}; n=$((n+1)); done; "
                          "cat > \"$f\" && echo \"$(pwd)/$f\"")
                r = subprocess.run(ssh_argv(target, script), input=data, capture_output=True, timeout=120, env=ENV)
                if r.returncode:
                    return {"error": (r.stderr.decode(errors="replace").strip().splitlines() or ["upload failed"])[-1][:200]}
                return {"path": r.stdout.decode().strip().splitlines()[-1], "size": len(data), "error": None}
            cwd = Path(os.path.expanduser(st.get("cwd") or "~")).resolve()
            app_dir = Path(__file__).resolve().parent
            if cwd == Path.home().resolve() or cwd == app_dir or app_dir in cwd.parents:
                cwd = Path.home() / "aether-projects"          # never drop files into home or Aether's own source
            folder = cwd / "attachments"
            folder.mkdir(parents=True, exist_ok=True)
            dest, n = folder / safe, 2
            while dest.exists():
                dest, n = folder / f"{Path(safe).stem}-{n}{Path(safe).suffix}", n + 1
            dest.write_bytes(data)
            return {"path": str(dest), "size": len(data), "error": None}
        except Exception as exc:
            return {"error": str(exc)[:200]}

    def pick_dir(self) -> str | None:
        res = self.window.create_file_dialog(webview.FOLDER_DIALOG) if self.window else None
        return res[0] if res else None

    # ── engineers & ssh
    def save_engineer(self, eng: dict) -> dict:
        cfg = load_cfg()
        key = eng.pop("api_key", None)
        clear = eng.pop("clear_key", False)
        if not eng.get("id"):
            base = re.sub(r"[^a-z0-9]+", "-", eng["name"].lower()).strip("-") or "engineer"
            taken = {e["id"] for e in cfg["engineers"]}
            eng["id"], n = base, 2
            while eng["id"] in taken:
                eng["id"], n = f"{base}-{n}", n + 1
        cfg["engineers"] = [e for e in cfg["engineers"] if e["id"] != eng["id"]] + [eng] \
            if not any(e["id"] == eng["id"] for e in cfg["engineers"]) \
            else [eng if e["id"] == eng["id"] else e for e in cfg["engineers"]]
        sec = load_secrets()
        if key:
            sec[eng["id"]] = key
        elif clear:
            sec.pop(eng["id"], None)
        save_secrets(sec)
        save_cfg(cfg)
        return self._public_cfg(cfg)

    def _public_cfg(self, cfg: dict) -> dict:
        sec = load_secrets()
        return {**cfg, "auto_memory": cfg.get("auto_memory", True),
                "engineers": [{**e, "has_key": e["id"] in sec} for e in cfg["engineers"]]}

    def delete_engineer(self, eid: str) -> dict:
        cfg = load_cfg()
        cfg["engineers"] = [e for e in cfg["engineers"] if e["id"] != eid]
        save_cfg(cfg)
        sec = load_secrets()
        if sec.pop(eid, None) is not None:
            save_secrets(sec)
        return self._public_cfg(cfg)

    def save_ssh(self, host: dict) -> dict:
        cfg = load_cfg()
        host.setdefault("id", uid())
        cfg["ssh"] = [host if h["id"] == host["id"] else h for h in cfg["ssh"]] \
            if any(h["id"] == host["id"] for h in cfg["ssh"]) else cfg["ssh"] + [host]
        save_cfg(cfg)
        return self._public_cfg(cfg)

    def delete_ssh(self, hid: str) -> dict:
        cfg = load_cfg()
        cfg["ssh"] = [h for h in cfg["ssh"] if h["id"] != hid]
        save_cfg(cfg)
        return self._public_cfg(cfg)

    def test_ssh(self, host: dict) -> dict:
        try:
            r = subprocess.run(ssh_argv(host, "echo connected as $(whoami)@$(hostname); pwd; "
                                        "for c in claude agy bob; do command -v $c >/dev/null && echo \"has $c\"; done; true"),
                               capture_output=True, text=True, timeout=25, env=ENV)
            return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()}
        except Exception as exc:
            return {"ok": False, "output": str(exc)}

    # ── memory
    def list_memory(self) -> list[dict]:
        with db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM memory ORDER BY ts")]

    def add_memory(self, text: str, source: str = "you") -> list[dict]:
        text = text.strip()
        if text:
            with db() as c:
                if not c.execute("SELECT 1 FROM memory WHERE text=?", (text,)).fetchone():
                    c.execute("INSERT INTO memory VALUES(?,?,?,?)", (uid(), time.time(), text, source))
        return self.list_memory()

    def delete_memory(self, mid: str) -> list[dict]:
        with db() as c:
            c.execute("DELETE FROM memory WHERE id=?", (mid,))
        return self.list_memory()

    # ── chat
    STATUS_Q = re.compile(r"\b(status|progress|update|how('?s| is| are)? (it|things|we|you|the \w+) ?(going|doing)?|where are (we|you)|"
                          r"what('?s| is) (happening|going on)|eta|done yet|ready yet|finished yet|still working|any news)\b|^\s*\?+\s*$", re.I)

    def _mid_job(self, sid: str, text: str) -> dict:
        """A message sent while a job runs (like Claude Desktop): it shows at once as "queued", never stops the job, and
        reaches the agents at their next step. The first agent to see it answers it briefly, then carries on; every agent
        keeps it as an instruction. If the job ends before anyone saw it, it runs as the next request."""
        now = time.time()
        msg = {"id": uid(), "ts": now, "role": "user", "author": "You", "content": text, "meta": {"during_job": True, "queued": True}}
        with db() as c:
            c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)", (msg["id"], sid, now, "user", "You", text, json.dumps(msg["meta"])))
        self._notes.setdefault(sid, []).append({"id": msg["id"], "text": text, "seen": [], "answered": False})
        return msg

    def _deliver_notes(self, sid: str, eng: dict, phase: str) -> str:
        """Prompt text for the user's mid-job messages, and mark them seen by `eng` (the chat shows who saw them)."""
        notes = self._notes.get(sid) or []
        if not notes:
            return ""
        out, reply = [], []
        for n in notes:
            if eng["name"] not in n["seen"]:
                n["seen"].append(eng["name"])
                self._mark_note(sid, n)
            if not n["answered"] and phase not in ("summary", "plan"):
                n["answered"] = True
                reply.append(n)
        out.append("MESSAGES THE USER SENT WHILE THE TEAM WAS WORKING (newest last) — they take priority; follow them:\n" +
                   "\n".join(f"- {n['text'][:2000]}" for n in notes[-10:]))
        if reply:
            try:
                import job_status as js
                st = js.status_text(self.job_status(sid))
            except Exception:
                st = ""
            asks = "\n".join(f"- {n['text'][:600]}" for n in reply)
            out.append(f"The user is waiting for an answer to:\n{asks}\nSTART your reply with a short answer to that "
                       "(2-5 lines; for a progress question use the job status below and what you are doing yourself), then a line "
                       "with only `---`, then continue your own task as before.\n" + (f"Job status right now:\n{st}" if st else ""))
        return "\n\n".join(out)

    def _mark_note(self, sid: str, n: dict) -> None:
        meta = {"during_job": True, "queued": False, "seen_by": n["seen"]}
        with db() as c:
            c.execute("UPDATE messages SET meta=? WHERE id=?", (json.dumps(meta), n["id"]))
        self.emit({"t": "seen", "sid": sid, "mid": n["id"], "by": n["seen"]})

    def _run_queued(self, sid: str) -> None:
        """After a job: messages no agent got to see run as the next request (one turn, in order)."""
        left = [n for n in self._notes.get(sid) or [] if not n["seen"]]
        if not left or sid in self.stopped:
            return
        text = "\n\n".join(n["text"] for n in left)
        now = time.time()
        with db() as c:   # they become ordinary messages, placed where they are now handled
            for n in left:
                c.execute("UPDATE messages SET ts=?, meta=? WHERE id=?", (now, json.dumps({"queued_turn": True}), n["id"]))
                self.emit({"t": "promoted", "sid": sid, "mid": n["id"]})
        self.procs[sid] = []
        self.stopped.discard(sid)
        threading.Thread(target=self._turn, args=(sid, text), daemon=True).start()

    def send(self, sid: str, text: str) -> dict | None:
        text = text.strip()
        if not text:
            return None
        if sid in self.procs:
            return self._mid_job(sid, text)
        now = time.time()
        msg = {"id": uid(), "ts": now, "role": "user", "author": "You", "content": text, "meta": {}}
        with db() as c:
            c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                      (msg["id"], sid, now, "user", "You", text, "{}"))
            n = c.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)).fetchone()[0]
            if n == 1:
                c.execute("UPDATE sessions SET title=? WHERE id=?", (re.sub(r"\s+", " ", text)[:48], sid))
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))
        self.procs[sid] = []
        self.stopped.discard(sid)
        threading.Thread(target=self._turn, args=(sid, text), daemon=True).start()
        return msg

    def stop(self, sid: str) -> bool:
        self.stopped.add(sid)
        for p in list(self.procs.get(sid, [])):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                pass
        return True

    def _session_settings(self, sid: str) -> dict:
        with db() as c:
            r = c.execute("SELECT settings FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(r["settings"]) if r else {}

    def _turn(self, sid: str, text: str) -> None:
        try:
            cfg = load_cfg()
            st = {**default_settings(cfg), **self._session_settings(sid)}
            target = next((h for h in cfg["ssh"] if h["id"] == st["target"]), None) if st["target"] != "local" else None

            if text.startswith("!"):
                self._shell(sid, text[1:].strip(), st, target)
                return
            if text.lower().startswith("/remember "):
                self.add_memory(text[10:], "you")
                self._post(sid, "system", "Memory", "Saved to shared memory.")
                self.emit({"t": "memory", "memory": self.list_memory()})
                return

            engs = {e["id"]: e for e in cfg["engineers"]}
            names = {e["name"].lower(): e["id"] for e in cfg["engineers"]} | {i: i for i in engs}
            mentioned = [names[m.lower()] for m in re.findall(r"@([\w-]+)", text) if m.lower() in names]
            if re.search(r"@all\b", text, re.I):
                mentioned = [e["id"] for e in cfg["engineers"]]
            self._acted.discard(sid)
            self._failed_turn[sid] = set()
            self._request[sid], self._turn_t0[sid] = text, time.time()
            self._plan.pop(sid, None)
            self._owners.pop(sid, None)
            self._auto_url.pop(sid, None)
            self._final.pop(sid, None)
            self._notes.pop(sid, None)   # (queued ones were turned into this request by _run_queued)
            order = list(dict.fromkeys(mentioned)) or [i for i in st["active"] if i in engs]
            if not order:
                self._post(sid, "system", "Aether", "No engineer selected. Pick one in the sidebar or use @name.")
                return
            # engineers that are out of quota / signed out are skipped, not waited on
            for i in order:
                why = orch.down_reason(i)
                if why:
                    self._post(sid, "system", "Aether", f"{engs[i]['name']} is unavailable — {why}. Continuing without them.")
            order = [i for i in order if not orch.is_down(i)]
            if not order:
                self._post(sid, "system", "Aether", "Every selected engineer is unavailable right now. Pick another engineer in the sidebar (or wait for the limit to reset).")
                return
            cands = [engs[i] for i in order]
            rt = orch.route(text, cands, bool(st.get("team", True)), [engs[i] for i in order] if mentioned else None)
            if rt.kind != "chat":
                st = self._project_dir(sid, text, st, target)
            if rt.kind != "chat" or len(cands) > 1:
                self._post(sid, "system", "Team", rt.label, {"phase": rt.kind})
            if rt.kind in ("standard", "deep") and len(rt.members) >= 2:
                self._team(sid, rt.members, cfg, st, target)
            elif rt.kind == "chat":
                for e in (rt.members if mentioned else [rt.lead]):
                    if sid in self.stopped:
                        break
                    self._run_covered(sid, e, cands, cfg, st, target, directive=CONVO if not mentioned else "", what="reply")
            else:   # quick: one engineer builds, tests and starts it, then a verified hand-over
                who, reply = self._run_covered(sid, rt.lead, cands, cfg, st, target, phase="build", directive=QUICK, what="build")
                if st["mode"] in ("edit", "auto") and self._changed_something(sid) and sid not in self.stopped:
                    self._auto_verify(sid, who, reply, cfg, st, target)
                    for rnd in (1, 2, 3):
                        auto_ok, auto = self._auto_checks(sid, st, target)
                        if auto:
                            self._post(sid, "shell", "Aether checks", auto, {"phase": "verify", "shell": True})
                            self._final[sid] = {"verdict": "FAIL" if auto_ok is False else "PASS", "auto_ok": auto_ok,
                                                "fails": self._failed_checks(auto)}
                        if auto_ok is not False or rnd == 3 or sid in self.stopped:
                            break
                        self._run_engineer(sid, who, cfg, st, target, phase="fix", directive=(
                            f"{auto[-4000:]}\n\nThese checks FAILED. Fix the cause, re-run the failing check yourself and show the output. Be brief."))
                    self._summarize(sid, who, cands, cfg, st, target)
            self._learn(sid, cfg)
        finally:
            self.procs.pop(sid, None)
            self.emit({"t": "idle", "sid": sid})
            try:
                self._run_queued(sid)
            except Exception:
                pass

    def _project_dir(self, sid: str, text: str, st: dict, target: dict | None) -> dict:
        """Build requests must not write into the home folder or Aether's own source: start a fresh project folder."""
        cwd = eff_cwd(st, target)
        app_dir = Path(__file__).resolve().parent
        if target is None:
            try:
                p = Path(os.path.expanduser(cwd)).resolve()
            except OSError:
                return st
            risky = p == Path.home().resolve() or p == app_dir or app_dir in p.parents
        else:
            risky = cwd.strip() in ("", "~", "~/")
        if not risky:
            return st
        slug = "-".join(re.findall(r"[a-z0-9]+", text.lower())[:5])[:32].strip("-") or "project"
        if target is None:
            base = Path.home() / "aether-projects"
            path, n = base / slug, 2
            while path.exists() and any(path.iterdir()):
                path, n = base / f"{slug}-{n}", n + 1
            path.mkdir(parents=True, exist_ok=True)
            new = str(path)
        else:
            new = f"~/aether-projects/{slug}"
            try:
                subprocess.run(ssh_argv(target, f"mkdir -p {new.replace('~', '$HOME', 1)}"), capture_output=True, timeout=20, env=ENV)
            except Exception:
                return st
        st = {**st, ("rcwd" if target else "cwd"): new}
        self.update_settings(sid, st)
        self.emit({"t": "settings", "sid": sid, "settings": st})
        self._post(sid, "system", "Aether", f"Working in a new project folder: {new}")
        return st

    def _substitute(self, sid: str, pool: list[dict], tried: set[str]) -> dict | None:
        """Next engineer who can take over: not down, not failed this turn, idle ones first."""
        bad = tried | self._failed_turn.get(sid, set())
        ok = [e for e in pool if e["id"] not in bad and not orch.is_down(e["id"])]
        busy = self._busy.get(sid, set())
        return next((e for e in ok if e["id"] not in busy), None) or (ok[0] if ok else None)

    def _run_covered(self, sid: str, eng: dict, pool: list[dict], cfg: dict, st: dict, target: dict | None,
                     directive="", phase: str = "", what: str = "task", accept=None) -> tuple[dict, str]:
        """Run `eng`; if it goes down, errors out or stops responding, hand the same work to the next available
        engineer in `pool`. `directive` may be a function of the engineer (e.g. the lead's plan prompt).
        `accept(eng)` may return a reply that already did the job even though a later round failed (e.g. the
        lead's plan, written before a provider error on its next call); then nobody takes over.
        Returns (engineer who finished, reply)."""
        make = directive if callable(directive) else (lambda e: directive)
        tried: set[str] = set()
        takeover = ""
        while True:
            tried.add(eng["id"])
            busy = self._busy.setdefault(sid, set())
            busy.add(eng["id"])
            try:
                text = self._run_engineer(sid, eng, cfg, st, target, directive=takeover + make(eng), phase=phase)
            finally:
                busy.discard(eng["id"])
            o = self._outcome.get((sid, eng["id"])) or {}
            if sid in self.stopped or not (o.get("failed") or orch.is_down(eng["id"])):
                return eng, text
            done = accept(eng) if accept else None
            if done:
                return eng, done
            why = (orch.down_reason(eng["id"]) or o.get("why") or "not responding").splitlines()[0][:90]
            sub = self._substitute(sid, pool, tried)
            if not sub:
                self._post(sid, "system", "Team", f"{eng['name']} could not finish the {what} ({why}) and no other engineer is available to take over.",
                           {"phase": phase or "work"})
                return eng, text
            self._post(sid, "system", "Team", f"Reassigned · {eng['name']} is unavailable ({why}) — {sub['name']} takes over the {what}.",
                       {"phase": phase or "work"})
            own = self._owners.get(sid) or {}
            for path, who in list(own.items()):
                if who == eng["name"]:
                    own[path] = sub["name"]
            takeover = (f"You are taking over from {eng['name']}, who stopped partway ({why}). Check the current state of "
                        "the files first (some work may already be done), then finish it.\n\n")
            eng = sub

    def _team(self, sid: str, members: list[dict], cfg: dict, st: dict, target: dict | None) -> None:
        """Lead plans & delegates → teammates work in turn (seeing each other) → lead reviews and answers."""
        lead = members[0]
        self._post(sid, "system", "Team", f"Plan · {lead['name']} leads, with {', '.join(m['name'] for m in members[1:])}", {"phase": "plan"})

        def plan_prompt(ld: dict) -> str:
            roster = "\n".join(f"- {m['name']}: {m['role']}" for m in members if m["id"] != ld["id"] and not orch.is_down(m["id"])
                               and m["id"] not in self._failed_turn.get(sid, set()))
            return (f"You are the TEAM LEAD for this request. Teammates:\n{roster}\n\n"
                    "Teammates work IN PARALLEL and cannot talk to each other, so your plan is the contract they all build to. "
                    "If the request is trivial (a question, a one-file change), answer or do it directly and delegate nothing. "
                    "Otherwise write the plan with exactly these headings:\n"
                    "## Goal\nOne line.\n"
                    "## Requirements\nEVERY requirement in the user's request as a checklist `- R1: ...`, `- R2: ...` — nothing left out; "
                    "the work is checked against this list.\n"
                    "## Architecture\nThe full file layout; the technology and exact versions (CDN/package URLs that really exist); "
                    "for every module/file: what it exports or exposes (exact function/class/element-id names and signatures) and what "
                    "it uses from which other file; how the app is started (command, free port via `freeport 8000`).\n"
                    "## Tasks\nOne line per teammate you use, in exactly this form:\n"
                    "@Name: what to build | files: path/one.js, path/two.css\n"
                    f"Every file has exactly ONE owner. Use only as many teammates as there are truly independent parts "
                    f"(at most {TEAM_MAX_WORKERS}; leave the others out — they cover for anyone who fails). Give related files to the "
                    "same person — above all, the page markup (HTML) and the script that drives it (ids, classes, events) belong "
                    "to ONE person, because mismatches between them are the most common bug. "
                    "Do NOT write any project files yourself now; you verify everything afterwards.\n"
                    "## Acceptance checks\nThe exact commands that prove it works (tests, syntax checks, starting it, the URL to load), "
                    "as a plain list — NOT in ```run blocks: Aether runs them when the work is verified, and nothing exists yet.\n"
                    "Libraries: pin ONE recent version for a library and all its add-ons (e.g. three@0.160.0 with an importmap "
                    "mapping `three` and `three/addons/` to that same version) — mixed versions load the library twice.\n"
                    "Assets: nobody on the team can download or write binary files (JPG/PNG/MP3). Plan images and textures as drawn "
                    "in code (<canvas> → THREE.CanvasTexture, CSS gradients, procedural noise) or as real .svg files — never as "
                    ".jpg/.png files the team would have to fake.")
        t_plan = time.time()

        def assigned(text: str) -> dict:
            """@Name: task lines in a plan, for every teammate who can still work."""
            out = {}
            for m in members:
                if orch.is_down(m["id"]) or m["id"] in self._failed_turn.get(sid, set()):
                    continue
                hit = re.search(rf"^\s*@{re.escape(m['name'])}\b\s*[:\-–]\s*(.+)$", text or "", re.I | re.M)
                if hit:
                    out[m["id"]] = hit.group(1).strip()
            return out

        def planned(eng: dict | None = None) -> str | None:
            """The first plan written this turn (by `eng`, or by anyone) that assigns work."""
            for author, text in self._phase_replies(sid, "plan", t_plan):
                if (eng is None or author == eng["name"]) and assigned(text):
                    return text
            return None

        lead, plan = self._run_covered(sid, lead, members, cfg, st, target, plan_prompt, phase="plan", what="lead role",
                                       accept=planned)
        tasks = assigned(plan)
        if not tasks and (earlier := planned()):
            # The first lead planned and then failed; its replacement started over without delegating.
            # The earlier plan is still the best one we have, so the team works from it.
            plan, tasks = earlier, assigned(earlier)
            self._post(sid, "system", "Team", "Using the plan written earlier this turn", {"phase": "plan"})
        if not tasks and not (len(plan) < 400 and not re.search(r"@\w+", plan)) and sid not in self.stopped:
            self._post(sid, "system", "Team", f"{lead['name']}'s plan has no task lines — asking for them.", {"phase": "plan"})
            lead, again = self._run_covered(sid, lead, members, cfg, st, target, lambda ld: plan_prompt(ld) + (
                "\n\nYour plan above stopped before its `## Tasks` section, so nobody can start. Do not repeat the rest: write "
                "ONLY the `## Tasks` lines (`@Name: what to build | files: …`, every file in your Architecture owned by exactly one "
                "person) and the `## Acceptance checks`."), phase="plan", what="lead role")
            if assigned(again):
                plan = again if "## Requirements" in again else plan.rstrip() + "\n\n" + again
                tasks = assigned(plan)
        if len(tasks) > TEAM_MAX_WORKERS:
            # Too many parallel writers make files that don't fit together. Fold the extra tasks into the first ones.
            ids = list(tasks)
            for k, extra in enumerate(ids[TEAM_MAX_WORKERS:]):
                host = ids[k % TEAM_MAX_WORKERS]
                tasks[host] = f"{tasks[host]}  ALSO: {tasks.pop(extra)}"
            self._post(sid, "system", "Team", f"The plan used {len(ids)} people; merged it into {TEAM_MAX_WORKERS} tasks so the "
                       "files are written by fewer hands and fit together.", {"phase": "plan"})
        if tasks:
            self._plan[sid] = plan
            names = {m["id"]: m["name"] for m in members}
            self._owners[sid] = self._parse_owners({names[i]: t for i, t in tasks.items() if i in names})
            orphans = self._adopt_orphans(sid, plan)
            if orphans:
                self._post(sid, "system", "Team", "Files in the Architecture that no task owned, now assigned: " +
                           ", ".join(f"{f} → {o}" for f, o in orphans.items()), {"phase": "plan"})
            self._save_plan(sid, plan, st, target)
        if (self._outcome.get((sid, lead["id"])) or {}).get("failed") and not tasks:
            return                                   # nobody could lead; the reason is already posted
        mates = [m for m in members if m["id"] != lead["id"] and not orch.is_down(m["id"])
                 and m["id"] not in self._failed_turn.get(sid, set())]
        solo_lead = not tasks and len(plan) < 400 and not re.search(r"@\w+", plan)   # lead handled a small request itself
        # The lead works too when the plan gave it a part (e.g. it took over from a lead that planned and failed).
        workers = [] if solo_lead else ([m for m in mates + [lead] if m["id"] in tasks] or mates[:TEAM_MAX_WORKERS])
        if workers:
            self._post(sid, "system", "Team", "Work · " + ", ".join(m["name"] for m in workers), {"phase": "work"})
        done: list[dict] = []
        pool = mates + [lead]                        # the lead is idle while the team works: last-resort cover

        def work(m):
            task = tasks.get(m["id"], "Contribute your part to the request, complementing the plan.")
            who, _ = self._run_covered(sid, m, pool, cfg, st, target, phase="work", what=f"task “{task[:60]}”", directive=(
                (f"Your part of the team plan: {task}\n" if m["id"] == lead["id"] else f"{lead['name']} (team lead) assigned you: {task}\n") +
                "Build it now, completely — no placeholders, TODOs or stubs. Follow the plan's Architecture exactly (same file "
                "paths, exported names, element ids, versions) so your part fits the others'. Write ONLY the files you own. "
                "The project file listing is above: do not re-list or re-read files you do not need. Before you finish, check "
                "your own files (syntax check, run your tests or a quick smoke test) and show the output. "
                "Other people's files may still be in progress: don't wait for them, don't re-read them repeatedly and never "
                "build them yourself. As soon as your own files are written and checked, STOP: reply with only the summary and "
                "no ```run or ```aether block. "
                "End with a 2-3 line summary: what you built, which names other files rely on, anything left open."))
            for _ in range(2):                        # an owner who stopped before writing all its files goes back
                missing = self._missing_files(sid, who["name"], st, target)
                if not missing or sid in self.stopped:
                    break
                self._post(sid, "system", "Team", f"{who['name']} has not written {', '.join(missing)} yet — sending it back.", {"phase": "work"})
                who, _ = self._run_covered(sid, who, pool, cfg, st, target, phase="work", what=f"task “{task[:60]}”", directive=(
                    f"You finished, but these files you own do not exist yet: {', '.join(missing)}. Write them now, complete "
                    "(no stubs), following the plan's Architecture, then check them and end with your summary."))
            done.append(who)
        # Teammates work in parallel, in waves of at most TEAM_MAX_WORKERS so they don't trip over each other.
        for i in range(0, len(workers), TEAM_MAX_WORKERS):
            threads = [threading.Thread(target=work, args=(m,)) for m in workers[i:i + TEAM_MAX_WORKERS]]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            if sid in self.stopped:
                break
        if sid in self.stopped or st["mode"] == "chat":
            return
        self._write_tests(sid, lead, mates, workers, pool, cfg, st, target)
        fixers = list({e["id"]: e for e in done}.values()) or [lead]
        self._verify(sid, lead, fixers, cfg, st, target, pool=[lead] + mates)
        self._summarize(sid, lead, [lead] + mates, cfg, st, target)

    @staticmethod
    def _parse_owners(tasks: dict[str, str]) -> dict[str, str]:
        """{engineer name: task line} → {path: engineer name} from the `| files: a, b` part of each task."""
        own: dict[str, str] = {}
        for name, task in tasks.items():
            m = re.search(r"\bfiles?\s*:\s*(.+)$", task, re.I)
            if not m:
                continue
            for raw in re.split(r"[,;]\s*|\s+(?:and|&)\s+|\s{2,}", m.group(1)):
                f = raw.strip().strip("`'\"*()[]").rstrip(".").strip()
                if not f or "*" in f or " " in f or not ("." in f or f.endswith("/")):
                    continue
                key = f if f.endswith("/") else os.path.normpath(f)
                own.setdefault(key, name)
        return own

    @staticmethod
    def _failed_checks(auto: str) -> list[str]:
        """'<check>: <first failure>' for each automatic check that failed."""
        out = []
        for block in (auto or "").split("\n\n$ ")[0:]:
            head = block.split("\n", 1)[0].lstrip("$ ").strip()
            if "[FAIL" not in block and "RESULT: FAIL" not in block:
                continue
            first = next((ln[6:].strip() for ln in block.splitlines() if ln.startswith("FAIL  ")), "")
            if not first:   # a test runner: show its last meaningful line
                first = next((ln.strip() for ln in reversed(block.splitlines()) if ln.strip() and not ln.startswith("[")), "")
            out.append(f"{head.split('   (')[0][:70]}: {first[:160]}")
        return out[:6]

    def _missing_files(self, sid: str, name: str | None, st: dict, target: dict | None) -> list[str]:
        """Planned files (owned by `name`, or by anyone when None) that are not in the project yet."""
        if target is not None:
            return []
        root = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
        return sorted(p_ for p_, o in (self._owners.get(sid) or {}).items()
                      if (name is None or o == name) and not p_.endswith("/") and p_ != self.E2E and not (root / p_).is_file())

    CODE_EXT = r"(?:html?|css|scss|m?js|jsx|tsx?|py|vue|svelte)"

    @classmethod
    def _arch_files(cls, plan: str) -> list[str]:
        """Source files the plan's Architecture section names: `a/b.js` paths, and names in a file tree (├── js/ … main.js)."""
        m = re.search(r"(?ims)^\s*#+\s*Architecture\b(.*?)(?=^\s*#+\s*Tasks\b|\Z)", plan or "")
        if not m:
            return []
        out: list[str] = []
        stack: list[tuple[int, str]] = []          # (depth, dir) for the tree being read
        for line in m.group(1).splitlines():
            tree = re.match(r"^([\s│|]*)(?:[├└]──|[|`]--|[-*]\s)?\s*([\w.@-]+/?)\s*(?:#.*)?$", line.split("  #")[0].rstrip())
            if tree and ("──" in line or "--" in line or re.match(r"^\s+[\w.@-]+/?\s*$", line.split("  #")[0])):
                depth = len(tree.group(1).replace("│", " ").replace("|", " "))
                name = tree.group(2)
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                if name.endswith("/"):
                    if depth > 0 or "──" in line:
                        stack.append((depth, name))
                    continue
                if re.fullmatch(rf"[\w.@-]+\.{cls.CODE_EXT}", name):
                    out.append(os.path.normpath("".join(d for _, d in stack) + name))
                continue
            for f in re.findall(rf"(?<![\w/.:-])((?:[\w@-]+/)+[\w.@-]+\.{cls.CODE_EXT})\b", line):
                if not f.startswith(("http", "node_modules/", "three/", "examples/", "build/")):
                    out.append(os.path.normpath(f))
        return [f for f in dict.fromkeys(out) if not f.startswith(("assets/", "tests/", "test/", ".aether/"))]

    def _adopt_orphans(self, sid: str, plan: str) -> dict[str, str]:
        """A file the Architecture needs but no task owns is never written (an entry js/main.js, say), and the team only
        finds out at verification. Give each one to the teammate with related work: the page owner gets entry points,
        otherwise the owner of a file in the same folder."""
        own = self._owners.get(sid)
        if not own:
            return {}
        given: dict[str, str] = {}
        page = next((o for f, o in own.items() if f.endswith((".html", ".htm"))), None)
        load = lambda n: sum(1 for o in own.values() if o == n)
        for f in self._arch_files(plan):
            if f in own or self._owner_of(sid, f):
                continue
            same_dir = [o for g, o in own.items() if os.path.dirname(g) == os.path.dirname(f) and not g.endswith("/")]
            base = os.path.basename(f).split(".")[0].lower()
            if page and (base in ("main", "app", "index", "entry", "bootstrap", "init") or not same_dir):
                who = page
            elif same_dir:
                who = min(dict.fromkeys(same_dir), key=load)
            else:
                who = min(dict.fromkeys(own.values()), key=load)
            own[f] = given[f] = who
        return given

    def _owner_of(self, sid: str, path: str) -> str | None:
        own = self._owners.get(sid) or {}
        return own.get(path) or next((o for p, o in own.items() if p.endswith("/") and path.startswith(p)), None)

    def _save_plan(self, sid: str, plan: str, st: dict, target: dict | None) -> None:
        """Keep the plan in the project (.aether/PLAN.md) so it outlives the chat window and later turns can read it."""
        if target is not None:
            return
        try:
            d = Path(os.path.expanduser(eff_cwd(st, target))).resolve() / ".aether"
            d.mkdir(exist_ok=True)
            (d / "PLAN.md").write_text(f"# Team plan\n\nRequest:\n\n{self._request.get(sid, '')}\n\n---\n\n{plan}\n")
        except OSError:
            pass

    SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".aether", ".cache", "target"}

    def _listing(self, st: dict, target: dict | None, limit: int = 150) -> str:
        """Files in the project with sizes, so engineers don't spend turns on `ls`/`cat` just to see what exists."""
        try:
            if target is not None:
                prune = " -o ".join(f"-name {d}" for d in sorted(self.SKIP_DIRS))
                r = subprocess.run(ssh_argv(target, f"{remote_cd(eff_cwd(st, target))} && find . \\( {prune} \\) -prune -o -type f -print | head -{limit}"),
                                   capture_output=True, text=True, timeout=20, env=ENV)
                rows = [ln[2:] for ln in r.stdout.splitlines() if ln.startswith("./")]
            else:
                base = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
                if base == Path.home().resolve():
                    return ""
                rows = []
                for dirpath, dirs, files in os.walk(base):
                    dirs[:] = sorted(d for d in dirs if d not in self.SKIP_DIRS)
                    for fn in sorted(files):
                        fp_ = Path(dirpath) / fn
                        try:
                            rows.append(f"{fp_.relative_to(base)}  ({fp_.stat().st_size} bytes)")
                        except OSError:
                            pass
                        if len(rows) >= limit:
                            break
                    if len(rows) >= limit:
                        break
            return "\n".join(rows) if rows else "(empty)"
        except Exception:
            return ""

    def _stop_project_servers(self, st: dict, target: dict | None) -> list[str]:
        """Stop servers left running from the project folder by earlier steps, so verification starts clean and
        the user isn't left with stray processes on random ports. Local projects only."""
        if target is not None or not shutil.which("lsof"):
            return []
        proj = str(Path(os.path.expanduser(eff_cwd(st, target))).resolve())
        if proj == str(Path.home().resolve()):
            return []
        stopped = []
        try:
            out = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"], capture_output=True, text=True, timeout=15).stdout
            pid, ports = None, {}
            for ln in out.splitlines():
                if ln.startswith("p"):
                    pid = int(ln[1:])
                elif ln.startswith("n") and pid:
                    ports.setdefault(pid, set()).add(ln.rsplit(":", 1)[-1])
            for pid, prt in ports.items():
                if pid == os.getpid():
                    continue
                cwd = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=10).stdout
                cwd = next((x[1:] for x in cwd.splitlines() if x.startswith("n")), "")
                if cwd == proj or cwd.startswith(proj + "/"):
                    try:
                        os.kill(pid, signal.SIGTERM)
                        stopped.append(f"pid {pid} (port {', '.join(sorted(prt))})")
                    except OSError:
                        pass
        except Exception:
            pass
        return stopped

    WEB_DIRS = ("", "public", "dist", "docs", "site", "web", "www", "app", "frontend", "client")
    E2E = ".aether/e2e.json"

    def _web_root(self, st: dict, target: dict | None) -> Path | None:
        if target is not None:
            return None
        root = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
        return next((root / d for d in self.WEB_DIRS if (root / d / "index.html").is_file()), None)

    def _write_tests(self, sid: str, lead: dict, mates: list[dict], workers: list[dict], pool: list[dict], cfg: dict,
                     st: dict, target: dict | None) -> None:
        """A page's features are only proven by using them. After the builders, an agent who did not build it writes
        browser acceptance steps for every UI requirement (.aether/e2e.json); Aether runs them in every verification."""
        if self._web_root(st, target) is None or sid in self.stopped:
            return
        busy = {w["id"] for w in workers}
        tester = next((m for m in mates if m["id"] not in busy and not orch.is_down(m["id"])
                       and m["id"] not in self._failed_turn.get(sid, set())), lead)
        self._owners.setdefault(sid, {})[self.E2E] = tester["name"]
        self._post(sid, "system", "Team", f"Test · {tester['name']} writes browser acceptance tests for the requirements", {"phase": "work"})
        usage = ('[{"click": "#new-card-btn"}, {"expect": "#card-modal", "visible": true}, {"submit": "#card-form"}, '
                 '{"expect": "#card-title-error", "visible": true}, {"type": ["#card-title", "Buy milk"]}, {"submit": "#card-form"}, '
                 '{"expect": "#card-modal", "visible": false}, {"expect": ".card", "text": "Buy milk"}, {"reload": true}, '
                 '{"expect": ".card", "text": "Buy milk"}, {"press": "n", "on": "body"}, {"press": "Escape"}, '
                 '{"drag": [".card", ".column:last-child"]}, {"select": ["#filter", "high"]}, {"expect": ".card", "count": 1}, '
                 '{"eval": "localStorage.length > 0", "equals": true}, {"wait": 300}]')
        self._run_covered(sid, tester, pool, cfg, st, target, phase="test", what="acceptance tests", directive=(
            "You are the TESTER. The builders have finished; you did not build this, so test it like a user would. Write the file "
            f"`{self.E2E}`: ONE JSON list of browser steps that check EVERY requirement in the plan that a user can see or do "
            "(open/close dialogs, create/edit/delete, validation messages, search/filters, keyboard shortcuts, persistence after "
            "reload, theme…). Steps run in order in one real page (headless Chrome) and each must pass:\n"
            f"{usage}\n"
            "Actions: click SEL, type [SEL, text], select [SEL, value], press KEY (+ \"on\": SEL), submit FORM, drag [from, to], "
            "wait MS, reload. Checks: expect SEL (+ \"visible\": true/false, \"text\": \"…\", \"count\": N), eval JS (+ \"equals\": value).\n"
            "Read index.html and the scripts first and use their REAL ids and classes. Put an expect after every action so a "
            "broken feature fails. Pure JSON: no comments, no trailing commas. Start the page with `aserve .` (once) and run your "
            f"steps against the URL it prints: `{VERIFY_PY} <url> --no-clicks --steps {self.E2E}`. "
            "If a step fails because the APP is broken, keep the step (that is a real bug for the builders) and list it; fix a "
            "step only when the step itself is wrong. Do not change any other file. End with: how many steps, which failed and why.\n"
            "The example above is from another app — use THIS project's ids. " + self._e2e_starter(st, target)))
        for _ in range(2):
            why = self._e2e_problem(st, target)
            if not why or sid in self.stopped:
                break
            self._post(sid, "system", "Team", f"{tester['name']}: {why} — sending it back.", {"phase": "work"})
            tester, _ = self._run_covered(sid, tester, pool, cfg, st, target, phase="test", what="acceptance tests", directive=(
                f"{why}. Write `{self.E2E}` now with one ```aether block: a JSON list of at least {self.E2E_MIN} steps that check every "
                "user-visible requirement, using the real ids/classes in index.html and the scripts. Then run it as described above.\n"
                + self._e2e_starter(st, target)))

    E2E_MIN = 8

    def _e2e_problem(self, st: dict, target: dict | None) -> str | None:
        root = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
        f = root / self.E2E
        if not f.is_file():
            return f"{self.E2E} was not written"
        try:
            steps = json.loads(f.read_text())
        except ValueError as exc:
            return f"{self.E2E} is not valid JSON ({str(exc)[:80]})"
        if isinstance(steps, dict):
            steps = next((v for v in steps.values() if isinstance(v, list)), steps)
            if isinstance(steps, list):
                return (f"{self.E2E} is an object wrapping the list; it must be the bare JSON list of steps itself, "
                        f"[{{\"click\": \"#id\"}}, {{\"expect\": \"#id\", \"visible\": true}}, …]")
        if not isinstance(steps, list):
            return f"{self.E2E} must be a JSON list of step objects"
        words = [x for x in steps if isinstance(x, str)]
        if words:
            return (f"{self.E2E} lists {len(words)} sentences like \"{words[0][:60]}\" — a person's checklist, which a browser "
                    "can't run. Each step must be an object with one action or check, e.g. {\"click\": \"#id\"} then "
                    "{\"expect\": \"#id\", \"visible\": true}")
        bad = [x for x in steps if not (isinstance(x, dict) and set(x) & self.E2E_KEYS)]
        if bad:
            return (f"{self.E2E} has {len(bad)} step(s) with no known action, e.g. {json.dumps(bad[0])[:80]}. Known: "
                    + ", ".join(sorted(self.E2E_KEYS)))
        if len(steps) < self.E2E_MIN:
            return f"{self.E2E} has {len(steps)} steps; it needs at least {self.E2E_MIN} covering the requirements"
        return None

    E2E_KEYS = {"click", "type", "select", "press", "submit", "wait", "expect", "eval", "drag", "reload"}

    def _e2e_starter(self, st: dict, target: dict | None) -> str:
        """A few valid steps built from the page's real buttons and ids: a template the tester extends, so it can't
        mistake the format (free models write sentences, or copy the generic example's ids)."""
        root = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
        page = root / "index.html"
        if not page.is_file():
            return ""
        html = page.read_text(errors="replace")
        buttons = re.findall(r"<button[^>]*\bid\s*=\s*[\"']([\w-]+)", html)[:3]
        ids = [i for i in re.findall(r"\bid\s*=\s*[\"']([\w-]+)", html) if i not in buttons][:3]
        steps = [{"expect": f"#{ids[0]}", "visible": True}] if ids else []
        for b in buttons:
            steps += [{"click": f"#{b}"}, {"expect": f"#{ids[-1] if ids else b}", "visible": True}]
        steps.append({"eval": "document.querySelectorAll('canvas').length > 0" if "canvas" in html.lower() else
                      "document.body.innerText.length > 0", "equals": True})
        return ("Start from these steps (real ids from index.html) and replace each `expect` with what that button must "
                "really change:\n" + json.dumps(steps))



    def _auto_checks(self, sid: str, st: dict, target: dict | None) -> tuple[bool | None, str]:
        """Checks Aether runs ITSELF, so a model can't talk its way past them: the project's tests, a Python compile
        check, and a real-browser check (verify_web.py) of a static site. Returns (all passed?, report);
        (None, "") when there is nothing it knows how to check, or the project is on another machine."""
        if target is not None:
            return None, ""
        root = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
        if root == Path.home().resolve() or not root.is_dir():
            return None, ""
        report, ok, ran = [], True, False

        def run(cmd: str, timeout: int = 240) -> tuple[int, str]:
            try:
                r = subprocess.run(["/bin/bash", "-lc", cmd], cwd=root, capture_output=True, text=True, timeout=timeout, env=ENV)
                return r.returncode, (r.stdout + r.stderr)
            except subprocess.TimeoutExpired:
                return 124, f"[stopped after {timeout}s]"

        files = [f for f in root.rglob("*") if f.is_file() and not (set(f.relative_to(root).parts) & self.SKIP_DIRS)]
        rel = [str(f.relative_to(root)) for f in files]
        tests = []
        try:
            scripts = json.loads((root / "package.json").read_text()).get("scripts", {}) if (root / "package.json").exists() else {}
        except ValueError:
            scripts = {}
        if scripts.get("test") and "no test specified" not in scripts["test"] and not scripts["test"].strip().startswith("node --test"):
            tests.append("npm test --silent" if (root / "node_modules").is_dir() or "node --test" in scripts["test"] else "npm install --silent && npm test --silent")
        elif tfiles := sorted(r for r in rel if re.search(r"\.(test|spec)\.[cm]?js$|(^|/)(tests?|__tests__)/[^/]+\.[cm]?js$", r)):
            # Name the files: `node --test tests/` treats the folder as a file on newer Node versions.
            tests.append("node --test " + " ".join(shlex.quote(t) for t in tfiles[:60]))
        py = [r for r in rel if r.endswith(".py")]
        if py:
            tests.append("python3 -m compileall -q " + " ".join(sorted({r.split("/")[0] for r in py})[:20]))
            if any(re.search(r"(^|/)test_[^/]*\.py$|_test\.py$", r) for r in py):
                uses_pytest = any("import pytest" in (root / r).read_text(errors="replace") for r in py if "test" in r)
                tdir = next((d for d in ("tests", "test") if (root / d).is_dir()), ".")
                tests.append("python3 -m pytest -q" if uses_pytest and shutil.which("pytest") else f"python3 -m unittest discover -s {tdir}")
        self._auto_cmds[sid] = list(tests)
        for cmd in tests:
            ran = True
            code, out = run(cmd)
            ok &= code == 0
            report.append(f"$ {cmd}\n{self._clip(out.strip(), 2500, 1500)}\n[{'PASS' if code == 0 else 'FAIL'}: exit {code}]")
        planned = [p_ for p_ in (self._owners.get(sid) or {}) if not p_.endswith("/") and p_ != self.E2E]
        if planned:
            ran = True
            missing = self._missing_files(sid, None, st, target)
            stubs = []
            for p_ in planned:
                f = root / p_
                if f.is_file() and f.suffix in (".js", ".mjs", ".ts", ".tsx", ".jsx", ".py", ".go", ".rs", ".java", ".rb", ".php"):
                    txt = f.read_text(errors="replace")
                    if re.search(r"(?://|#)\s*TODO\b|not implemented|NotImplementedError|placeholder implementation", txt, re.I):
                        stubs.append(p_)
            ok &= not missing and not stubs
            report.append("$ deliverables: every file in the plan exists and is not a stub\n"
                          + "".join(f"FAIL  {p_} is in the plan but was never written\n" for p_ in missing)
                          + "".join(f"FAIL  {p_} still has TODO / not-implemented parts\n" for p_ in stubs)
                          + (f"[FAIL]" if missing or stubs else f"OK    all {len(planned)} planned files are there\n[PASS]"))
        if any(r.endswith((".js", ".mjs", ".cjs", ".jsx", ".html")) for r in rel):
            ran = True
            try:
                import contract_check
                problems = contract_check.check(root)
            except Exception as exc:
                problems = []
                report.append(f"(contract check could not run: {exc})")
            ok &= not problems
            report.append("$ contract check: imports vs exports, referenced files, element ids\n" +
                          ("\n".join("FAIL  " + x for x in problems[:25]) or "OK    all match") +
                          f"\n[{'FAIL' if problems else 'PASS'}]")
        web = next((root / d for d in self.WEB_DIRS if (root / d / "index.html").is_file()), None)
        if web is not None:
            ran = True
            port = fp.first_free(8000)
            srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0"], cwd=web,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(0.8)
            url = f"http://127.0.0.1:{port}/"
            e2e = root / self.E2E
            steps = f" --steps {shlex.quote(str(e2e))}" if e2e.is_file() else ""
            if self.E2E in (self._owners.get(sid) or {}) and (why := self._e2e_problem(st, target)):
                ok = False
                report.append(f"$ acceptance tests\nFAIL  {why} — features can't be shown to work without them\n[FAIL]")
            code, out = run(f"{VERIFY_PY} {url}{steps}", timeout=300)
            self._auto_cmds.setdefault(sid, []).append(f"{VERIFY_PY} {url}" + (f" --steps {self.E2E}" if steps else ""))
            ok &= code == 0
            report.append(f"$ verify_web {url}{' --steps ' + self.E2E if steps else ''}   (served from {web.relative_to(root) or '.'}; still running, pid {srv.pid})\n"
                          f"{self._clip(out.strip(), 3000, 1000)}")
            self._auto_url[sid] = url
        if not ran:
            return None, ""
        return ok, "AUTOMATIC CHECKS (run by Aether itself, not by a model — these results are facts):\n\n" + "\n\n".join(report)

    def _phase_replies(self, sid: str, phase: str, since: float) -> list[tuple[str, str]]:
        """(author, text) of the engineers' replies in `phase` since `since`, oldest first."""
        with db() as c:
            rows = c.execute("SELECT author, content, meta FROM messages WHERE session_id=? AND role='assistant' AND ts>=? "
                             "ORDER BY ts", (sid, since)).fetchall()
        out = []
        for r in rows:
            try:
                if json.loads(r["meta"] or "{}").get("phase") == phase:
                    out.append((r["author"], r["content"] or ""))
            except ValueError:
                pass
        return out

    def _summarize(self, sid: str, lead: dict, pool: list[dict], cfg: dict, st: dict, target: dict | None) -> None:
        """The lead's closing hand-over (phase "summary"; the UI shows the latest one in its side panel)."""
        if sid in self.stopped:
            return
        self._post(sid, "system", "Team", f"Summary · {lead['name']} wraps up", {"phase": "summary"})
        url = self._auto_url.get(sid)
        extra = f"\nAether is serving the project at {url} (on the machine where it runs); give that URL in How to run." if url else ""
        fin = self._final.get(sid) or {}
        failed = fin.get("verdict") == "FAIL" or fin.get("auto_ok") is False
        if failed:
            extra += ("\nIMPORTANT: the final verification FAILED" + (":\n" + "\n".join(fin.get("fails") or []) if fin.get("fails") else ".") +
                      "\nSay so in Result, mark the affected requirements ✗ (or ? when unchecked), and list these failures first under Open issues.")
        self._run_covered(sid, lead, pool, cfg, st, target, SUMMARY + extra, phase="summary", what="summary")
        if fin:
            if failed:
                self._post(sid, "system", "Aether", "Final check: FAILED — the work is not finished. " +
                           (" · ".join(fin.get("fails") or [])[:700] or "See the verification above.") +
                           " Ask the team to continue (e.g. \"fix the failing checks\") or fix it by hand.", {"phase": "summary"})
            else:
                self._post(sid, "system", "Aether", "Final check: PASSED" + (" (Aether's automatic checks and the lead's verification)."
                           if fin.get("auto_ok") else " (the lead's verification)."), {"phase": "summary"})

    URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\d{1,3}(?:\.\d{1,3}){3}):\d+[^\s)\]>\"'`*]*")

    def _auto_verify(self, sid: str, eng: dict, reply: str, cfg: dict, st: dict, target: dict | None) -> None:
        """No model call: the app itself opens the page the engineer reported (headless Chrome) and posts the evidence.
        One repair round if it fails."""
        urls = list(dict.fromkeys(self.URL_RE.findall(reply)))
        if not urls:
            return
        for rnd in (1, 2):
            url = urls[-1].replace("0.0.0.0", "127.0.0.1")
            if target:
                url = re.sub(r"//(?:localhost|127\.0\.0\.1)", f"//{target['host']}", url)
            self._post(sid, "system", "Team", f"Verify · checking {url} in a real browser" + (" (re-check)" if rnd > 1 else ""), {"phase": "verify"})
            foreign = None if target else self._foreign_server(url, eff_cwd(st, target))
            if foreign:
                self._post(sid, "shell", "Verify", f"$ verify {url}\nFAIL  {foreign}\n\nVERDICT: FAIL", {"phase": "verify"})
                if rnd == 2 or sid in self.stopped:
                    self._post(sid, "system", "Team", "Still failing after one repair round — handing back with the failures above.", {"phase": "verify"})
                    return
                self._run_engineer(sid, eng, cfg, st, target, phase="fix", directive=(
                    f"{foreign}\nStart YOUR server on a free port: run `freeport 8000` (or `aserve <dir>`), use exactly the port it prints, "
                    "and report that URL. Do not stop the other program."))
                continue
            try:
                r = subprocess.run([PY_FOR_TOOLS, str(Path(__file__).parent / "verify_web.py"), url],
                                   capture_output=True, text=True, timeout=90, env=ENV)
                out, ok = (r.stdout + r.stderr).strip(), r.returncode == 0
            except Exception as exc:
                out, ok = f"verifier error: {exc}", False
            self._post(sid, "shell", "Verify", f"$ verify_web.py {url}\n{out}\n\nVERDICT: {'PASS' if ok else 'FAIL'}", {"phase": "verify"})
            if ok or rnd == 2 or sid in self.stopped:
                if not ok:
                    self._post(sid, "system", "Team", "Still failing after one repair round — handing back with the failures above.", {"phase": "verify"})
                return
            self._run_engineer(sid, eng, cfg, st, target, phase="fix", directive=(
                f"An automatic browser check of {url} FAILED:\n{out[-1800:]}\n\nFix the cause, restart the server if needed, "
                "and report the working URL. Be brief."))

    def _foreign_server(self, url: str, project: str) -> str | None:
        """If the port in `url` is held by a process that is not running from this project, say so."""
        m = re.search(r":(\d+)", url)
        if not m:
            return None
        try:
            pid = subprocess.run(["lsof", "-nP", f"-iTCP:{m.group(1)}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=10).stdout.split()
            if not pid:
                return None
            proj = str(Path(os.path.expanduser(project)).resolve())
            cmd = subprocess.run(["ps", "-p", pid[0], "-o", "command="], capture_output=True, text=True, timeout=5).stdout.strip()
            cwd = subprocess.run(["lsof", "-a", "-p", pid[0], "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=10).stdout
            cwd = next((ln[1:] for ln in cwd.splitlines() if ln.startswith("n")), "")
            if proj in cmd or (cwd and (cwd == proj or cwd.startswith(proj + "/"))) or re.search(r"docker|rootlessport|vpnkit|colima|podman", cmd, re.I):
                return None
            return (f"Port {m.group(1)} is served by a different program (pid {pid[0]}, running from {cwd or 'unknown folder'}), "
                    f"not by this project ({proj}).")
        except Exception:
            return None

    def _changed_something(self, sid: str) -> bool:
        """Did the last engineer run write/run anything (tools used)? Questions don't need verifying."""
        return sid in self._acted

    def _verify(self, sid: str, lead: dict, fixers: list[dict], cfg: dict, st: dict, target: dict | None, pool: list[dict] | None = None) -> None:
        """The lead tests the work for real (another engineer covers if the lead is down). Repair rounds on an explicit FAIL,
        up to VERIFY_ROUNDS verifications; the fixers get the findings themselves, not "read above"."""
        pool = pool or [lead, *fixers]
        for rnd in range(1, VERIFY_ROUNDS + 1):
            stray = self._stop_project_servers(st, target)
            if stray:
                self._post(sid, "system", "Aether", "Stopped servers left running by earlier steps: " + ", ".join(stray), {"phase": "verify"})
            if orch.is_down(lead["id"]) or lead["id"] in self._failed_turn.get(sid, set()):
                lead = self._substitute(sid, pool, set()) or lead
            auto_ok, auto = self._auto_checks(sid, st, target) if st["mode"] in ("edit", "auto") else (None, "")
            if auto:
                self._post(sid, "shell", "Aether checks", auto, {"phase": "verify", "shell": True})
            self._post(sid, "system", "Team", f"Verify · {lead['name']} tests the work" + (" (re-check)" if rnd > 1 else ""), {"phase": "verify"})
            directive = VERIFY + (f"\n\n{auto}\n\nIf an automatic check FAILED, your verdict is FAIL: find the cause in the code and "
                                  "name the file and the fix." if auto else "")
            lead, out = self._run_covered(sid, lead, pool, cfg, st, target, directive, phase="verify", what="verification")
            found = re.findall(r"VERDICT:\s*(PASS|FAIL|UNVERIFIED)", out)
            verdict = found[-1] if found else "UNVERIFIED"          # no marker is not a failure — nothing to repair
            if auto_ok is False and verdict != "FAIL":
                self._post(sid, "system", "Aether", f"{lead['name']} said {verdict}, but Aether's automatic checks failed — "
                           "treating it as FAIL.", {"phase": "verify"})
                verdict = "FAIL"
                out = auto + "\n\n" + out
            elif auto_ok is False:
                out = auto + "\n\n" + out
            tools = (self._last.get(sid) or {}).get("tools") or []
            if tools and not any(t.get("state") == "done" for t in tools) and verdict == "FAIL":
                verdict = "UNVERIFIED"                               # every command was refused: that is a permission issue, not a bug
                self._post(sid, "system", "Aether", f"{lead['name']} could not run any command in {st['mode']} mode, so nothing was verified. Switch the mode to Auto (or approve its command requests) and ask again.")
            self._final[sid] = {"verdict": verdict, "auto_ok": auto_ok, "fails": self._failed_checks(auto)}
            if verdict != "FAIL" or sid in self.stopped:
                return
            if rnd == VERIFY_ROUNDS:
                self._post(sid, "system", "Team", f"Still failing after {VERIFY_ROUNDS - 1} repair rounds — handing back with the failures listed above.", {"phase": "verify"})
                return
            findings = out[-5000:]
            # Send each failure to whoever owns the file it names, so nobody answers "not my file" and nobody idles.
            own = self._owners.get(sid) or {}
            by_name = {m["name"]: m for m in pool}
            named = [o for path, o in own.items() if not path.endswith("/") and path != self.E2E
                     and re.search(rf"(?<![\w/.-]){re.escape(path)}(?![\w-])", findings)]
            # A failing browser step names ids/classes, not files: the owners of the files that contain them fix it.
            step_fails = [ln for ln in findings.splitlines() if ln.startswith("FAIL") and "step " in ln]
            sels = set(re.findall(r"[#.]([A-Za-z][\w-]{2,})", " ".join(step_fails)))
            if sels:
                root = Path(os.path.expanduser(eff_cwd(st, target))).resolve()
                for path, o in own.items():
                    f = root / path
                    if path != self.E2E and f.is_file() and f.suffix in (".html", ".js", ".mjs", ".css", ".jsx", ".ts", ".tsx"):
                        txt = f.read_text(errors="replace")
                        if any(x in txt for x in sels):
                            named.append(o)
            targeted = [by_name[n] for n in dict.fromkeys(named) if n in by_name and not orch.is_down(by_name[n]["id"])]
            # Several people fixing at once undo each other (one renames the ids in the HTML, another in the script).
            # One integrator per round fixes everything; it rotates through the owners of the failing files.
            cands = targeted or [m for m in fixers if not orch.is_down(m["id"])] or [lead]
            fixers = [cands[(rnd - 1) % len(cands)]]
            recheck = [c for c in self._auto_cmds.get(sid, []) if "verify_web" not in c]
            recheck.append(f"{PY_FOR_TOOLS} {Path(__file__).parent / 'contract_check.py'} .")
            recheck += [c for c in self._auto_cmds.get(sid, []) if "verify_web" in c]
            again_cmd = ("Then run ALL of these (not only the one that failed — a fix must not break the rest) and show the output; "
                         "the job only passes when every one passes:\n" +
                         "\n".join(f"  {c}" for c in recheck) + "\n") if recheck else "Then re-run the failing check yourself and show the output.\n"
            self._post(sid, "system", "Team", f"Fix · {', '.join(m['name'] for m in fixers)} repair what failed (round {rnd})", {"phase": "work"})

            def fix_directive(m):
                mine = sorted(p_ for p_, o in own.items() if o == m["name"])
                return (f"You are the INTEGRATOR for this repair round: the work was tested and it FAILED. The findings:\n\n{findings}\n\n"
                        + (f"(You wrote: {', '.join(mine)}.) " if mine else "")
                        + "Fix ALL of these problems yourself, in any file — nobody else is changing files now. Make the files agree "
                        "with the plan's Architecture (the contract); where it says nothing, change the fewest files. Read the files "
                        "involved before you edit them, and write each changed file complete. Do not edit .aether/e2e.json unless a step "
                        "is plainly invalid. Unit tests passing is not enough: the failing checks must pass. " + again_cmd + "Be brief.")
            threads = [threading.Thread(target=lambda m=m: self._run_covered(sid, m, pool, cfg, st, target, phase="fix", what="fix",
                directive=fix_directive(m))) for m in fixers
                if not orch.is_down(m["id"])] or [threading.Thread(target=lambda: self._run_covered(
                    sid, lead, pool, cfg, st, target, phase="fix", what="fix",
                    directive=f"Your test FAILED. The findings:\n\n{findings}\n\nFix the problems, then re-run the failing check and show the output. Be brief."))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

    def _learn(self, sid: str, cfg: dict) -> None:
        """Background: distil durable facts + a session summary from the latest exchange (one fast Haiku call)."""
        if not cfg.get("auto_memory", True) or sid in self.stopped:
            return
        threading.Thread(target=self._learn_now, args=(sid,), daemon=True).start()

    def _learn_now(self, sid: str) -> None:
        try:
            with db() as c:
                recent = [row_msg(r) for r in c.execute(
                    "SELECT * FROM messages WHERE session_id=? AND role IN ('user','assistant') ORDER BY ts DESC LIMIT 8", (sid,))][::-1]
                prev = (c.execute("SELECT summary FROM sessions WHERE id=?", (sid,)).fetchone() or {"summary": ""})["summary"] or ""
            if not recent:
                return
            known = "\n".join(f"- {m['text']}" for m in self.list_memory()[-60:]) or "(none)"
            convo = "\n".join(f"[{m['author']}]: {m['content'][:1200]}" for m in recent)
            prompt = (
                "You maintain a team's long-term memory. From the conversation below extract ONLY durable facts worth "
                "remembering in future sessions: user preferences, project details, decisions, environment facts "
                "(hosts, paths, stack), recurring constraints. Skip chit-chat and one-off answers. If the user explicitly asks to remember something, always include it. Do not repeat facts already known (listed below).\n"
                f"Already known:\n{known}\n\nPrevious session summary: {prev or '(none)'}\n\nConversation:\n{convo}\n\n"
                'Reply with ONLY JSON: {"facts": ["short fact", ...], "summary": "one sentence on what this session is about"}. '
                'Use at most 5 facts; "facts": [] if nothing new.')
            r = subprocess.run(["claude", "-p", "--model", "haiku", "--tools", "", "--no-session-persistence",
                                "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", ""],
                               input=prompt, capture_output=True, text=True, timeout=60, env=ENV, cwd=str(Path.home()))
            out = r.stdout
            data = json.loads(out[out.index("{"):out.rindex("}") + 1])
        except Exception:
            return
        changed = False
        for fact in (data.get("facts") or [])[:5]:
            if isinstance(fact, str) and 3 < len(fact.strip()) <= 240:
                before = len(self.list_memory())
                if len(self.add_memory(fact.strip(), "auto")) > before:
                    changed = True
        summ = data.get("summary")
        if isinstance(summ, str) and summ.strip():
            with db() as c:
                c.execute("UPDATE sessions SET summary=? WHERE id=?", (summ.strip()[:200], sid))
        # keep auto-learned memory bounded: drop the oldest beyond 100
        with db() as c:
            c.execute("DELETE FROM memory WHERE source='auto' AND id NOT IN "
                      "(SELECT id FROM memory WHERE source='auto' ORDER BY ts DESC LIMIT 100)")
        self.emit({"t": "memory", "memory": self.list_memory(), "learned": changed})

    def _post(self, sid: str, role: str, author: str, content: str, meta: dict | None = None, mid: str | None = None):
        mid = mid or uid()
        with db() as c:
            c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                      (mid, sid, time.time(), role, author, content, json.dumps(meta or {})))
        self.emit({"t": "message", "sid": sid, "message": {"id": mid, "role": role, "author": author,
                                                          "content": content, "meta": meta or {}}})

    def _history(self, sid: str, eng: dict, phase: str) -> tuple[list[dict], int]:
        """Which past messages an engineer sees, and how much of each.
        - work/fix/build in a team job: its own replies and the output of its own commands and file writes.
        - verify/summary: every engineer's latest reply this turn plus the latest messages.
        - otherwise (chat, plan): the last CONTEXT_MESSAGES messages, as before."""
        team_job = sid in self._turn_t0 and phase in ("work", "fix", "build", "test", "verify", "summary")
        with db() as c:
            if not team_job:
                return [row_msg(r) for r in c.execute("SELECT * FROM messages WHERE session_id=? ORDER BY ts DESC LIMIT ?",
                                                      (sid, CONTEXT_MESSAGES))][::-1], MAX_MSG_CHARS
            rows = [row_msg(r) for r in c.execute("SELECT * FROM messages WHERE session_id=? AND ts>=? ORDER BY ts",
                                                  (sid, self._turn_t0[sid]))]
        rows = [m for m in rows if m["role"] in ("assistant", "shell")]
        if phase == "build":
            # A single engineer doing the whole job: also show the conversation before this request (follow-ups).
            with db() as c:
                prior = [row_msg(r) for r in c.execute("SELECT * FROM messages WHERE session_id=? AND ts<? AND role IN ('user','assistant') "
                                                       "ORDER BY ts DESC LIMIT 6", (sid, self._turn_t0[sid]))][::-1]
            mine = [m for m in rows if (m["role"] == "assistant" and m["author"] == eng["name"])
                    or (m["role"] == "shell" and m["meta"].get("by") == eng["name"])]
            return prior + mine[-OWN_THREAD_MESSAGES:], OWN_MSG_CHARS
        if phase in ("work", "fix", "test"):
            mine = [m for m in rows if (m["role"] == "assistant" and m["author"] == eng["name"])
                    or (m["role"] == "shell" and m["meta"].get("by") == eng["name"])]
            return mine[-OWN_THREAD_MESSAGES:], OWN_MSG_CHARS
        latest = {}
        for m in rows:
            if m["role"] == "assistant" and m["meta"].get("phase") in ("work", "fix", "build"):
                latest[m["author"]] = m
        tail = rows[-12:]
        keep = [m for m in latest.values() if m not in tail] + tail
        return sorted(keep, key=lambda m: m["ts"]), 1800

    def _prompt(self, sid: str, eng: dict, cfg: dict, st: dict, target: dict | None, directive: str = "", proxy: bool = False,
                phase: str = "") -> str:
        hist, max_chars = self._history(sid, eng, phase)
        with db() as c:
            others = c.execute("SELECT title, summary FROM sessions WHERE id!=? AND archived=0 ORDER BY updated DESC LIMIT 6", (sid,)).fetchall()
        team = ", ".join(f'{e["name"]} ({e["role"]})' for e in cfg["engineers"] if e["id"] != eng["id"]) or "none"
        where = f'on {target["user"]}@{target["host"]} (SSH)' if target else "on the user's Mac"
        proxy_note = ""
        is_api = eng["provider"] == API
        if proxy and target and not is_api:
            prefix = " ".join(shlex.quote(a) for a in ssh_argv(target, "X")[:-1])
            proxy_note = (f"IMPORTANT: your own shell runs on the user's Mac, but the project lives on the remote Ubuntu VM "
                          f"{target.get('user', '')}@{target['host']}, folder {eff_cwd(st, target)}. Run EVERY command there with: "
                          f"{prefix} '{remote_cd(eff_cwd(st, target))} && <command>'. Create/edit remote files through ssh "
                          f"(e.g. heredocs). Do not change anything on the Mac. If you cannot run shell commands in this mode, "
                          f"say so and tell the user to switch to Auto mode.\n")
        mem = "\n".join(f"- {m['text']}" for m in self.list_memory()[-60:]) or "(empty)"
        lines = []
        for i, m in enumerate(hist):
            # In an agent's own thread the latest few outputs come whole (a file it just read), older ones shorter.
            lim = 10_000 if max_chars == OWN_MSG_CHARS and i >= len(hist) - 3 else max_chars
            body = m["content"][:lim] + (" […cut]" if len(m["content"]) > lim else "")
            if m["role"] == "user":
                lines.append(f"[User]: {body}")
            elif m["role"] == "assistant":
                lines.append(f"[{m['author']}]: {body}")
            elif m["role"] == "shell":
                lines.append(f"[Shell output]: {body}")
        return (
            f"You are {eng['name']}, {eng['role']}, in a shared team chat with the user and: {team}.\n"
            f"Working directory {where}: {eff_cwd(st, target)}  |  permission mode: {st['mode']}.\n"
            f"{proxy_note}{DOD if st['mode'] in ('edit', 'auto') else ''}{RUN_NOTE if st['mode'] in ('plan', 'edit') or (is_api and st['mode'] == 'auto') else ''}"
            f"{API_NOTE if is_api and st['mode'] in ('edit', 'auto') else ''}Be concise. Use your tools to act when asked. Replies from teammates appear in the transcript as [Name].\n"
            f"If you learn a durable fact worth keeping across sessions, add a line `REMEMBER: <fact>` at the end.\n\n"
            f"Shared memory:\n{mem}\n\n"
            f"Other recent sessions: {'; '.join(r['title'] + (' — ' + r['summary'] if r['summary'] else '') for r in others) or 'none'}\n\n"
            f"{self._pinned(sid, eng, st, target, phase)}"
            f"{'Your work so far (your replies and the output of your own commands):' if phase in ('work', 'fix', 'build', 'test') and sid in self._turn_t0 else 'Conversation so far:'}\n"
            + "\n\n".join(lines) + f"\n\n{directive or 'Reply now as ' + eng['name'] + '.'}"
        )

    def _pinned(self, sid: str, eng: dict, st: dict, target: dict | None, phase: str) -> str:
        """Blocks every engineer keeps seeing however long the job runs: the request, the plan, its files, the project."""
        if not phase or phase == "chat":
            return ""
        out = []
        req = self._request.get(sid, "")
        if req:
            out.append(f"THE USER'S REQUEST (the whole job; every requirement counts):\n{req[:12000]}")
        notes = self._deliver_notes(sid, eng, phase)
        if notes:
            out.append(notes)
        plan = self._plan.get(sid)
        if plan and phase != "plan":
            out.append(f"THE TEAM PLAN (the contract everyone builds to):\n{plan[:9000]}")
        mine = sorted(p for p, o in (self._owners.get(sid) or {}).items() if o == eng["name"])
        if mine and phase in ("work", "fix", "test"):
            out.append("FILES YOU OWN: " + ", ".join(mine))
        listing = self._listing(st, target) if st["mode"] in ("edit", "auto", "plan") else ""
        if listing:
            out.append(f"PROJECT FILES RIGHT NOW (folder {eff_cwd(st, target)}):\n{listing}")
        return "\n\n".join(out) + "\n\n" if out else ""

    def _spawn(self, sid: str, argv: list[str], cwd: str | None, stdin: str | None, extra_env: dict | None = None):
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=cwd, env={**ENV, **(extra_env or {})}, start_new_session=True, bufsize=1)
        self.procs.setdefault(sid, []).append(p)
        err: list[str] = []
        threading.Thread(target=lambda: err.extend(p.stderr.readlines()[-30:]), daemon=True).start()
        if stdin is not None:
            try:
                p.stdin.write(stdin)
                p.stdin.close()
            except BrokenPipeError:
                pass
        return p, err

    def _run_engineer(self, sid: str, eng: dict, cfg: dict, st: dict, target: dict | None, directive: str = "", phase: str = "") -> str:
        """One engineer turn, plus the command broker: in Plan/Edit mode the engineer asks for shell commands in a
        ```run block; the user approves, the app runs it where the project lives, and the output goes back. Each block is
        one script, so heredocs survive. API engineers do all their work this way, so they get more rounds than CLIs."""
        text = self._run_once(sid, eng, cfg, st, target, directive, phase)
        retold, acted, idle_retold, broke = 0, False, False, 0
        for _ in range({"plan": 3, "fix": 6}.get(phase, 12) if eng["provider"] == API else 3):
            brokered = phase != "summary" and (st["mode"] in ("plan", "edit") or (eng["provider"] == API and st["mode"] == "auto"))
            block = aether_block(text) if brokered else {}
            files = [f for f in (block.get("files") or []) if isinstance(f, dict)][:20]
            cmds = (run_blocks(text) + [c.strip() for c in (block.get("commands") or []) if isinstance(c, str) and c.strip()]) \
                if brokered else []
            if sid in self.stopped or orch.is_down(eng["id"]):
                break
            if phase == "plan" and self.PLAN_DONE.search(text or ""):
                break      # the plan is written. Its acceptance checks run at verification; another round only tempts the lead to build alone
            if not (cmds or files):
                # A model that writes its own tool-call syntax (<tool_call>, <function=…>) instead of a ```run block
                # gets nothing run, and used to end the whole job there, silently. Tell it, at most twice.
                if brokered and retold < 2 and self.FOREIGN_CALL.search(text or ""):
                    retold += 1
                    self._post(sid, "system", "Aether", f"{eng['name']} wrote a tool call Aether cannot run — asking for a ```run / ```aether block instead.")
                    text = self._run_once(sid, eng, cfg, st, target, phase=phase, directive=self.RETELL)
                    continue
                # Free models sometimes answer a build with a stray word ("hi") and no action, which also ended the
                # job with nothing built and no summary. A doing turn that has not run or written anything yet gets one nudge.
                trouble = block_trouble(text) if brokered else ""
                if trouble and broke < 3:
                    broke += 1
                    self._post(sid, "system", "Aether", f"{eng['name']}: " + trouble.split(" — ")[0].split(", so")[0] + " — asking again.")
                    text = self._run_once(sid, eng, cfg, st, target, phase=phase, directive=trouble)
                    continue
                if brokered and phase in ("build", "work", "fix", "test") and not acted and not idle_retold:
                    idle_retold = True
                    self._post(sid, "system", "Aether", f"{eng['name']} replied without running or writing anything — asking it to do the task.")
                    text = self._run_once(sid, eng, cfg, st, target, phase=phase, directive=self.NOTHING_DONE)
                    continue
                break
            acted = True
            results = []
            if phase == "plan":
                # The lead plans; the team builds. Free models like to start building alone here, which leaves the
                # teammates with nothing to do and the lead debugging by itself. Only looking around is allowed.
                if files:
                    results.append("✕ files not written — this is the planning step. Put the work in the plan's Tasks; "
                                   "teammates write the files next.")
                    files = []
                ro = [c for c in cmds if self._read_only(c)]
                results += [f"$ {c}\n[not run] planning step: only read-only commands (ls, cat, grep, find…)." for c in cmds if c not in ro]
                cmds = ro
            if files:
                results.append(self._write_files(sid, files, st, target, by=eng["name"], phase=phase))
                if block.get("lenient") or (text or "").count("```") % 2 == 1:
                    results.append("⚠ Your ```aether block was " + ("cut off" if (text or "").count("```") % 2 == 1 else "not valid JSON")
                                   + f"; Aether recovered only: {', '.join(f.get('path', '?') for f in files)}. Anything else "
                                   "in it was NOT written — send it again, one file per reply.")
            if len(cmds) > 4:
                results.append(f"[not run: {len(cmds) - 4} more ```run blocks — only 4 run per reply. Send the rest in your next reply.]")
            for cmd in cmds[:4]:
                again = self._seen_cmd(sid, eng, cmd, st, target)
                if again:
                    results.append(f"$ {cmd}\n[not run again] {again}")
                    continue
                blocked = self._kill_guard(cmd, st, target) or next(
                    (why for ln in cmd.splitlines() if (why := self._port_guard(ln, target))), None)
                if blocked:
                    results.append(f"$ {cmd}\n[not run] {blocked}")
                    self._post(sid, "system", "Aether", f"Blocked: {blocked}")
                    continue
                if self._approve(sid, eng, cmd, st, target):
                    out = self._shell(sid, cmd, st, target, by=eng["name"])
                    self._acted.add(sid)
                    results.append(self._clip(out))
                else:
                    results.append(f"$ {cmd}\n[skipped — the user did not approve this command]")
            text = self._run_once(sid, eng, cfg, st, target, phase=phase, directive=(
                "Results of the files and commands you asked for:\n" + "\n\n".join(results) +
                "\n\nContinue your task. If you still need files or commands, output another ```aether / ```run block; "
                "otherwise finish with your answer."))
        return text

    PLAN_DONE = re.compile(r"(?mi)^\s*#+\s*Tasks\b[\s\S]*?^\s*@[\w .-]+?\s*[:\-–].*\|\s*files?\s*:")
    READ_ONLY = re.compile(r"^\s*(ls|cat|head|tail|grep|rg|find|wc|tree|pwd|file|stat|du|echo|sed\s+-n|git\s+(?:status|log|diff|show|branch)|node\s+--version|python3?\s+--version|which)\b")
    WRITES = re.compile(r"(?<![0-9&])>(?!\s*/dev/null)|\b(rm|mv|cp|tee|chmod|mkdir|touch|npm|npx|pip|kill|curl\s.*-o)\b|-exec|-delete|sed\s+-i")

    def _read_only(self, cmd: str) -> bool:
        lines = [ln for ln in re.split(r"\n|&&|\|\||;|\|", cmd) if ln.strip()]
        return bool(lines) and all(self.READ_ONLY.match(ln) for ln in lines) and not self.WRITES.search(cmd)

    def _seen_cmd(self, sid: str, eng: dict, cmd: str, st: dict, target: dict | None) -> str | None:
        """Agents re-read the same files over and over. An identical read-only command from the same agent, with no
        file in the project changed since it last ran, is answered from memory instead of being run again."""
        if not self._read_only(cmd):
            return None
        state = self._listing(st, target, limit=400)
        key = (sid, eng["id"], " ".join(cmd.split()))
        seen = self._cmd_seen.get(key)
        self._cmd_seen[key] = (state, time.strftime("%H:%M:%S"))
        if seen and seen[0] == state:
            return (f"you already ran exactly this at {seen[1]} and no file has changed since — use that output (it is in "
                    "your thread above). If your own files are done and checked, finish now with your summary.")
        return None

    @staticmethod
    def _clip(out: str, head: int = 7000, tail: int = 3000) -> str:
        """Command output for the engineer. Keep the START (a `cat` of a file used to arrive as only its last 3000
        characters, so engineers cat-ed the same file again and again) and the end (exit code, final errors)."""
        if len(out) <= head + tail:
            return out
        return out[:head] + f"\n[… {len(out) - head - tail} characters cut …]\n" + out[-tail:]

    # Includes vendor variants such as <dots_function_call> (a free model emitted 300 KB of those and ended a job).
    FOREIGN_CALL = re.compile(r"<tool_call>|<[\w-]*function_call\b|<function[=\s>]|<parameter=|<invoke\b|\"tool_calls\"\s*:|<\|tool_call", re.I)
    RETELL = ("Nothing was run: your last reply used a tool-call format this app ignores (<tool_call>, <function>, "
              "<parameter>). The ONLY actions are a ```run block (shell commands) and one ```aether block (files). "
              "Redo that step now with a ```run or ```aether block, or give your final answer if you are done.")

    NOTHING_DONE = ("You have not run or written anything yet, so nothing is built. Do the user's request now: create the "
                    "files with one ```aether block and/or run commands with ```run blocks, then check the result. "
                    "If the request truly needs no files or commands, say exactly why in one or two sentences.")

    SERVER_CMD = re.compile(r"http\.server|uvicorn|gunicorn|flask|vite|next (?:dev|start)|npm (?:run )?(?:dev|start)|php -S|serve\b|runserver|--port|--listen|PORT=", re.I)
    NOT_SERVER = re.compile(r"^\s*(curl|wget|lsof|ss|netstat|kill|pkill|echo|cat|ls|grep|freeport|sleep)\b")
    PORT_ARG = re.compile(r"(?:http\.server|--port[ =]|--listen[ =]|(?<!\w)-p[ =]?|PORT=|(?<!\w)-l[ =]?|:)\s*(\d{4,5})\b")

    def _port_in_use(self, port: int, target: dict | None) -> bool:
        if target is None:
            return fp.in_use(port)
        try:
            r = subprocess.run(ssh_argv(target, f"ss -ltnH 'sport = :{port}' | grep -q ."), capture_output=True, timeout=20, env=ENV)
            return r.returncode == 0
        except Exception:
            return False

    BROAD_KILL = re.compile(r"\b(?:pkill|killall)\b[^|;&]*?(?:-f\s+)?[\"']?(?:http\.server|python3?|Python|node|npm|uvicorn|gunicorn|ssh|chrome|Chrome|Claude|agy|claude|aether)\b", re.I)

    def _kill_guard(self, cmd: str, st: dict, target: dict | None) -> str | None:
        """Stopping programs by broad name, or killing whatever holds a port, also kills other people's work
        (a generic `pkill -f http.server` once stopped the user's solar simulator)."""
        if self.BROAD_KILL.search(cmd):
            return ("never stop programs by a broad name (pkill/killall) — that also stops the user's other programs. "
                    "Stop only a server YOU started, by its pid (aserve prints it) or with `kill <pid>`.")
        m = re.search(r"lsof\s+-[a-zA-Z]*t[a-zA-Z]*\s*:?\s*-?i?:?(\d{4,5})|-iTCP:(\d{4,5})[^|]*\|\s*xargs\s+kill", cmd)
        if m and re.search(r"\bkill\b", cmd) and target is None:
            port = m.group(1) or m.group(2)
            foreign = self._foreign_server(f"http://localhost:{port}/", eff_cwd(st, target))
            if foreign:
                return f"{foreign} Do not kill it — it is not part of this project."
        return None

    def _port_guard(self, cmd: str, target: dict | None) -> str | None:
        """Refuse a server-start command whose port is already taken (the team kept using 8000 blindly)."""
        if self.NOT_SERVER.search(cmd) or not self.SERVER_CMD.search(cmd) or "freeport" in cmd or "aserve" in cmd:
            return None
        for m in self.PORT_ARG.finditer(cmd):
            port = int(m.group(1))
            if 1024 <= port <= 65535 and self._port_in_use(port, target):
                return (f"port {port} is already in use by another program. Do not stop it. Get a free port with `freeport {port}` "
                        f"(prints the next free one) or serve a folder with `aserve <dir>`, then use the port it gives you.")
        return None

    # ---- approvals: read-only commands run on their own; "all" auto-approves everything except risky commands
    SAFE_SEG = re.compile(r"^\s*(?:ls|pwd|cat|head|tail|wc|grep|rg|find|which|whoami|hostname|uname|date|stat|file|tree|du|df|ps|lsof|ss|netstat|freeport|"
                          r"git (?:status|log|diff|show|branch|rev-parse)|node --check|python3? -m py_compile|sleep \d+|"
                          r"curl (?:-[a-zA-Z]+ )*https?://(?:localhost|127\.0\.0\.1)\S*|.*verify_web\.py\s+https?://\S+)(?:\s[^;&|<>`$]*)?$")
    RISKY = re.compile(r"\b(rm\s+-[a-z]*[rf]|sudo|su\b|mkfs|dd\s+if=|shutdown|reboot|halt|chmod\s+-R|chown\s+-R|git\s+push|git\s+reset\s+--hard|git\s+clean|"
                       r"kill\s+-9|killall|pkill|launchctl|systemctl\s+(?:stop|disable|mask)|docker\s+(?:rm|rmi|system\s+prune|volume\s+rm)|crontab|passwd|"
                       r"ssh-keygen|scp\b|rsync\b|npm\s+publish|pip3?\s+uninstall|brew\s+(?:uninstall|remove)|apt(?:-get)?\s+(?:remove|purge))\b|"
                       r"\|\s*(?:sh|bash|zsh)\b|>\s*/dev/|:\(\)\s*\{", re.I)

    CATASTROPHIC = re.compile(r"\bsudo\b|\bmkfs|\bdd\s+[^|;]*of=/dev/|:\(\)\s*\{|>\s*/dev/(?:sd|disk|nvme)|"
                              r"(?:curl|wget)[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b|"
                              r"\brm\s+-[a-z]*r[a-z]*\s+(?:--no-preserve-root\s+)?(?:/|~|\$HOME|/\*|~/\*|\*|\.\.?)\s*(?:$|[;&|])|chmod\s+-R\s+\d+\s+/\s*$", re.I)

    def _auto_ok(self, sid: str, cmd: str, st: dict) -> str | None:
        """Why this command may run without asking (None = ask the user)."""
        mode = st.get("autoapprove", "full")
        if mode == "full":
            # line by line too: the pattern anchors on end-of-command, which a multi-line script would hide
            return None if any(self.CATASTROPHIC.search(c) for c in [cmd, *cmd.splitlines()]) else "auto-approve is on"
        if any(self.RISKY.search(c) for c in [cmd, *cmd.splitlines()]):
            return None
        if mode == "all" or sid in self._allow_all:
            return "auto-approve is on"
        if mode == "safe" and not re.search(r"[><`]|\$\(", cmd) and all(self.SAFE_SEG.match(p) for p in re.split(r"&&|;|\|\|?|\n", cmd) if p.strip()):
            return "read-only"
        return None

    def _approve(self, sid: str, eng: dict, cmd: str, st: dict, target: dict | None) -> bool:
        why = self._auto_ok(sid, cmd, st)
        if why:
            self.emit({"t": "autoapproved", "sid": sid, "who": eng["name"], "cmd": cmd, "why": why})
            return True
        cid = uid()
        ev = threading.Event()
        self._approvals[cid] = {"ev": ev, "ok": False, "sid": sid}
        where = f'{target.get("user", "")}@{target["host"]}' if target else "this Mac"
        self.emit({"t": "approval", "sid": sid, "cid": cid, "who": eng["name"], "cmd": cmd, "where": where, "cwd": eff_cwd(st, target), "risky": bool(self.RISKY.search(cmd))})
        end = time.time() + 900
        while not ev.wait(0.5):
            if sid in self.stopped or time.time() > end:
                break
        ok = self._approvals.pop(cid, {}).get("ok", False)
        return ok and sid not in self.stopped

    def approve(self, cid: str, ok: bool, scope: str = "") -> bool:
        a = self._approvals.get(cid)
        if a:
            a["ok"] = bool(ok)
            if ok and scope == "session":
                self._allow_all.add(a["sid"])      # "allow all this session" (risky commands still ask)
            a["ev"].set()
        return True

    def _run_once(self, sid: str, eng: dict, cfg: dict, st: dict, target: dict | None, directive: str = "", phase: str = "") -> str:
        mid = uid()
        self.emit({"t": "start", "sid": sid, "mid": mid, "author": eng["name"], "eid": eng["id"], "phase": phase,
                   "via": "Mac → VM over ssh" if target and (phase == "verify" or not remote_ready(eng, target)) else ""})
        parser, tools, ok, error = Parser(eng["provider"]), {}, True, None
        thoughts: list[str] = []
        t0 = time.time()
        try:
            proxy = bool(target) and (phase == "verify" or not remote_ready(eng, target))
            if proxy:
                self.emit({"t": "text", "sid": sid, "mid": mid, "d": ""})
            argv, local_cwd = build_command(eng, st["mode"], target, eff_cwd(st, target), proxy, phase == "verify")
            p, err = self._spawn(sid, argv, local_cwd, (next(iter(engineer_env(eng).values()), "") + "\n" if target and not proxy and eng["provider"] == "bob_cli" else "")
                                  + wrap_stdin(eng["provider"], self._prompt(sid, eng, cfg, st, target, directive, proxy, phase)),
                                  engineer_env(eng))
            last, hung, limit = [time.time()], [], IDLE_LIMIT.get(eng["provider"], IDLE_LIMIT_DEFAULT)

            def watchdog() -> None:      # an engineer that stays silent too long is stopped, so its work can be reassigned
                while p.poll() is None:
                    if time.time() - last[0] > limit:
                        hung.append(True)
                        try:
                            os.killpg(p.pid, signal.SIGTERM)
                        except OSError:
                            pass
                        return
                    time.sleep(2)
            threading.Thread(target=watchdog, daemon=True).start()
            for line in p.stdout:
                last[0] = time.time()
                for kind, val in parser.feed(line.rstrip("\n") if eng["provider"] != "custom" else line):
                    if kind == "text":
                        self.emit({"t": "text", "sid": sid, "mid": mid, "d": val})
                    elif kind == "thought":
                        thoughts.append(val)
                        self.emit({"t": "thought", "sid": sid, "mid": mid, "d": val})
                    elif kind == "tool":
                        tools[val["id"]] = val
                        self.emit({"t": "tool", "sid": sid, "mid": mid, "tool": val})
                    elif kind == "result":
                        ok, error = val["ok"], val.get("error")
                        if val.get("abort"):
                            os.killpg(p.pid, signal.SIGTERM)
            p.wait()
            if sid in self.stopped:
                ok, error = False, "Stopped"
            elif hung:
                ok, error = False, f"not responding (no output for {f'{limit // 60} min' if limit >= 120 else f'{limit}s'})"
                orch.mark_down(eng["id"], "not responding", 300)
            elif p.returncode not in (0, None) and ok and not parser.text:
                ok, error = False, (" ".join(err).strip()[-400:] or f"exited with code {p.returncode}")
        except FileNotFoundError:
            ok, error = False, f"Command not found: {eng.get('command')}. Install it or fix the engineer's command."
        except Exception as exc:
            ok, error = False, str(exc)

        text = parser.text.strip()
        if len(text) > RUNAWAY_CHARS:
            ln = text.splitlines() or [text]
            if len(set(ln)) / len(ln) < 0.2 or self.FOREIGN_CALL.search(text[:3000]) or len(set(text[i:i + 200] for i in range(0, 20000, 200))) < 30:
                text = text[:3000] + f"\n\n[Aether cut this reply: {len(text) // 1024} KB of repeated output]"
        failed = sid not in self.stopped and ((bool(error) and error != "Stopped") or (not text and not tools))
        self._outcome[(sid, eng["id"])] = {"failed": failed, "why": error or "gave no reply"}
        if failed:
            self._failed_turn.setdefault(sid, set()).add(eng["id"])
        for fact in re.findall(r"^\s*REMEMBER:\s*(.+)$", text, re.M):
            self.add_memory(fact, eng["name"])
        text = re.sub(r"^\s*REMEMBER:.*$", "", text, flags=re.M).strip()
        outage = orch.detect_outage(error or "") or (orch.detect_outage(text) if not tools and len(text) < 400 else None)
        if outage:
            orch.mark_down(eng["id"], outage[0], outage[1])
            self._post(sid, "system", "Aether", f"{eng['name']} is unavailable — {outage[0]}. Their work goes to another available engineer.")
        orch.note_failure(eng["id"], bool(ok) and not error)
        self._last[sid] = {"tools": list(tools.values()), "error": error, "who": eng["id"]}
        if tools:
            self._acted.add(sid)
        if not text and not error and tools:      # agy sometimes ends with no prose: show what the last tool returned
            last = [t for t in tools.values() if t.get("output")]
            if last:
                text = f"{last[-1]['command']}\n```\n{last[-1]['output'].strip()[:1500]}\n```"
        if not text and not error and tools:
            steps = "\n".join(f"- {t.get('name')}: {str(t.get('command') or '')[:90]} ({t.get('state')})" for t in list(tools.values())[:12])
            text = f"(No written reply — here is what {eng['name']} did:)\n{steps}"
        if error and error != "Stopped" and not text:
            text = f"⚠ {error}"
        if not text and not error and sid not in self.stopped:
            text = f"({eng['name']} finished without replying — try again, or pick another engineer.)"
        self._store_assistant(sid, mid, eng["name"], text, {"tools": list(tools.values()), "error": error, "eid": eng["id"], "phase": phase,
                                                                      "thoughts": "".join(thoughts)[:4000], "dur": round(time.time() - t0, 1)})
        self.emit({"t": "end", "sid": sid, "mid": mid, "ok": ok, "error": error, "content": text, "dur": round(time.time() - t0, 1),
                   "memory": self.list_memory()})
        return text

    def _store_assistant(self, sid, mid, author, text, meta):
        with db() as c:
            c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                      (mid, sid, time.time(), "assistant", author, text, json.dumps(meta)))

    def _write_files(self, sid: str, files: list[dict], st: dict, target: dict | None, by: str | None = None, phase: str = "") -> str:
        """Write the files from an ```aether block into the project folder (Edit/Auto mode only; paths must stay
        inside it). Shown in the chat like a shell step; returns the report sent back to the engineer."""
        mid = uid()
        names = ", ".join(str(f.get("path", "?")) for f in files)
        self.emit({"t": "start", "sid": sid, "mid": mid, "author": "Shell", "eid": "shell", "shell": f"write {names}"})
        report: list[str] = []
        root = eff_cwd(st, target)
        for f in files:
            rel, content = str(f.get("path") or "").strip(), f.get("content")
            if isinstance(content, (list, dict)) and rel.endswith(".json"):
                content = json.dumps(content, indent=1)     # a JSON file given as JSON, not as a string: write it
            if not isinstance(content, str):
                report.append(f"✕ {rel or '?'}: no \"content\" string")
                continue
            if st["mode"] not in ("edit", "auto"):
                report.append(f"✕ {rel}: not written — {st['mode'].title()} mode does not allow changing files")
                continue
            norm = os.path.normpath(rel) if rel else ""
            if not norm or norm.startswith("..") or os.path.isabs(norm) or norm == ".":
                report.append(f"✕ {rel or '?'}: not written — use a path inside the project folder")
                continue
            if phase == "test" and norm != self.E2E:
                report.append(f"✕ {norm}: not written — the tester writes only {self.E2E}; report app bugs instead of fixing them.")
                continue
            owner = self._owner_of(sid, norm) if by and phase == "work" else None
            if owner and owner != by:
                report.append(f"✕ {norm}: not written — {owner} owns this file in the plan. Write only your own files; if it needs "
                              "a change for your part to work, say exactly what in your summary.")
                continue
            data = content.encode("utf-8")
            if len(data) > 2 << 20:
                report.append(f"✕ {norm}: not written — larger than 2 MB")
                continue
            try:
                if target:
                    d = os.path.dirname(norm)
                    script = f"{remote_cd(root)} && {'mkdir -p ' + shlex.quote(d) + ' && ' if d else ''}cat > {shlex.quote(norm)}"
                    r = subprocess.run(ssh_argv(target, script), input=data, capture_output=True, timeout=60, env=ENV)
                    if r.returncode:
                        raise OSError((r.stderr.decode(errors="replace").strip().splitlines() or ["ssh write failed"])[-1])
                else:
                    base = Path(os.path.expanduser(root)).resolve()
                    dest = (base / norm).resolve()
                    if base not in dest.parents:
                        raise OSError("outside the project folder")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
                report.append(f"✓ {norm} ({len(data)} bytes, {lines} lines)")
                self._acted.add(sid)
            except Exception as exc:
                report.append(f"✕ {norm}: {str(exc)[:160]}")
        body = f"$ write {names}\n" + "\n".join(report)
        self.emit({"t": "text", "sid": sid, "mid": mid, "d": "\n".join(report)})
        self._store_assistant(sid, mid, "Shell", body, {"shell": True, "by": by})
        with db() as c:
            c.execute("UPDATE messages SET role='shell' WHERE id=?", (mid,))
        self.emit({"t": "end", "sid": sid, "mid": mid, "ok": True, "content": body})
        return body

    def _shell(self, sid: str, cmd: str, st: dict, target: dict | None, by: str | None = None) -> str:
        mid = uid()
        self.emit({"t": "start", "sid": sid, "mid": mid, "author": "Shell", "eid": "shell", "shell": cmd})
        if target:
            argv, cwd = ssh_argv(target, f"{remote_cd(eff_cwd(st, target))} && {cmd}"), None
        else:
            argv, cwd = ["/bin/zsh", "-lc", cmd], st["cwd"] if Path(st["cwd"]).is_dir() else str(Path.home())
        out: list[str] = []
        try:
            # stdout+stderr merged like a terminal. We wait for the *shell* to exit, not for the pipe to close,
            # so a command that leaves a server running in the background (`python -m http.server &`) returns.
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 cwd=cwd, env=ENV, start_new_session=True, bufsize=1)
            self.procs.setdefault(sid, []).append(p)

            def reader() -> None:
                for line in p.stdout:
                    out.append(line)
                    self.emit({"t": "text", "sid": sid, "mid": mid, "d": line})
            th = threading.Thread(target=reader, daemon=True)
            th.start()
            t0 = time.time()
            while p.poll() is None and time.time() - t0 < 180 and sid not in self.stopped:
                time.sleep(0.15)
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                out.append("\n[stopped: still running after 180s]")
            th.join(1.0)
            tail = f"\n[exit {p.returncode}]"
            out.append(tail)
            self.emit({"t": "text", "sid": sid, "mid": mid, "d": tail})
        except Exception as exc:
            out.append(str(exc))
        body = f"$ {cmd}\n" + "".join(out)
        self._store_assistant(sid, mid, "Shell", body, {"shell": True, "by": by})
        with db() as c:   # stored as role=shell so engineers see it as user-run output
            c.execute("UPDATE messages SET role='shell' WHERE id=?", (mid,))
        self.emit({"t": "end", "sid": sid, "mid": mid, "ok": True, "content": body})
        return body


def install_edit_menu() -> None:
    """Standard Edit menu (Undo/Redo/Cut/Copy/Paste/Select All). WKWebView only honours ⌘C/⌘V/⌘A/⌘X when the app has one."""
    try:
        from AppKit import NSApplication, NSMenu, NSMenuItem
        app = NSApplication.sharedApplication()
        main = app.mainMenu()
        if main is None:
            main = NSMenu.alloc().init()
            app.setMainMenu_(main)
        for i in reversed(range(main.numberOfItems())):          # drop the framework's own Edit menu: ours uses the standard responder actions
            it = main.itemAtIndex_(i)
            if it.title() == "Edit" or (it.submenu() is not None and it.submenu().title() == "Edit"):
                main.removeItemAtIndex_(i)
        edit = NSMenu.alloc().initWithTitle_("Edit")
        for title, sel, key, shift in (("Undo", "undo:", "z", False), ("Redo", "redo:", "z", True), (None, None, None, False),
                                       ("Cut", "cut:", "x", False), ("Copy", "copy:", "c", False), ("Paste", "paste:", "v", False),
                                       ("Select All", "selectAll:", "a", False)):
            if title is None:
                edit.addItem_(NSMenuItem.separatorItem())
                continue
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
            if shift:
                it.setKeyEquivalentModifierMask_((1 << 20) | (1 << 17))   # ⌘⇧
            edit.addItem_(it)
        holder = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Edit", None, "")
        holder.setSubmenu_(edit)
        main.insertItem_atIndex_(holder, min(1, main.numberOfItems()))
    except Exception:
        pass


_ACTIVITY = None


def brand_app(name: str = "Aether Lite") -> None:
    """Dock icon + menu-bar name (otherwise macOS shows the generic Python rocket)."""
    try:
        from AppKit import NSApplication, NSBundle, NSImage
        from Foundation import NSProcessInfo
        # keep updating while the window is behind others (App Nap would otherwise pause the chat)
        global _ACTIVITY
        _ACTIVITY = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(0x00FFFFFF & ~(1 << 20), "Aether team is working")
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = name
        info["CFBundleDisplayName"] = name
        icon = NSImage.alloc().initWithContentsOfFile_(str(HERE / "assets" / "AetherLite.icns"))
        if icon:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
    except Exception:
        pass


def main() -> None:
    import atexit
    pidfile = DATA / "run.pid"
    pidfile.write_text(str(os.getpid()))
    atexit.register(lambda: pidfile.unlink(missing_ok=True))
    init_db()
    brand_app()
    api = Api()
    api.window = webview.create_window(
        "Aether Lite", str(HERE / "ui.html"), js_api=api, width=1180, height=780, min_size=(820, 520),
        transparent=True, vibrancy=True)
    webview.start(lambda: __import__('PyObjCTools.AppHelper', fromlist=['callAfter']).callAfter(install_edit_menu))


if __name__ == "__main__":
    main()
