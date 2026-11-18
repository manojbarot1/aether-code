#!/usr/bin/env python3
"""Engineer backed by an OpenAI-compatible chat API (OpenAI/ChatGPT, Ollama, FreeLLMAPI, LM Studio, OpenRouter…).

Run by app.py like a CLI engineer: prompt on stdin, API key in $AETHER_API_KEY, JSON lines on stdout:
  {"type": "text", "text": ...} | {"type": "thought", "text": ...} | {"type": "result", "ok": bool, "error": str|None}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def stream_once(base: str, key: str, model: str, messages: list[dict]) -> tuple[str | None, str]:
    """One streamed completion, echoed as it arrives. Returns (text, finish_reason); text None after an error event."""
    body = {"model": model, "stream": True, "messages": messages}
    text, finish = [], ""
    with request(base, "/chat/completions", key, body, timeout=300) as r:
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
                    out({"type": "thought", "text": think})
                if d.get("content"):
                    text.append(d["content"])
                    out({"type": "text", "text": d["content"]})
                finish = ch.get("finish_reason") or finish
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
        full = ""
        for attempt in range(1 + MAX_CONTINUE):
            text, finish = stream_once(args.base_url, key, model, messages)
            if text is None:
                return 1
            full += text
            cut = finish == "length" or full.count("```") % 2 == 1
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
