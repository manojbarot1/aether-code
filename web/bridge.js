// Browser stand-in for pywebview, loaded by web.py before the UI's own scripts.
// window.pywebview.api.<method>(...args) → POST /api/<method>; engine events arrive
// over Server-Sent Events and are handed to window.onEvent exactly as in the desktop app.
(() => {
  // Optional token (AETHER_WEB_TOKEN), passed once as #token=… and kept for this tab.
  const fromHash = new URLSearchParams(location.hash.slice(1)).get('token');
  if (fromHash) {
    try { sessionStorage.setItem('aetherToken', fromHash); } catch {}
    history.replaceState(null, '', location.pathname);
  }
  let token = '';
  try { token = sessionStorage.getItem('aetherToken') || ''; } catch {}

  async function call(name, args) {
    const res = await fetch(`/api/${name}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-aether-web': '1', 'x-aether-token': token },
      body: JSON.stringify({ args }),
    });
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) {
      const t = prompt('Aether web token (AETHER_WEB_TOKEN):');
      if (t) { token = t; try { sessionStorage.setItem('aetherToken', t); } catch {} return call(name, args); }
    }
    if (!res.ok) throw new Error(body.error || res.statusText);
    return body.result;
  }

  // The clipboard belongs to the browser's machine, not the server's, so use the browser's
  // when it allows it (localhost or https) and fall back to the server otherwise.
  const local = {
    clip_get: async () => { try { return await navigator.clipboard.readText(); } catch { return call('clip_get', []); } },
    clip_set: async text => { try { await navigator.clipboard.writeText(text); return true; } catch { return call('clip_set', [text]); } },
  };

  window.pywebview = {
    api: new Proxy({}, { get: (_, name) => local[name] || ((...args) => call(String(name), args)) }),
  };

  function listen() {
    const es = new EventSource(`/events${token ? `?token=${encodeURIComponent(token)}` : ''}`);
    es.onmessage = e => {
      try { if (window.onEvent) window.onEvent(JSON.parse(e.data)); } catch (err) { console.error(err); }
    };
    // EventSource reconnects by itself; nothing to do on error.
  }

  window.addEventListener('DOMContentLoaded', () => {
    document.documentElement.classList.add('web');
    // The desktop window is transparent (macOS vibrancy shows through); a browser tab is not.
    const style = document.createElement('style');
    style.textContent = 'html.web,html.web body{background:var(--bg-solid)}';
    document.head.appendChild(style);
    // The desktop app's "Choose in Finder…" opens a native dialog, which a browser cannot do:
    // point the user at the path field of the folder browser instead.
    window.finderPick = () => { const f = document.getElementById('br_path'); if (f) { f.focus(); f.select(); } };
    listen();
    window.dispatchEvent(new Event('pywebviewready'));
  });
})();
