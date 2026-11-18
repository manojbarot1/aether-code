"""Static checks that catch integration mistakes between files written by different engineers, all at once
(a browser stops at the first one): ES-module / CommonJS imports that name something the other file doesn't
export, imports of files that don't exist, and HTML that references missing local files or element ids the
scripts never find."""
from __future__ import annotations

import re
from pathlib import Path

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".aether", ".cache", "target"}
JS_EXT = (".js", ".mjs", ".cjs", ".jsx")

IMPORT_NAMED = re.compile(r"import\s*(?:([\w$]+)\s*,\s*)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]", re.S)
IMPORT_DEFAULT = re.compile(r"import\s+([\w$]+)\s+from\s*['\"]([^'\"]+)['\"]")
IMPORT_BARE = re.compile(r"import\s*(?:\*\s*as\s*[\w$]+\s*from\s*)?['\"]([^'\"]+)['\"]")
REQUIRE = re.compile(r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)")
EXPORT_DECL = re.compile(r"export\s+(?:async\s+)?(?:function\s*\*?|class|const|let|var)\s+([\w$]+)")
EXPORT_LIST = re.compile(r"export\s*\{([^}]*)\}(?:\s*from\s*['\"]([^'\"]+)['\"])?")
EXPORT_DEFAULT = re.compile(r"export\s+default\b")
EXPORT_STAR = re.compile(r"export\s*\*\s*from\s*['\"]([^'\"]+)['\"]")
CJS_EXPORTS = re.compile(r"(?:module\.)?exports\.([\w$]+)\s*=|module\.exports\s*=\s*\{([^}]*)\}")
COMMENT = re.compile(r"/\*.*?\*/|(?<![:'\"\\])//[^\n]*", re.S)


def _files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP):
            yield p


def _resolve(src: Path, spec: str) -> Path | None:
    if not spec.startswith("."):
        return None                      # a package or a URL: not ours to check
    base = (src.parent / spec).resolve()
    for cand in (base, base.with_suffix(base.suffix + ".js") if base.suffix not in JS_EXT else base, base / "index.js",
                 Path(str(base) + ".js"), Path(str(base) + ".mjs")):
        if cand.is_file():
            return cand
    return base                         # missing: reported by the caller


def _names(block: str) -> list[str]:
    out = []
    for part in block.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(re.split(r"\s+as\s+", part)[0].strip())
    return [n for n in out if re.match(r"^[\w$]+$", n)]


def exports_of(path: Path, seen: set | None = None) -> tuple[set[str], bool]:
    """(exported names, has default)."""
    seen = seen or set()
    if path in seen or not path.is_file():
        return set(), False
    seen.add(path)
    code = COMMENT.sub("", path.read_text(errors="replace"))
    names = set(EXPORT_DECL.findall(code))
    for block, frm in EXPORT_LIST.findall(code):
        for part in block.split(","):
            part = part.strip()
            if part:
                bits = re.split(r"\s+as\s+", part)
                names.add(bits[-1].strip())
    for frm in EXPORT_STAR.findall(code):
        r = _resolve(path, frm)
        if r:
            names |= exports_of(r, seen)[0]
    for one, many in CJS_EXPORTS.findall(code):
        if one:
            names.add(one)
        if many:
            names |= {re.split(r"\s*:\s*", x.strip())[0] for x in many.split(",") if x.strip()}
    default = bool(EXPORT_DEFAULT.search(code)) or "module.exports" in code
    names.discard("default")
    return names, default


def check(root: str | Path) -> list[str]:
    root = Path(root).resolve()
    problems: list[str] = []
    js = [p for p in _files(root) if p.suffix in JS_EXT]
    if len(js) > 400:
        return []
    rel = lambda p: str(p.relative_to(root)) if str(p).startswith(str(root)) else str(p)
    for src in js:
        code = COMMENT.sub("", src.read_text(errors="replace"))
        for default, block, spec in IMPORT_NAMED.findall(code):
            tgt = _resolve(src, spec)
            if tgt is None:
                continue
            if not tgt.is_file():
                problems.append(f"{rel(src)} imports from '{spec}', which does not exist")
                continue
            have, has_default = exports_of(tgt)
            missing = [n for n in _names(block) if n not in have]
            if missing:
                problems.append(f"{rel(src)} imports {{{', '.join(missing)}}} from '{spec}', but {rel(tgt)} does not export "
                                f"{'it' if len(missing) == 1 else 'them'}. It exports: {', '.join(sorted(have)) or '(nothing)'}")
            if default and not has_default:
                problems.append(f"{rel(src)} imports a default export '{default}' from '{spec}', but {rel(tgt)} has no `export default`")
        for name, spec in IMPORT_DEFAULT.findall(code):
            tgt = _resolve(src, spec)
            if tgt is None:
                continue
            if not tgt.is_file():
                problems.append(f"{rel(src)} imports from '{spec}', which does not exist")
            elif not exports_of(tgt)[1]:
                problems.append(f"{rel(src)} imports a default export '{name}' from '{spec}', but {rel(tgt)} has no `export default`")
        for spec in IMPORT_BARE.findall(code):
            tgt = _resolve(src, spec)
            if tgt is not None and not tgt.is_file():
                problems.append(f"{rel(src)} imports '{spec}', which does not exist")
        for block, spec in REQUIRE.findall(code):
            tgt = _resolve(src, spec)
            if tgt is None:
                continue
            if not tgt.is_file():
                problems.append(f"{rel(src)} requires '{spec}', which does not exist")
                continue
            have, _ = exports_of(tgt)
            missing = [n for n in _names(block.replace(":", " as ")) if n not in have]
            if missing and have:
                problems.append(f"{rel(src)} requires {{{', '.join(missing)}}} from '{spec}', but {rel(tgt)} does not export them. It exports: {', '.join(sorted(have))}")
    # HTML: local files it references, and ids that scripts look up but the page doesn't have
    all_js = "\n".join(p.read_text(errors="replace") for p in js[:200])
    for page in [p for p in _files(root) if p.suffix == ".html"][:20]:
        html = page.read_text(errors="replace")
        for ref in re.findall(r"""(?:src|href)\s*=\s*["']([^"'#?]+)["']""", html):
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", ref, re.I):
                continue                                   # a URL (CDN, mailto, data:)
            target = (root / ref.lstrip("/")) if ref.startswith("/") else (page.parent / ref)
            if not target.exists():
                problems.append(f"{rel(page)} references '{ref}', which does not exist")
        ids = set(re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", html))
        if ids and len([p for p in _files(root) if p.suffix == ".html"]) == 1:
            wanted = set(re.findall(r"""getElementById\(\s*['"]([\w-]+)['"]\s*\)""", all_js))
            wanted |= set(re.findall(r"""querySelector(?:All)?\(\s*['"]#([\w-]+)['"]\s*\)""", all_js))
            made = set(re.findall(r"""\.id\s*=\s*['"`]([\w-]+)""", all_js)) | set(re.findall(r"""id=\\?["']([\w-]+)""", all_js))
            missing = sorted(w for w in wanted - ids - made)
            if missing:
                problems.append(f"scripts look up element id(s) {', '.join('#' + m for m in missing[:12])} that {rel(page)} does not have")
    problems += _state_classes(root, js)
    problems += _bad_assets(root)
    problems += _importmap(root, js)
    return list(dict.fromkeys(problems))


def _importmap(root: Path, js: list[Path]) -> list[str]:
    """Bare imports (`three`, `three/addons/x.js`) in browser modules must resolve through the page's importmap: an exact
    key, or a key ending in "/" that prefixes them. A prefix key without its "/" ("three/addons") resolves nothing, and
    the whole page dies with 'Failed to resolve module specifier'."""
    import json as _json
    pages = [p for p in _files(root) if p.suffix == ".html"]
    maps: dict[str, str] = {}
    for page in pages:
        for raw in re.findall(r"""<script[^>]*type\s*=\s*["']importmap["'][^>]*>(.*?)</script>""", page.read_text(errors="replace"), re.S | re.I):
            try:
                maps.update((_json.loads(raw).get("imports") or {}))
            except ValueError:
                return [f"{page.relative_to(root)} has an importmap that is not valid JSON, so every bare import fails"]
    if not maps or (root / "package.json").exists():
        return []                          # no importmap (bundler / Node project): not a browser-import setup to check
    out = []
    for src in js:
        code = COMMENT.sub("", src.read_text(errors="replace"))
        for spec in set(re.findall(r"""(?:\bfrom|\bimport)\s*\(?\s*['"]([^'"./][^'"]*)['"]""", code)):
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", spec, re.I):
                continue
            if spec in maps or any(k.endswith("/") and spec.startswith(k) for k in maps):
                continue
            near = max((k for k in maps if spec.startswith(k + "/")), key=len, default=None)
            out.append(f"{src.relative_to(root)} imports '{spec}', which the page's importmap doesn't resolve"
                       + (f": the key \"{near}\" needs a trailing slash (\"{near}/\") to map a path prefix" if near else
                          f". Add it to the importmap (keys: {', '.join(sorted(maps))})"))
    return out[:6]


MAGIC = {".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG",), ".gif": (b"GIF8",),
         ".webp": (b"RIFF",), ".bmp": (b"BM",), ".ico": (b"\x00\x00\x01\x00",), ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3"),
         ".wav": (b"RIFF",), ".ogg": (b"OggS",), ".woff2": (b"wOF2",), ".woff": (b"wOFF",)}


def _bad_assets(root: Path) -> list[str]:
    """Images, sounds and fonts that are empty or not what their extension says (a model can't download binaries, so it
    writes an empty file or SVG text called earth.jpg). The browser fails to decode them: a black planet, a missing icon."""
    out = []
    for p in _files(root):
        ext = p.suffix.lower()
        if ext not in MAGIC:
            continue
        head = p.read_bytes()[:64]
        rel = str(p.relative_to(root))
        if not head:
            out.append(f"{rel} is an empty file")
        elif not head.startswith(MAGIC[ext]) or (ext == ".webp" and b"WEBP" not in head[:16]):
            kind = "SVG text" if b"<svg" in head.lower() or b"<?xml" in head.lower() else "text" if head.isascii() else "not a real file of that type"
            out.append(f"{rel} is {kind}, not a real {ext[1:].upper()} image/file")
    if not out:
        return []
    return [f"{len(out)} asset file(s) can't be decoded by the browser: {'; '.join(out[:8])}. Binary files can't be written as text: "
            "draw textures in code (a <canvas> → THREE.CanvasTexture, CSS gradients), save real SVG as .svg, or load from a "
            "URL that really exists"]


STATE_WORDS = {"active", "open", "opened", "show", "shown", "visible", "is-open", "is-active", "is-visible", "expanded",
               "selected", "dragging", "drag-over", "dragover", "over", "hidden", "is-hidden", "closed", "collapsed", "on"}


def _state_classes(root: Path, js: list[Path]) -> list[str]:
    """CSS that shows or hides things with a state class (`.modal.active`, `.menu.open`) which no script ever adds:
    the element can never change state, e.g. a dialog that never appears."""
    css = "\n".join(p.read_text(errors="replace") for p in _files(root) if p.suffix == ".css")
    if not css or not js:
        return []
    html = "\n".join(p.read_text(errors="replace") for p in _files(root) if p.suffix == ".html")
    code = "\n".join(p.read_text(errors="replace") for p in js)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    used = set()
    for sel in re.findall(r"([^{}]+)\{", css):
        for m in re.finditer(r"\.([\w-]+)((?:\.[\w-]+)+)", sel):
            for st in m.group(2).split(".")[1:]:
                if st in STATE_WORDS:
                    used.add((m.group(1), st))
    static = set(re.findall(r"[\w-]+", " ".join(re.findall(r"""class\s*=\s*["']([^"']*)["']""", html))))
    out = []
    for base, st in sorted(used):
        if st in static or re.search(rf"""['"`\s.]{re.escape(st)}['"`\s]""", code):
            continue
        out.append(f"the CSS styles `.{base}.{st}` but no script ever adds the class '{st}' — that state can never be reached "
                   f"(e.g. a .{base} that never opens/shows); make the script toggle '{st}' or change the CSS")
    return out[:8]


if __name__ == "__main__":
    import sys
    found = check(sys.argv[1] if len(sys.argv) > 1 else ".")
    print("\n".join(f"FAIL  {p}" for p in found) or "OK    imports, exports, file references and element ids match")
    sys.exit(1 if found else 0)
