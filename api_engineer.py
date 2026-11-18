#!/usr/bin/env python3
"""Engineer backed by an OpenAI-compatible chat API (OpenAI/ChatGPT, Ollama, FreeLLMAPI, LM Studio, OpenRouter…).

Run by app.py like a CLI engineer: prompt on stdin, API key in $AETHER_API_KEY, JSON lines on stdout:
  {"type": "text", "text": ...} | {"type": "thought", "text": ...} | {"type": "result", "ok": bool, "error": str|None}
"""

from __future__ import annotations

import argparse
import json
import re
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request


def out(ev: dict) -> None:
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


def request(base: str, path: str, key: str, body: dict | None = None, timeout: int = 20):
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if body and body.get("stream") else "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    return urllib.request.urlopen(urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers), timeout=timeout)


def list_models(base: str, key: str, timeout: int = 15) -> list[str]:
    with request(base, "/models", key, timeout=timeout) as r:
        data = json.loads(r.read())
    items = data.get("data") if isinstance(data, dict) else data
    return [m["id"] for m in items or [] if isinstance(m, dict) and m.get("id")]


def http_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
        j = json.loads(body)
        err = j.get("error")
        msg = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or body
    except Exception:
        msg = exc.reason
    hint = " Check the API key in the engineer's settings." if exc.code in (401, 403) else ""
    return f"HTTP {exc.code}: {str(msg)[:300]}{hint}"


def ssl_hint(url: str, exc: Exception) -> str:
    """Plain-HTTP servers (Ollama, FreeLLMAPI, LM Studio) answer an https:// URL with an SSL error."""
    return " (this server speaks plain HTTP: use http:// instead of https://)" \
        if url.startswith("https://") and "SSL" in str(exc) else ""


MAX_CONTINUE = 3
STALL_SECS = int(os.environ.get("AETHER_STALL_SECS", "90"))   # no text for this long: the provider has stalled
STALL_RETRIES = 2


def splice(before: str, more: str) -> str:
    """The start of a continuation, cleaned so it joins the text it continues: models asked to go on often re-open the
    block they were in (a stray "```aether" in the middle of a file) or repeat the last lines they wrote."""
    inside = before.count("```") % 2 == 1
    if inside:
        more = re.sub(r"^\s*```[\w-]*[ \t]*\n(?:\s*\{\s*\n?\s*\"files\"\s*:\s*\[\s*\{[^\n]*\n?)?", "", more, count=1)
    tail = before[-600:]
    for n in range(min(len(tail), len(more)), 19, -1):          # longest repeated overlap first
        if tail.endswith(more[:n]):
            return more[n:]
    return more


def stream_once(base: str, key: str, model: str, messages: list[dict], before: str = "") -> tuple[str | None, str]:
    """One streamed completion, echoed as it arrives. Returns (text, finish_reason); text None after an error event.
    `before`: the text this one continues; its first ~600 characters are held back and cleaned (see splice)."""
    body = {"model": model, "stream": True, "messages": messages}
    text, finish = [], ""
    held = [] if before else None
    # A provider can start a reply and then go silent while the connection stays open (keep-alive pings reset the
    # socket timeout), which froze whole jobs for 20+ minutes. A watchdog closes the stream after STALL_SECS
    # without any text; the caller retries, or continues the part that arrived.
    last, done, resp, stalled = [time.time()], threading.Event(), [None], [False]

    def watch() -> None:
        while not done.wait(3):
            if time.time() - last[0] > STALL_SECS:
                stalled[0] = True
                r = resp[0]
                if r is not None:
                    try:
                        r.fp.raw._sock.shutdown(socket.SHUT_RDWR)      # unblocks the read in the other thread
                    except Exception:
                        pass
                return

    threading.Thread(target=watch, daemon=True).start()

    def emit(chunk: str) -> None:
        nonlocal held
        if held is not None:
            held.append(chunk)
            joined = "".join(held)
            if len(joined) < 600:
                return
            held, chunk = None, splice(before, joined)
            if not chunk:
                return
        text.append(chunk)
        out({"type": "text", "text": chunk})

    try:
        with request(base, "/chat/completions", key, body, timeout=STALL_SECS + 30) as r:
            resp[0] = r
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                if ev.get("error"):
                    err = ev["error"]
                    out({"type": "result", "ok": False, "error": str(err.get("message") if isinstance(err, dict) else err)[:300]})
                    return None, "error"
                for ch in ev.get("choices") or []:
                    d = ch.get("delta") or ch.get("message") or {}
                    think = d.get("reasoning_content") or d.get("reasoning")
                    if think:
                        last[0] = time.time()
                        out({"type": "thought", "text": think})
                    if d.get("content"):
                        last[0] = time.time()
                        emit(d["content"])
                    finish = ch.get("finish_reason") or finish
    except Exception:
        if not stalled[0]:
            raise
    finally:
        done.set()
    if stalled[0]:
        finish = "stalled"
    if held:
        rest = splice(before, "".join(held))
        if rest:
            text.append(rest)
            out({"type": "text", "text": rest})
    return "".join(text), finish


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", default="")
    args = ap.parse_args()
    key = os.environ.get("AETHER_API_KEY", "")
    prompt = sys.stdin.read()
    try:
        model = args.model
        if not model:   # no model chosen: use the first one the server offers
            ids = list_models(args.base_url, key)
            if not ids:
                out({"type": "result", "ok": False, "error": "No model set and the server listed none. Pick a model in the engineer's settings."})
                return 1
            model = ids[0]
        # Free providers cap reply length (often ~4k tokens). A plan or a file cut off mid-way used to arrive
        # half-written (no task lines, broken JSON). When the reply stops at the limit, or inside an unclosed
        # ``` block, ask the model to continue where it stopped, up to MAX_CONTINUE times.
        messages = [{"role": "user", "content": prompt}]
        full, stalls, attempt = "", 0, 0
        while attempt <= MAX_CONTINUE:
            text, finish = stream_once(args.base_url, key, model, messages, before=full)
            if text is None:
                return 1
            if finish == "stalled" and not text.strip():
                stalls += 1
                if stalls > STALL_RETRIES:
                    out({"type": "result", "ok": False, "error": f"The provider stopped responding ({STALL_SECS}s with no reply, "
                                                                  f"{stalls} tries)."})
                    return 1
                out({"type": "thought", "text": f"\n[provider sent nothing for {STALL_SECS}s — asking again]\n"})
                continue                       # nothing arrived: the same request again (the router picks a provider anew)
            attempt += 1
            full += text
            cut = finish in ("length", "stalled") or full.count("```") % 2 == 1
            if not cut or not text.strip():
                break
            messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": full},
                        {"role": "user", "content": "Your reply was cut off. Continue EXACTLY where it stopped (mid-word or "
                                                    "mid-line if needed). Do not repeat anything and do not add any preamble."}]
        out({"type": "result", "ok": True, "error": None})
        return 0
    except urllib.error.HTTPError as exc:
        out({"type": "result", "ok": False, "error": http_error(exc)})
    except urllib.error.URLError as exc:
        out({"type": "result", "ok": False, "error": f"Cannot reach {args.base_url}: {exc.reason}{ssl_hint(args.base_url, exc)}"})
    except Exception as exc:
        out({"type": "result", "ok": False, "error": str(exc)[:300]})
    return 1


if __name__ == "__main__":
    sys.exit(main())
