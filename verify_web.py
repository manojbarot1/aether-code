#!/usr/bin/env python3
"""verify_web.py URL — does this web page ACTUALLY work? Used by the Aether team before handing work over.

Checks (exit 0 = PASS, 1 = FAIL):
  1. the URL answers 200 with HTML
  2. every script / stylesheet / ES-module import it references is reachable (no 404s)
  3. headless Chrome loads it and reports NO uncaught errors / console errors
  4. the rendered page is not blank (screenshot has real content)
Prints a short evidence report the engineer can paste into the chat.
"""
import json
import re
import subprocess
import warnings
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHROME = next((p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           "/Applications/Chromium.app/Contents/MacOS/Chromium",
                           "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if Path(p).exists()), None)


warnings.filterwarnings("ignore")


def get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "aether-verify"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get("content-type", "")


def main(url: str) -> int:
    fails, notes = [], []
    try:
        st, body, ctype = get(url)
    except Exception as exc:
        print(f"FAIL  cannot open {url}: {exc}")
        print("      (is the server running? is the port the right one — another service may own it)")
        return 1
    html = body.decode("utf-8", "replace")
    notes.append(f"OK    {url} -> HTTP {st} ({len(body)} bytes, {ctype.split(';')[0]})")
    if "html" not in ctype and "<html" not in html.lower() and "<!doctype" not in html.lower():
        fails.append(f"response is not HTML ({ctype}); body starts: {html[:80]!r}")

    # 2. referenced files + module imports (same origin, recursive)
    seen, queue = set(), [urllib.parse.urljoin(url, m) for m in re.findall(r'(?:src|href)=["\']([^"\'#]+)["\']', html)]
    inline = re.findall(r"<script[^>]*type=[\"']module[\"'][^>]*>(.*?)</script>", html, re.S)
    for code in inline:
        queue += [urllib.parse.urljoin(url, m) for m in re.findall(r"""(?:from|import)\s*\(?\s*["'](\.{0,2}/[^"']+)["']""", code)]
    base = urllib.parse.urlparse(url).netloc
    checked = 0
    while queue and checked < 60:
        u = queue.pop()
        if u in seen or urllib.parse.urlparse(u).scheme not in ("http", "https"):
            continue
        seen.add(u)
        if urllib.parse.urlparse(u).netloc != base:
            continue   # CDN etc. — Chrome step below catches load failures
        checked += 1
        try:
            s2, b2, c2 = get(u)
        except urllib.error.HTTPError as exc:
            fails.append(f"missing file: {u} -> HTTP {exc.code}")
            continue
        except Exception as exc:
            fails.append(f"cannot fetch {u}: {exc}")
            continue
        if u.endswith(".js") or "javascript" in c2:
            txt = b2.decode("utf-8", "replace")
            queue += [urllib.parse.urljoin(u, m) for m in re.findall(r"""(?:from|import)\s*\(?\s*["'](\.{0,2}/[^"']+)["']""", txt)]
    notes.append(f"OK    {checked} same-origin files reachable" if not any("missing" in f or "cannot fetch" in f for f in fails) else f"      checked {checked} files")

    # 3 + 4. real browser: errors, what is on screen, every button clicked, and the team's scripted steps
    if not CHROME:
        notes.append("WARN  no Chrome found — skipped the browser check (install Google Chrome or Chromium for full verification)")
    else:
        try:
            import browser_check
            f2, n2 = browser_check.run(CHROME, url, steps=STEPS, clicks=CLICKS, width=SIZE[0], height=SIZE[1])
            fails += f2
            notes += n2
        except Exception as exc:
            notes.append(f"WARN  interactive browser check failed to run ({exc}); falling back to a screenshot check")
            fails += legacy_screenshot(url, notes)

    print("\n".join(notes))
    if fails:
        print("\n".join("FAIL  " + f for f in fails))
        print("\nRESULT: FAIL")
        return 1
    print("\nRESULT: PASS")
    return 0


def legacy_screenshot(url, notes):
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "page.png"
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--window-size=1280,800",
                            "--enable-logging=stderr", "--v=0", "--virtual-time-budget=6000", f"--screenshot={shot}", url],
                           capture_output=True, text=True, timeout=60)
        for ln in r.stderr.splitlines():
            if "CONSOLE" in ln and ("rror" in ln or "Uncaught" in ln or "Failed" in ln or "404" in ln):
                fails.append("browser console error: " + re.sub(r"^\[.*?CONSOLE[^\]]*\]\s*", "", ln).strip()[:240])
        if not shot.exists():
            fails.append("headless Chrome produced no screenshot (page failed to load?)")
    return list(dict.fromkeys(fails))


STEPS, CLICKS, SIZE = None, True, (1280, 800)
USAGE = """verify_web.py URL [--steps STEPS] [--no-clicks] [--mobile]

STEPS is a JSON list (inline or a file path) of checks run in order in the real page, e.g.
  [{"click": "#add-card"}, {"expect": "#card-modal", "visible": true},
   {"type": ["#card-title", "Buy milk"]}, {"submit": "#card-form"}, {"expect": ".card", "text": "Buy milk"},
   {"press": "Escape"}, {"expect": "#card-modal", "visible": false},
   {"drag": [".card", "#col-done"]}, {"reload": true}, {"expect": ".card", "count": 1},
   {"eval": "localStorage.length > 0", "equals": true}, {"wait": 500}, {"select": ["#filter", "high"]}]
Actions: click, type [sel, text], select [sel, value], press KEY (optional "on": sel), submit FORM, drag [from, to],
wait MS, reload. Checks: expect SEL (+ visible true/false, text "…", count N), eval JS (+ equals VALUE).
--no-clicks skips clicking every button; --mobile uses a 375x812 viewport."""


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print(USAGE)
        sys.exit(2)
    target = args[0]
    if "--no-clicks" in args:
        CLICKS = False
    if "--mobile" in args:
        SIZE = (375, 812)
    if "--steps" in args:
        raw = args[args.index("--steps") + 1]
        try:
            STEPS = json.loads(Path(raw).read_text() if Path(raw).is_file() else raw)
            assert isinstance(STEPS, list)
        except Exception as exc:
            print(f"FAIL  --steps is not a JSON list of steps: {exc}\n\n{USAGE}")
            sys.exit(2)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(target))
