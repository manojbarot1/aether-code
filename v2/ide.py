#!/usr/bin/env python3
"""Aether Code — v2: a VS Code-style workspace (explorer, Monaco editor, terminals) with the Aether AI team.

Reuses v1's engine (engineers, team mode, memory, SSH hosts, sessions) from ../app.py — same data in ~/.aether-lite.
Run:  ./run-v2.sh
"""

from __future__ import annotations

import base64
import fcntl
import json
import mimetypes
import os
import pty
import shlex
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import app as v1  # noqa: E402  (the v1 chat/engineer engine)
import webview  # noqa: E402

IDE_STATE = v1.DATA / "ide.json"
MAX_TEXT = 5 * 1024 * 1024
IGNORE_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".next", "dist", "build", ".cache", ".idea", "target"}


def load_state() -> dict:
    try:
        return json.loads(IDE_STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    IDE_STATE.write_text(json.dumps(st))


class IdeApi(v1.Api):
    def __init__(self) -> None:
        super().__init__()
        self.terms: dict[str, dict] = {}

    # ───────────── helpers
    def _target(self, tid: str) -> dict | None:
        if not tid or tid == "local":
            return None
        return next((h for h in v1.load_cfg()["ssh"] if h["id"] == tid), None)

    def _sh(self, tid: str, cmd: str, stdin: bytes | None = None, timeout: int = 30) -> tuple[int, bytes, str]:
        """Run a shell snippet on this Mac or the SSH host. Returns (rc, stdout, stderr)."""
        t = self._target(tid)
        argv = v1.ssh_argv(t, cmd) if t else ["/bin/bash", "-lc", cmd]
        r = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout, env=v1.ENV)
        return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")

    def _abs(self, tid: str, path: str) -> str:
        return os.path.expanduser(path) if tid == "local" else path

    # ───────────── workspace state
    def ide_boot(self) -> dict:
        st = load_state()
        b = self.bootstrap()
        b["ide"] = {"workspace": st.get("workspace"), "recent": st.get("recent", []), "open": st.get("open", [])}
        return b

    def ide_save(self, patch: dict) -> bool:
        st = load_state()
        st.update(patch)
        save_state(st)
        return True

    # ───────────── files
    def fs_list(self, tid: str, path: str) -> dict:
        try:
            if tid == "local":
                p = Path(os.path.expanduser(path))
                items = []
                for e in os.scandir(p):
                    try:
                        isdir = e.is_dir(follow_symlinks=True)
                    except OSError:
                        isdir = False
                    items.append({"name": e.name, "dir": isdir})
            else:
                rc, out, err = self._sh(tid, f"{v1.remote_cd(path)} && pwd && find . -mindepth 1 -maxdepth 1 -printf '%Y\\t%f\\n'")
                lines = out.decode("utf-8", "replace").splitlines()
                if rc != 0 or not lines:
                    return {"error": err.strip() or "cannot open folder", "items": []}
                path = lines[0]
                items = []
                for ln in lines[1:]:
                    kind, _, name = ln.partition("\t")
                    items.append({"name": name, "dir": kind == "d"})   # %Y follows symlinks to their real type
            items.sort(key=lambda i: (not i["dir"], i["name"].lower()))
            return {"path": str(path), "items": items, "error": None}
        except Exception as exc:
            return {"error": str(exc)[:200], "items": []}

    def fs_read(self, tid: str, path: str) -> dict:
        try:
            if tid == "local":
                p = Path(os.path.expanduser(path))
                size = p.stat().st_size
                mtime = p.stat().st_mtime
                if size > MAX_TEXT * 4:
                    return {"error": f"File is too large to open ({size // 1024 // 1024} MB)"}
                data = p.read_bytes()
            else:
                rc, out, err = self._sh(tid, f"stat -c '%s %Y' {shlex.quote(path)} && base64 {shlex.quote(path)}", timeout=60)
                if rc != 0:
                    return {"error": err.strip() or "cannot read file"}
                head, _, b64 = out.decode().partition("\n")
                size, mtime = int(head.split()[0]), float(head.split()[1])
                if size > MAX_TEXT * 4:
                    return {"error": f"File is too large to open ({size // 1024 // 1024} MB)"}
                data = base64.b64decode(b64)
            mime = mimetypes.guess_type(path)[0] or ""
            if mime.startswith("image/") and len(data) < 8 * 1024 * 1024:
                return {"kind": "image", "mime": mime, "b64": base64.b64encode(data).decode(), "mtime": mtime}
            if b"\0" in data[:8192]:
                return {"kind": "binary", "size": size, "mtime": mtime}
            if len(data) > MAX_TEXT:
                return {"error": "File is too large for the editor (over 5 MB)"}
            return {"kind": "text", "text": data.decode("utf-8", "replace"), "mtime": mtime,
                    "crlf": b"\r\n" in data[:100000]}
        except Exception as exc:
            return {"error": str(exc)[:200]}

    def fs_write(self, tid: str, path: str, text: str) -> dict:
        try:
            data = text.encode("utf-8")
            if tid == "local":
                p = Path(os.path.expanduser(path))
                p.write_bytes(data)
                return {"ok": True, "mtime": p.stat().st_mtime}
            rc, out, err = self._sh(tid, f"cat > {shlex.quote(path)} && stat -c %Y {shlex.quote(path)}", stdin=data, timeout=60)
            return {"ok": rc == 0, "mtime": float(out.decode().strip() or 0), "error": err.strip() if rc else None}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def fs_stat(self, tid: str, paths: list[str]) -> dict:
        out: dict = {}
        try:
            if tid == "local":
                for p in paths:
                    try:
                        out[p] = Path(os.path.expanduser(p)).stat().st_mtime
                    except OSError:
                        out[p] = None
            elif paths:
                rc, o, _ = self._sh(tid, " ; ".join(f"stat -c '%Y' {shlex.quote(p)} 2>/dev/null || echo -" for p in paths))
                for p, v in zip(paths, o.decode().splitlines()):
                    out[p] = float(v) if v != "-" else None
        except Exception:
            pass
        return out

    def fs_new(self, tid: str, path: str, is_dir: bool) -> dict:
        try:
            if tid == "local":
                p = Path(os.path.expanduser(path))
                if p.exists():
                    return {"ok": False, "error": "Already exists"}
                p.mkdir(parents=True) if is_dir else (p.parent.mkdir(parents=True, exist_ok=True), p.touch())
                return {"ok": True}
            q = shlex.quote(path)
            rc, _, err = self._sh(tid, f"test ! -e {q} && " + (f"mkdir -p {q}" if is_dir else f"mkdir -p $(dirname {q}) && touch {q}"))
            return {"ok": rc == 0, "error": err.strip() or ("Already exists" if rc else None)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def fs_rename(self, tid: str, old: str, new: str) -> dict:
        try:
            if tid == "local":
                if Path(os.path.expanduser(new)).exists():
                    return {"ok": False, "error": "Target already exists"}
                os.rename(os.path.expanduser(old), os.path.expanduser(new))
                return {"ok": True}
            rc, _, err = self._sh(tid, f"test ! -e {shlex.quote(new)} && mv {shlex.quote(old)} {shlex.quote(new)}")
            return {"ok": rc == 0, "error": err.strip() or ("Target already exists" if rc else None)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def fs_delete(self, tid: str, path: str) -> dict:
        """Mac: moves to the Trash (recoverable). VM: permanent rm -rf (the UI confirms first)."""
        try:
            if tid == "local":
                p = os.path.expanduser(path)
                r = subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file {json.dumps(p)}'],
                                   capture_output=True, text=True, timeout=30)
                return {"ok": r.returncode == 0, "error": r.stderr.strip() or None}
            rc, _, err = self._sh(tid, f"rm -rf -- {shlex.quote(path)}")
            return {"ok": rc == 0, "error": err.strip() or None}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def pick_folder(self) -> str | None:
        res = self.window.create_file_dialog(webview.FOLDER_DIALOG) if self.window else None
        return res[0] if res else None

    def reveal(self, path: str) -> bool:
        subprocess.Popen(["open", "-R", os.path.expanduser(path)])
        return True

    # ───────────── search & index
    def files_index(self, tid: str, root: str) -> list[str]:
        """Relative file paths under root (for Cmd+P quick open)."""
        prune = " -o ".join(f"-name {shlex.quote(d)}" for d in IGNORE_DIRS)
        cmd = f"cd {shlex.quote(root) if tid != 'local' else shlex.quote(os.path.expanduser(root))} && " \
              f"find . \\( {prune} \\) -prune -o -type f -print 2>/dev/null | head -8000"
        if tid != "local":
            cmd = f"{v1.remote_cd(root)} && find . \\( {prune} \\) -prune -o -type f -print 2>/dev/null | head -8000"
        try:
            rc, out, _ = self._sh(tid, cmd, timeout=40)
            return [ln[2:] for ln in out.decode("utf-8", "replace").splitlines() if ln.startswith("./")]
        except Exception:
            return []

    def search(self, tid: str, root: str, query: str, case: bool = False) -> dict:
        if not query.strip():
            return {"results": []}
        flags = "" if case else "i"
        excl = " ".join(f"--exclude-dir={shlex.quote(d)}" for d in IGNORE_DIRS)
        base = shlex.quote(os.path.expanduser(root)) if tid == "local" else None
        cd = f"cd {base}" if tid == "local" else v1.remote_cd(root)
        cmd = f"{cd} && grep -rnI{flags}F {excl} -m 20 -- {shlex.quote(query)} . 2>/dev/null | head -400"
        try:
            rc, out, _ = self._sh(tid, cmd, timeout=45)
            res = []
            for ln in out.decode("utf-8", "replace").splitlines():
                parts = ln.split(":", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    res.append({"path": parts[0][2:] if parts[0].startswith("./") else parts[0], "line": int(parts[1]), "text": parts[2].strip()[:200]})
            return {"results": res}
        except Exception as exc:
            return {"results": [], "error": str(exc)[:160]}

    def git_info(self, tid: str, root: str) -> dict:
        cd = f"cd {shlex.quote(os.path.expanduser(root))}" if tid == "local" else v1.remote_cd(root)
        try:
            rc, out, _ = self._sh(tid, f"{cd} && git rev-parse --abbrev-ref HEAD 2>/dev/null && git status --porcelain 2>/dev/null | head -300", timeout=15)
            lines = out.decode("utf-8", "replace").splitlines()
            if rc != 0 or not lines:
                return {"branch": None, "changes": []}
            ch = [{"status": ln[:2].strip() or "?", "path": ln[3:]} for ln in lines[1:] if len(ln) > 3]
            return {"branch": lines[0], "changes": ch}
        except Exception:
            return {"branch": None, "changes": []}

    # ───────────── terminals (real PTYs: local shell or ssh -tt)
    def term_open(self, tid: str, cwd: str, cols: int = 100, rows: int = 24) -> str:
        t = self._target(tid)
        env = {**v1.ENV, "TERM": "xterm-256color", "LANG": "en_US.UTF-8"}
        if t:
            argv = v1.ssh_argv(t, f'{v1.remote_cd(cwd)} && exec "$SHELL" -l')
            argv.insert(1, "-tt")
            if "BatchMode=yes" in argv:      # allow interactive prompts (password / passphrase) in a real terminal
                i = argv.index("BatchMode=yes")
                del argv[i - 1:i + 1]
            cwd_local = None
        else:
            p = os.path.expanduser(cwd or "~")
            argv, cwd_local = [os.environ.get("SHELL", "/bin/zsh"), "-l"], (p if os.path.isdir(p) else str(Path.home()))
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd_local, env=env,
                                start_new_session=True, close_fds=True)
        os.close(slave)
        tidn = v1.uid()
        self.terms[tidn] = {"proc": proc, "fd": master}

        def reader() -> None:
            while True:
                try:
                    data = os.read(master, 8192)
                except OSError:
                    break
                if not data:
                    break
                try:
                    self.window.evaluate_js(f"window.termData('{tidn}','{base64.b64encode(data).decode()}')")
                except Exception:
                    pass
            try:
                self.window.evaluate_js(f"window.termExit('{tidn}')")
            except Exception:
                pass
            self.terms.pop(tidn, None)

        threading.Thread(target=reader, daemon=True).start()
        return tidn

    def term_write(self, tid: str, data: str) -> None:
        t = self.terms.get(tid)
        if t:
            try:
                os.write(t["fd"], data.encode("utf-8"))
            except OSError:
                pass

    def term_resize(self, tid: str, cols: int, rows: int) -> None:
        t = self.terms.get(tid)
        if t:
            try:
                fcntl.ioctl(t["fd"], termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.killpg(t["proc"].pid, signal.SIGWINCH)
            except Exception:
                pass

    def term_close(self, tid: str) -> None:
        t = self.terms.pop(tid, None)
        if t:
            try:
                os.killpg(t["proc"].pid, signal.SIGHUP)
            except Exception:
                pass

    def js_log(self, msg: str) -> None:
        with open("/tmp/aether-code-js.log", "a") as f:
            f.write(msg + "\n")

    def send(self, sid: str, text: str, context: str = ""):
        self._ctx = getattr(self, "_ctx", {})
        self._ctx[sid] = context
        return super().send(sid, text)

    def _prompt(self, sid, eng, cfg, st, target, directive="", proxy=False):
        ctx = getattr(self, "_ctx", {}).get(sid, "")
        if ctx:
            directive = f"Context from the user's editor (the IDE they are looking at right now):\n{ctx}\n\n" + (
                directive or f"Reply now as {eng['name']}.")
        return super()._prompt(sid, eng, cfg, st, target, directive, proxy)

    def shutdown(self) -> None:
        for k in list(self.terms):
            self.term_close(k)


def main() -> None:
    import atexit
    pidfile = v1.DATA / "run-v2.pid"
    pidfile.write_text(str(os.getpid()))
    atexit.register(lambda: pidfile.unlink(missing_ok=True))
    v1.init_db()
    v1.brand_app("Aether Code")
    api = IdeApi()
    api.window = webview.create_window(
        "Aether Code", str(HERE / "web" / "index.html"), js_api=api, width=1480, height=920, min_size=(1000, 600),
        transparent=True, vibrancy=True)
    atexit.register(api.shutdown)
    webview.start(lambda: __import__('PyObjCTools.AppHelper', fromlist=['callAfter']).callAfter(v1.install_edit_menu), http_server=True)


if __name__ == "__main__":
    main()
