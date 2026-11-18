"""Drive headless Chrome over the DevTools protocol (no packages needed: CDP over --remote-debugging-pipe).

Used by verify_web.py to check that a page really WORKS, not only that it loads:
  * errors: uncaught exceptions, console.error, failed requests (404s, CDN failures)
  * what is on screen after load: visible text, buttons, canvases, and dialogs/overlays left open over the page
  * smoke clicks: every visible button is clicked once; any error it throws is reported
  * steps: scripted checks written by the team (click, type, press, drag, expect, eval…)
"""
from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import subprocess
import tempfile
import time

STUBS = """
(() => {
  window.__aeErrors = [];
  const push = (m) => { try { window.__aeErrors.push(String(m).slice(0, 300)); } catch (e) {} };
  addEventListener('error', (e) => push((e.message || 'error') + (e.filename ? ' @ ' + e.filename.split('/').pop() + ':' + e.lineno : '')), true);
  addEventListener('unhandledrejection', (e) => push('unhandled promise rejection: ' + ((e.reason && e.reason.message) || e.reason)));
  window.alert = () => {}; window.confirm = () => true; window.prompt = (m, d) => (d || 'Test');
})();
"""

AUDIT = r"""
(() => {
  const vw = innerWidth, vh = innerHeight;
  const visible = (el) => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.05 && r.width > 2 && r.height > 2 &&
      r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;  // computed style only: CSS can override the hidden attribute
  };
  const desc = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const overlays = [];
  for (const el of document.querySelectorAll('dialog[open], [role="dialog"], [role="alertdialog"], [class*="modal" i], [class*="overlay" i], [class*="popup" i], [id*="modal" i], [id*="dialog" i]')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    const area = (Math.min(r.right, vw) - Math.max(r.left, 0)) * (Math.min(r.bottom, vh) - Math.max(r.top, 0));
    const s = getComputedStyle(el);
    if ((s.position === 'fixed' || s.position === 'absolute' || el.tagName === 'DIALOG') && area > 0.12 * vw * vh)
      overlays.push(desc(el) + ' — "' + (el.innerText || '').trim().split('\n')[0].slice(0, 60) + '"');
  }
  const buttons = [...document.querySelectorAll('button, [role="button"], input[type="button"]')].filter(visible);
  const canvases = [...document.querySelectorAll('canvas')].filter(visible).map((c) => c.width + 'x' + c.height);
  const text = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
  return { title: document.title, text: text.slice(0, 500), textLength: text.length, buttons: buttons.length,
           buttonNames: buttons.slice(0, 40).map((b) => (b.getAttribute('aria-label') || b.innerText || b.title || desc(b)).trim().slice(0, 30)),
           unlabeled: buttons.filter((b) => !(b.getAttribute('aria-label') || b.innerText.trim() || b.title)).map(desc).slice(0, 8),
           overlays: [...new Set(overlays)].slice(0, 6), canvases, elements: document.querySelectorAll('body *').length };
})()
"""

SMOKE = r"""
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const visible = (el) => { const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 2 && r.height > 2 && !el.disabled; };
  const name = (b) => (b.getAttribute('aria-label') || b.innerText || b.title || b.id || b.className || b.tagName).toString().trim().slice(0, 40);
  const out = [], done = new Set();
  const start = location.href;
  for (let round = 0; round < 3; round++) {
    const list = [...document.querySelectorAll('button, [role="button"], input[type="button"]')]
      .filter((b) => visible(b) && !done.has(b) && b.type !== 'submit' && !/delete|remove|clear|reset|import/i.test(name(b)));
    if (!list.length) break;
    for (const b of list.slice(0, 40)) {
      done.add(b);
      if (!document.contains(b) || !visible(b)) continue;
      const before = window.__aeErrors.length;
      try { b.click(); } catch (e) { window.__aeErrors.push('click threw: ' + e.message); }
      await sleep(180);
      const errs = window.__aeErrors.slice(before);
      out.push((errs.length ? 'ERR ' : 'ok  ') + name(b) + (errs.length ? ' -> ' + errs.join(' | ') : ''));
      // close whatever it opened, so the next button is reachable
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      for (const d of document.querySelectorAll('dialog[open]')) { try { d.close(); } catch (e) {} }
      await sleep(60);
      if (location.href !== start) { out.push('note: navigated to ' + location.href); return out; }
    }
  }
  return out;
})()
"""

STEP_JS = r"""
(async (step) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (sel) => { const el = document.querySelector(sel); if (!el) throw new Error('no element matches ' + sel); return el; };
  const vis = (el) => { const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.05 && r.width > 0 && r.height > 0; };
  const key = (k, target) => { const t = target || document.activeElement || document.body;
    for (const type of ['keydown', 'keyup']) t.dispatchEvent(new KeyboardEvent(type, { key: k, bubbles: true, cancelable: true })); };
  if (step.click) { const el = q(step.click); el.scrollIntoView({ block: 'center' }); el.click(); await sleep(200); return 'clicked ' + step.click; }
  if (step.type) { const [sel, text] = step.type; const el = q(sel); el.focus(); el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return 'typed into ' + sel; }
  if (step.select) { const [sel, v] = step.select; const el = q(sel); el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); return 'selected ' + v; }
  if (step.press) { key(step.press, step.on ? q(step.on) : null); await sleep(200); return 'pressed ' + step.press; }
  if (step.submit) { const f = q(step.submit); (f.requestSubmit ? f.requestSubmit() : f.submit()); await sleep(250); return 'submitted ' + step.submit; }
  if (step.wait) { await sleep(Math.min(+step.wait, 10000)); return 'waited ' + step.wait + ' ms'; }
  if (step.expect) {
    const all = [...document.querySelectorAll(step.expect)];
    if ('count' in step) { const n = all.filter(vis).length; if (n !== step.count) throw new Error(`expected ${step.count} visible ${step.expect}, found ${n}`); return `${n} visible ${step.expect}`; }
    if (!all.length) { if (step.visible === false) return step.expect + ' absent'; throw new Error('no element matches ' + step.expect); }
    const shown = all.some(vis);
    if (step.visible === false && shown) throw new Error(step.expect + ' is visible but should be hidden');
    if (step.visible !== false && !shown) throw new Error(step.expect + ' exists but is not visible');
    if (step.text && !all.some((e) => (e.innerText || e.value || '').includes(step.text))) throw new Error(`${step.expect} does not contain "${step.text}"`);
    return step.expect + (step.visible === false ? ' hidden' : ' visible') + (step.text ? ` with "${step.text}"` : '');
  }
  if (step.eval) { const v = await (0, eval)(step.eval); if ('equals' in step && JSON.stringify(v) !== JSON.stringify(step.equals))
    throw new Error(`${step.eval} returned ${JSON.stringify(v)}, expected ${JSON.stringify(step.equals)}`); return 'eval -> ' + JSON.stringify(v).slice(0, 120); }
  if (step.center) { const r = q(step.center).getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }
  throw new Error('unknown step ' + JSON.stringify(step));
})
"""


class Chrome:
    def __init__(self, chrome: str, width: int = 1280, height: int = 800):
        self.profile = tempfile.mkdtemp(prefix="aether-chrome-")
        r1, self.w = os.pipe()
        self.r, w2 = os.pipe()
        # Chrome reads commands on fd 3 and writes replies on fd 4. Move our ends above 10 first, so a pipe that
        # happens to be numbered 3 or 4 already can't be clobbered (or left close-on-exec) by the dup2 below.
        hi_r, hi_w = fcntl.fcntl(r1, fcntl.F_DUPFD_CLOEXEC, 10), fcntl.fcntl(w2, fcntl.F_DUPFD_CLOEXEC, 10)
        os.close(r1)
        os.close(w2)
        r1, w2 = hi_r, hi_w

        def fds():
            os.dup2(r1, 3)
            os.dup2(w2, 4)
        self.p = subprocess.Popen([chrome, "--headless=new", "--remote-debugging-pipe", "--no-sandbox", "--disable-gpu",
                                   "--no-first-run", "--no-default-browser-check", "--use-gl=swiftshader", "--enable-unsafe-swiftshader",
                                   f"--user-data-dir={self.profile}", f"--window-size={width},{height}", "about:blank"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  close_fds=False, preexec_fn=fds)
        os.close(r1)
        os.close(w2)
        self.buf, self.n, self.events, self.session = b"", 0, [], None

    def _read(self, timeout: float):
        end = time.time() + timeout
        while b"\0" not in self.buf:
            left = end - time.time()
            if left <= 0 or not select.select([self.r], [], [], left)[0]:
                return None
            chunk = os.read(self.r, 1 << 20)
            if not chunk:
                raise RuntimeError("Chrome closed the DevTools pipe")
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def send(self, method: str, params: dict | None = None, timeout: float = 30, session: bool = True):
        self.n += 1
        mid = self.n
        m = {"id": mid, "method": method, "params": params or {}}
        if session and self.session:
            m["sessionId"] = self.session
        os.write(self.w, json.dumps(m).encode() + b"\0")
        end = time.time() + timeout
        while time.time() < end:
            msg = self._read(end - time.time())
            if msg is None:
                break
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            self.events.append(msg)
        raise TimeoutError(f"{method} timed out")

    def pump(self, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            msg = self._read(end - time.time())
            if msg is None:
                return
            self.events.append(msg)

    def eval(self, expr: str, timeout: float = 30):
        r = self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description", d.get("text", "error")).split("\n")[0])
        return (r.get("result") or {}).get("value")

    def open(self, url: str):
        t = self.send("Target.createTarget", {"url": "about:blank"}, session=False)
        self.session = self.send("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}, session=False)["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
            self.send(m)
        self.send("Page.addScriptToEvaluateOnNewDocument", {"source": STUBS})
        self.send("Page.navigate", {"url": url})
        end = time.time() + 20
        while time.time() < end and not any(e.get("method") == "Page.loadEventFired" for e in self.events):
            self.pump(0.5)

    def mouse_drag(self, a, b):
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": a[0], "y": a[1]})
        self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": a[0], "y": a[1], "button": "left", "clickCount": 1})
        for i in range(1, 11):
            x, y = a[0] + (b[0] - a[0]) * i / 10, a[1] + (b[1] - a[1]) * i / 10
            self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left", "buttons": 1})
            self.pump(0.03)
        self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": b[0], "y": b[1], "button": "left", "clickCount": 1})
        self.pump(0.3)

    def errors(self) -> list[str]:
        out = []
        for e in self.events:
            m, p = e.get("method"), e.get("params", {})
            if m == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                out.append("uncaught: " + ((d.get("exception") or {}).get("description") or d.get("text", "")).split("\n")[0][:240])
            elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
                out.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:240])
            elif m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
                en = p["entry"]
                out.append(f"{en.get('source', 'log')}: {en.get('text', '')[:200]} {en.get('url', '')[-80:]}".strip())
            elif m == "Network.loadingFailed" and not p.get("canceled"):
                out.append(f"request failed: {p.get('errorText')} ({p.get('type', '')})")
        return list(dict.fromkeys(o for o in out if "favicon.ico" not in o))

    def close(self):
        try:
            self.send("Browser.close", session=False, timeout=5)
        except Exception:
            pass
        try:
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


ACTIONS = ("click", "type", "select", "press", "submit", "drag", "reload", "wait")
CHECKS = {"expect": ("visible", "text", "count"), "eval": ("equals",)}


def split_steps(steps: list) -> list:
    """{"click": "#a", "expect": "#b", "visible": true} is one action and one check. The step runner does only the first
    key it knows, so the check was silently skipped and could never fail; run them as separate steps, action first."""
    out = []
    for st in steps or []:
        if not isinstance(st, dict):
            out.append(st)
            continue
        acts = [k for k in ACTIONS if k in st]
        checks = [k for k in CHECKS if k in st]
        if len(acts) + len(checks) <= 1:
            out.append(st)
            continue
        for k in acts:
            out.append({k: st[k], **({"on": st["on"]} if k == "press" and "on" in st else {})})
        for k in checks:
            out.append({k: st[k], **{x: st[x] for x in CHECKS[k] if x in st}})
    return out


def run(chrome: str, url: str, steps: list | None = None, clicks: bool = True, width: int = 1280, height: int = 800):
    """Returns (fails, notes) lines for the report."""
    fails, notes = [], []
    c = Chrome(chrome, width, height)
    try:
        c.open(url)
        c.pump(2.5)                                    # let the app start (fonts, modules, first render)
        load_errs = c.errors()
        for e in load_errs:
            fails.append(f"on load: {e}")
        if not load_errs:
            notes.append("OK    no errors on load (exceptions, console.error, failed requests)")
        a = c.eval(AUDIT)
        notes.append(f"      on screen ({width}x{height}): title \"{a['title']}\", {a['elements']} elements, {a['buttons']} visible buttons, "
                     f"{len(a['canvases'])} canvas(es) {' '.join(a['canvases'])}")
        notes.append(f"      visible text: \"{a['text'][:300]}\"")
        if a["buttonNames"]:
            notes.append("      buttons: " + ", ".join(b for b in a["buttonNames"] if b)[:400])
        if a["overlays"]:
            fails.append("a dialog/overlay is open over the page right after load (should start closed?): " + "; ".join(a["overlays"]))
        if a["textLength"] < 20 and not a["canvases"]:
            fails.append(f"page looks empty: {a['textLength']} characters of visible text and no canvas")
        if a["unlabeled"]:
            notes.append("WARN  buttons without a text or aria-label: " + ", ".join(a["unlabeled"]))
        steps = split_steps(steps)
        if steps:
            fn = STEP_JS.strip()
            known = {"click", "type", "select", "press", "submit", "wait", "expect", "eval", "drag", "reload"}
            for i, st in enumerate(steps, 1):
                if not isinstance(st, dict) or not (set(st) & known):
                    notes.append(f"WARN  step {i} {json.dumps(st)[:80]} is not a valid step (test bug) — skipped")
                    continue
                before = len(c.errors())
                try:
                    if "drag" in st:
                        src, dst = st["drag"]
                        a_xy = c.eval(f"({fn})({json.dumps({'center': src})})")
                        b_xy = c.eval(f"({fn})({json.dumps({'center': dst})})")
                        c.mouse_drag(a_xy, b_xy)
                        res = f"dragged {src} -> {dst}"
                    elif st.get("reload"):
                        c.events.clear()
                        c.send("Page.reload")
                        end = time.time() + 15
                        while time.time() < end and not any(e.get("method") == "Page.loadEventFired" for e in c.events):
                            c.pump(0.5)
                        c.pump(1.5)
                        res, before = "reloaded", 0
                    else:
                        res = c.eval(f"({fn})({json.dumps(st)})")
                    errs = c.errors()[before:]
                    if errs:
                        fails.append(f"step {i} {json.dumps(st)[:80]}: {res}, but it caused: " + " | ".join(errs[:3]))
                    else:
                        notes.append(f"OK    step {i}: {res}")
                except Exception as exc:
                    fails.append(f"step {i} {json.dumps(st)[:100]}: {exc}")
        if clicks:
            before = len(c.errors())
            res = c.eval(SMOKE, timeout=90) or []
            bad = [r for r in res if r.startswith("ERR")]
            notes.append(f"      clicked {len([r for r in res if not r.startswith('note')])} buttons one by one" + (f"; {len(bad)} threw errors" if bad else ", none threw an error"))
            for r in bad[:8]:
                fails.append("clicking " + r[4:])
            for e in c.errors()[before:]:
                if not any(e in b for b in bad):
                    fails.append(f"during clicks: {e}")
        shot = c.send("Page.captureScreenshot", {"format": "png"})
        if shot.get("data"):
            import base64
            path = "/tmp/aether-verify.png"
            with open(path, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            notes.append(f"      screenshot: {path}")
    finally:
        c.close()
    return fails, notes
