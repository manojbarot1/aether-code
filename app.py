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

VERIFY_PY = str(Path(__file__).parent / ".venv" / "bin" / "python") + " " + str(Path(__file__).parent / "verify_web.py")


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

API_NOTE = ("You are reached through a chat API and have no file or shell tools of your own. ONLY ```run blocks are "
            "executed — any other tool-call syntax (<tool_call>, function calls, JSON) is ignored. Do all work (create/edit "
            "files, run tests) through ```run blocks. Write each whole file with one heredoc in one block:\n"
            "```run\ncat > path/file.ext <<'EOF'\n...full file content...\nEOF\n```\n"
            "Check your work (e.g. `wc -c file`) before saying it is done.\n")

DOD = ("Definition of done: never say something works until you have actually run or opened it and can show the real "
       "command output. PORTS: never assume 8000 is free. Get a free port with `freeport 8000` (prints the first free port at or "
       "above 8000), or serve a folder with `aserve <dir>` (picks a free port and prints the real URL). Report the URL it printed. "
       "Never stop programs with pkill/killall by name; stop only servers you started, by pid.\n")

VERIFY = (
    "You are the TEAM LEAD and the only one who signs off. Do NOT trust your teammates' claims — verify everything yourself with your tools:\n"
    "1. Find what was built (list the working directory).\n"
    "2. Run it for real. Pick a FREE port with `freeport 8000` (never assume 8000 is free) — or `aserve <dir>` for a static site — and start it in the background.\n"
    f"3. For anything served over HTTP run: `{VERIFY_PY} <url>` (checks HTTP, missing files, browser console errors, blank page). "
    "For other code run its tests or run it with sample input.\n"
    "4. Quote the real command output as evidence.\n"
    "End with exactly one line: `VERDICT: PASS` (everything demonstrably works), `VERDICT: FAIL` (say precisely what is broken) "
    "or `VERDICT: UNVERIFIED` (you were not allowed to run the checks — say which). "
    "After VERDICT: PASS give the user the final answer: URL / how to run, and what you tested. Never write PASS without evidence from commands you ran in this step.")


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

    def clip_get(self) -> str:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            return str(NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or "")
        except Exception:
            return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout

    def clip_set(self, text: str) -> bool:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(text, NSPasteboardTypeString)
            return True
        except Exception:
            subprocess.run(["pbcopy"], input=text, text=True)
            return True

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
    def send(self, sid: str, text: str) -> dict | None:
        text = text.strip()
        if not text or sid in self.procs:
            return None
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
            self._learn(sid, cfg)
        finally:
            self.procs.pop(sid, None)
            self.emit({"t": "idle", "sid": sid})

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
                     directive="", phase: str = "", what: str = "task") -> tuple[dict, str]:
        """Run `eng`; if it goes down, errors out or stops responding, hand the same work to the next available
        engineer in `pool`. `directive` may be a function of the engineer (e.g. the lead's plan prompt).
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
            why = (orch.down_reason(eng["id"]) or o.get("why") or "not responding").splitlines()[0][:90]
            sub = self._substitute(sid, pool, tried)
            if not sub:
                self._post(sid, "system", "Team", f"{eng['name']} could not finish the {what} ({why}) and no other engineer is available to take over.",
                           {"phase": phase or "work"})
                return eng, text
            self._post(sid, "system", "Team", f"Reassigned · {eng['name']} is unavailable ({why}) — {sub['name']} takes over the {what}.",
                       {"phase": phase or "work"})
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
            return (f"You are the TEAM LEAD for this request. Teammates:\n{roster}\n"
                    "Write a short plan, then delegate by writing one line per teammate in exactly this form:\n"
                    "@Name: the specific task for them\n"
                    "Delegate by strengths (e.g. implementation vs review vs research). Do NOT do their work yourself now; "
                    "you will review everything afterwards. If the request is trivial, answer it directly and delegate nothing.")
        lead, plan = self._run_covered(sid, lead, members, cfg, st, target, plan_prompt, phase="plan", what="lead role")
        if (self._outcome.get((sid, lead["id"])) or {}).get("failed"):
            return                                   # nobody could lead; the reason is already posted
        mates = [m for m in members if m["id"] != lead["id"] and not orch.is_down(m["id"])
                 and m["id"] not in self._failed_turn.get(sid, set())]
        tasks = {}
        for m in mates:
            hit = re.search(rf"^\s*@{re.escape(m['name'])}\b\s*[:\-–]\s*(.+)$", plan, re.I | re.M)
            if hit:
                tasks[m["id"]] = hit.group(1).strip()
        solo_lead = not tasks and len(plan) < 400 and not re.search(r"@\w+", plan)   # lead handled a small request itself
        workers = [] if solo_lead else ([m for m in mates if m["id"] in tasks] or mates)
        if workers:
            self._post(sid, "system", "Team", "Work · " + ", ".join(m["name"] for m in workers), {"phase": "work"})
        done: list[dict] = []
        pool = mates + [lead]                        # the lead is idle while the team works: last-resort cover

        def work(m):
            task = tasks.get(m["id"], "Contribute your part to the request, complementing the plan.")
            who, _ = self._run_covered(sid, m, pool, cfg, st, target, phase="work", what=f"task “{task[:60]}”", directive=(
                f"{lead['name']} (team lead) assigned you: {task}\n"
                "Do your part now with your tools if needed. Be brief. End with a 2-3 line summary of what you did/found."))
            done.append(who)
        threads = [threading.Thread(target=work, args=(m,)) for m in workers]   # teammates work in parallel
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if sid in self.stopped or st["mode"] == "chat":
            return
        fixers = list({e["id"]: e for e in done}.values()) or [lead]
        self._verify(sid, lead, fixers, cfg, st, target, pool=[lead] + mates)

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
                r = subprocess.run([str(Path(__file__).parent / ".venv" / "bin" / "python"), str(Path(__file__).parent / "verify_web.py"), url],
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
        """The lead tests the work for real (another engineer covers if the lead is down). One repair round, only on an explicit FAIL."""
        pool = pool or [lead, *fixers]
        for rnd in (1, 2):
            if orch.is_down(lead["id"]) or lead["id"] in self._failed_turn.get(sid, set()):
                lead = self._substitute(sid, pool, set()) or lead
            self._post(sid, "system", "Team", f"Verify · {lead['name']} tests the work" + (" (re-check)" if rnd > 1 else ""), {"phase": "verify"})
            lead, out = self._run_covered(sid, lead, pool, cfg, st, target, VERIFY, phase="verify", what="verification")
            found = re.findall(r"VERDICT:\s*(PASS|FAIL|UNVERIFIED)", out)
            verdict = found[-1] if found else "UNVERIFIED"          # no marker is not a failure — nothing to repair
            tools = (self._last.get(sid) or {}).get("tools") or []
            if tools and not any(t.get("state") == "done" for t in tools) and verdict == "FAIL":
                verdict = "UNVERIFIED"                               # every command was refused: that is a permission issue, not a bug
                self._post(sid, "system", "Aether", f"{lead['name']} could not run any command in {st['mode']} mode, so nothing was verified. Switch the mode to Auto (or approve its command requests) and ask again.")
            if verdict != "FAIL" or sid in self.stopped:
                return
            if rnd == 2:
                self._post(sid, "system", "Team", "Still failing after one repair round — handing back with the failures listed above.", {"phase": "verify"})
                return
            self._post(sid, "system", "Team", "Fix · repairing what the lead found", {"phase": "work"})
            threads = [threading.Thread(target=lambda m=m: self._run_covered(sid, m, pool, cfg, st, target, phase="fix", what="fix", directive=(
                f"{lead['name']} tested the work and it FAILED — read the findings above. Fix the problems in your area, "
                "then re-run the failing check yourself and show the output. Be brief."))) for m in fixers
                if not orch.is_down(m["id"])] or [threading.Thread(target=lambda: self._run_covered(
                    sid, lead, pool, cfg, st, target, phase="fix", what="fix",
                    directive="Your test FAILED — read the findings above. Fix the problems, then re-run the failing check and show the output. Be brief."))]
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

    def _prompt(self, sid: str, eng: dict, cfg: dict, st: dict, target: dict | None, directive: str = "", proxy: bool = False) -> str:
        with db() as c:
            hist = [row_msg(r) for r in c.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY ts DESC LIMIT ?", (sid, CONTEXT_MESSAGES))][::-1]
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
        for m in hist:
            body = m["content"][:MAX_MSG_CHARS]
            if m["role"] == "user":
                lines.append(f"[User]: {body}")
            elif m["role"] == "assistant":
                lines.append(f"[{m['author']}]: {body}")
            elif m["role"] == "shell":
                lines.append(f"[User ran shell command]: {body}")
        return (
            f"You are {eng['name']}, {eng['role']}, in a shared team chat with the user and: {team}.\n"
            f"Working directory {where}: {eff_cwd(st, target)}  |  permission mode: {st['mode']}.\n"
            f"{proxy_note}{DOD if st['mode'] in ('edit', 'auto') else ''}{RUN_NOTE if st['mode'] in ('plan', 'edit') or (is_api and st['mode'] == 'auto') else ''}"
            f"{API_NOTE if is_api and st['mode'] in ('edit', 'auto') else ''}Be concise. Use your tools to act when asked. Replies from teammates appear in the transcript as [Name].\n"
            f"If you learn a durable fact worth keeping across sessions, add a line `REMEMBER: <fact>` at the end.\n\n"
            f"Shared memory:\n{mem}\n\n"
            f"Other recent sessions: {'; '.join(r['title'] + (' — ' + r['summary'] if r['summary'] else '') for r in others) or 'none'}\n\n"
            f"Conversation so far:\n" + "\n\n".join(lines) + f"\n\n{directive or 'Reply now as ' + eng['name'] + '.'}"
        )

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
        for _ in range(12 if eng["provider"] == API else 3):
            cmds = [blk.strip() for blk in re.findall(r"```run\s*\n(.*?)```", text, re.S) if blk.strip()] \
                if st["mode"] in ("plan", "edit") or (eng["provider"] == API and st["mode"] == "auto") else []
            if not cmds or sid in self.stopped or orch.is_down(eng["id"]):
                break
            results = []
            for cmd in cmds[:4]:
                blocked = self._kill_guard(cmd, st, target) or next(
                    (why for ln in cmd.splitlines() if (why := self._port_guard(ln, target))), None)
                if blocked:
                    results.append(f"$ {cmd}\n[not run] {blocked}")
                    self._post(sid, "system", "Aether", f"Blocked: {blocked}")
                    continue
                if self._approve(sid, eng, cmd, st, target):
                    out = self._shell(sid, cmd, st, target)
                    self._acted.add(sid)
                    results.append(out[-3000:])
                else:
                    results.append(f"$ {cmd}\n[skipped — the user did not approve this command]")
            text = self._run_once(sid, eng, cfg, st, target, phase=phase, directive=(
                "Results of the commands you asked for:\n" + "\n\n".join(results) +
                "\n\nContinue your task. If you still need a command, output another ```run block; otherwise finish with your answer."))
        return text

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
        self.emit({"t": "start", "sid": sid, "mid": mid, "author": eng["name"], "eid": eng["id"],
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
                                  + wrap_stdin(eng["provider"], self._prompt(sid, eng, cfg, st, target, directive, proxy)),
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

    def _shell(self, sid: str, cmd: str, st: dict, target: dict | None) -> str:
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
        self._store_assistant(sid, mid, "Shell", body, {"shell": True})
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
