"""Replies from free models, as they really come: the file in them must be written, or the agent told exactly why not.
Run: python3 -m unittest discover -s tests   (from .aether-code)"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("webview", types.ModuleType("webview"))
import app                       # noqa: E402
import api_engineer              # noqa: E402
import contract_check            # noqa: E402

F = "```"


def files(text):
    return {f["path"]: f["content"] for f in app.aether_block(text).get("files", [])}


class AetherBlock(unittest.TestCase):
    def test_valid_json(self):
        self.assertEqual(files(f'{F}aether\n{{"files": [{{"path": "a.js", "content": "x\\ny"}}]}}\n{F}'), {"a.js": "x\ny"})

    def test_wrong_closing_brackets(self):          # `}}}` instead of `}]}`
        self.assertEqual(files(f'{F}aether\n{{"files": [{{"path": "a.js", "content": "export {{ A }};\\n"}}}}}}\n{F}'),
                         {"a.js": "export { A };\n"})

    def test_js_escape(self):                       # \' is not valid JSON; the file keeps it
        got = files(f'{F}aether\n{{"files": [{{"path": "d.js", "content": "const s = \'Sun\\\'s mass\';"}}]}}\n{F}')
        self.assertEqual(got["d.js"], "const s = 'Sun\\'s mass';")

    def test_unescaped_html_quotes(self):           # the whole page, not the part before the first quote
        html = '<link rel="stylesheet" href="css/style.css">\\n<div id="app"></div>'
        got = files(f'{F}aether\n{{"files": [{{"path": "index.html", "content": "{html}"}}]}}\n{F}')
        self.assertEqual(got["index.html"], '<link rel="stylesheet" href="css/style.css">\n<div id="app"></div>')

    def test_unescaped_quotes_two_files(self):
        t = (f'{F}aether\n{{"files": [{{"path": "a.html", "content": "<a href="x">x</a>"}}, '
             f'{{"path": "b.js", "content": "let b = 1;"}}]}}\n{F}')
        self.assertEqual(files(t), {"a.html": '<a href="x">x</a>', "b.js": "let b = 1;"})

    def test_cut_off_file_is_not_written(self):
        t = f'{F}aether\n{{"files": [{{"path": "a.js", "content": "ok"}}, {{"path": "b.js", "content": "function half('
        self.assertEqual(files(t), {"a.js": "ok"})

    def test_trouble_messages(self):
        self.assertIn("cut off inside a ```run block", app.block_trouble(f"{F}run\ncat > a <<EOF\nhalf"))
        self.assertIn("not valid JSON", app.block_trouble(f'{F}aether\n{{"files": [{{"path": 1 2}}]}}\n{F}'))
        self.assertEqual(app.block_trouble("All done."), "")


class Continuation(unittest.TestCase):
    before = f'{F}aether\n{{"files": [{{"path": "a.js", "content": "const x = new THREE.LineLoop(g, m);\\n    solar'

    def test_reopened_fence_dropped(self):
        self.assertEqual(api_engineer.splice(self.before, f"{F}aether\nSystem.add(x);"), "System.add(x);")

    def test_repeated_lines_dropped(self):
        self.assertEqual(api_engineer.splice(self.before, "THREE.LineLoop(g, m);\\n    solarSystem.add(x)"), "System.add(x)")

    def test_plain_text_unchanged(self):
        self.assertEqual(api_engineer.splice("abc", "hello"), "hello")


class Plan(unittest.TestCase):
    plan = ("## Architecture\n```\nproj/\n├── index.html\n├── css/\n│   └── style.css\n└── js/\n    ├── main.js\n"
            "    ├── ui.js\n    └── anim.js\n```\n## Tasks\n@FreeLLM 2: page | files: index.html, css/style.css, js/ui.js\n")

    def test_arch_files(self):
        self.assertEqual(app.Api._arch_files(self.plan), ["index.html", "css/style.css", "js/main.js", "js/ui.js", "js/anim.js"])

    def test_orphans_go_to_page_owner(self):
        o = types.SimpleNamespace(_owners={"s": app.Api._parse_owners({"FreeLLM 2": "page | files: index.html, css/style.css, js/ui.js"})})
        o._owner_of = lambda sid, p: app.Api._owner_of(o, sid, p)
        o._arch_files = app.Api._arch_files
        self.assertEqual(app.Api._adopt_orphans(o, "s", self.plan), {"js/main.js": "FreeLLM 2", "js/anim.js": "FreeLLM 2"})

    def test_plan_done(self):
        self.assertTrue(app.Api.PLAN_DONE.search(self.plan))
        self.assertFalse(app.Api.PLAN_DONE.search("## Goal\nx\n## Requirements\n- R1"))


class Assets(unittest.TestCase):
    def test_fake_images_reported(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.jpg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            Path(d, "b.png").write_bytes(b"")
            Path(d, "ok.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 20)
            Path(d, "app.js").write_text("export const a = 1;")
            out = " ".join(contract_check.check(d))
            self.assertIn("a.jpg is SVG text", out)
            self.assertIn("b.png is an empty file", out)
            self.assertNotIn("ok.png", out)

    def test_importmap_prefix_without_slash(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "index.html").write_text('<script type="importmap">{"imports": {"three": "https://x/three.module.js", '
                                             '"three/addons": "https://x/jsm/"}}</script><script type="module" src="m.js"></script>')
            Path(d, "m.js").write_text("import * as THREE from 'three';\nimport { OrbitControls } from 'three/addons/controls/OrbitControls.js';")
            out = " ".join(contract_check.check(d))
            self.assertIn('needs a trailing slash ("three/addons/")', out)
            self.assertNotIn("imports 'three',", out)



class Steps(unittest.TestCase):
    def test_combined_step_split(self):
        import browser_check
        self.assertEqual(browser_check.split_steps([{"click": "#a", "expect": "#b", "visible": True}, {"expect": "#c"}]),
                         [{"click": "#a"}, {"expect": "#b", "visible": True}, {"expect": "#c"}])



class ManyBlocks(unittest.TestCase):
    def test_every_block_counts(self):
        t = (f'Here:\n{F}aether\n{{"files": [{{"path": "a.js", "content": "A"}}]}}\n{F}\nand\n'
             f'{F}aether\n{{"files": [{{"path": "b.js", "content": "B"}}]}}\n{F}\nfix:\n'
             f'{F}aether\n{{"files": [{{"path": "a.js", "content": "A2"}}]}}\n{F}')
        self.assertEqual(files(t), {"a.js": "A2", "b.js": "B"})

    def test_echoed_example_ignored(self):
        t = f'{F}aether\n{{"files": [{{"path": "src/app.ts", "content": "...the whole file..."}}]}}\n{F}'
        self.assertEqual(files(t), {})



class Snippets(unittest.TestCase):
    def test_elided_snippet_detected(self):
        for t in ("// ... rest of the file ...", "/* ... existing code */", "<!-- … remaining markup -->"):
            self.assertTrue(app.Api.ELIDED.search(t), t)
        for t in ("const a = [...rest];", "f(...args) // spread", "export { a };"):
            self.assertFalse(app.Api.ELIDED.search(t), t)



class Undo(unittest.TestCase):
    def test_snapshot_restore(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "js").mkdir()
            Path(d, "index.html").write_text("<div id=a></div>" * 50)
            Path(d, "js", "app.js").write_text("export const a = 1;")
            o = types.SimpleNamespace(E2E=app.Api.E2E, SNAP_SKIP=app.Api.SNAP_SKIP)
            old = app.eff_cwd
            app.eff_cwd = lambda st, t: d
            try:
                snap = app.Api._snapshot(o, {}, None)
                Path(d, "index.html").write_text("<p>gone</p>")       # a bad repair
                Path(d, "js", "app.js").unlink()
                Path(d, "new.js").write_text("x")
                changed = app.Api._restore(o, snap, {}, None)
            finally:
                app.eff_cwd = old
            self.assertEqual(sorted(changed), ["index.html", "js/app.js"])
            self.assertIn("<div id=a>", Path(d, "index.html").read_text())
            self.assertTrue(Path(d, "new.js").exists())



class Stall(unittest.TestCase):
    def test_stalled_provider_is_retried_then_continued(self):
        """A provider that goes silent (keep-alive pings, no text) must not freeze the job."""
        import http.server
        import subprocess
        import threading
        import time as _t
        calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                calls.append(1)
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                send = lambda t, fin=None: self.wfile.write(
                    ("data: " + __import__("json").dumps({"choices": [{"delta": {"content": t}, "finish_reason": fin}]}) + "\n\n").encode())
                try:
                    if len(calls) == 2:
                        send("Hello wor")
                    if len(calls) <= 2:
                        for _ in range(20):
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            _t.sleep(0.3)
                    else:
                        send("ld.", "stop")
                        self.wfile.write(b"data: [DONE]\n\n")
                except OSError:
                    pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            run = subprocess.run([sys.executable, os.path.join(os.path.dirname(api_engineer.__file__), "api_engineer.py"),
                                  "--base-url", f"http://127.0.0.1:{srv.server_port}/v1", "--model", "x"],
                                 input="hi", capture_output=True, text=True, timeout=60, env={**os.environ, "AETHER_STALL_SECS": "2"})
        finally:
            srv.shutdown()
        evs = [__import__("json").loads(l) for l in run.stdout.splitlines() if l.strip()]
        self.assertEqual("".join(e["text"] for e in evs if e["type"] == "text"), "Hello world.")
        self.assertTrue(evs[-1]["ok"])



class Exports(unittest.TestCase):
    def test_export_of_nested_or_missing_name(self):
        u = contract_check._undefined_exports
        self.assertEqual(u("const init = () => {\n  const animate = () => {};\n};\nexport { init, animate };"), ["animate"])
        self.assertEqual(u("function a(){}\nconst b = 1, c = 2;\nlet {d} = o;\nimport { f } from './f.js';\nexport { a, b, c, d, f as g };"), [])


class Shrink(unittest.TestCase):
    def test_gutting_a_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "ui.js").write_text("x" * 8000)
            o = types.SimpleNamespace(_baseline={}, _turn_t0={"s": 1.0}, _request={"s": "fix the failing checks"},
                                      SNAP_SKIP=app.Api.SNAP_SKIP, REWRITE_OK=app.Api.REWRITE_OK)
            old = app.eff_cwd
            app.eff_cwd = lambda st, t: d
            try:
                self.assertIn("shrink ui.js", app.Api._shrinks(o, "s", {}, None, "ui.js", "export const ui = 1;"))
                self.assertEqual(app.Api._shrinks(o, "s", {}, None, "ui.js", "y" * 6000), "")      # a real edit
                self.assertEqual(app.Api._shrinks(o, "s", {}, None, "new.js", "z"), "")             # a new file
                o._request["s"] = "rewrite ui.js from scratch, minimal"
                self.assertEqual(app.Api._shrinks(o, "s", {}, None, "ui.js", "export const ui = 1;"), "")
            finally:
                app.eff_cwd = old

    def test_repair_request_words(self):
        for t in ("fix the failing checks", "finish the project", "continue", "it's broken"):
            self.assertTrue(app.Api.FIX_REQ.search(t), t)
        self.assertFalse(app.Api.FIX_REQ.search("add a dark mode toggle"))


if __name__ == "__main__":
    unittest.main()
