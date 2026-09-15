#!/usr/bin/env python3
"""
Verify every Mermaid diagram in docs/*.md actually parses and renders.

Broken Mermaid fails *silently* on GitHub — the block renders as an error
box, or as nothing, and nobody notices until a reader hits it. This
builds a single page containing every diagram in the docs, parses each
one, and reports a pass/fail tally.

Usage:
    npm install mermaid            # once, anywhere; see --mermaid below
    python docs/verify_diagrams.py --mermaid path/to/mermaid.min.js
    # then open the printed URL and read the banner at the top

A green banner means every diagram parsed and rendered. A red one names
the file, the diagram's index within it, and the parser error.
"""

from __future__ import annotations

import argparse
import html
import http.server
import pathlib
import re
import shutil
import socketserver
import tempfile

DOCS = pathlib.Path(__file__).resolve().parent
BLOCK = re.compile(r"```mermaid\n(.*?)\n```", re.S)

PAGE_HEAD = """<meta charset='utf-8'><title>diagram check</title>
<style>
 body{background:#edf0f5;color:#111;font:14px system-ui;margin:0;padding:16px}
 h3{font:600 13px ui-monospace;margin:22px 0 6px;color:#444}
 .box{background:#fff;border:1px solid #bbb;padding:10px;overflow-x:auto}
 #tally{position:sticky;top:0;background:#111;color:#fff;padding:11px;
        font:600 15px ui-monospace;z-index:9}
</style>
<div id='tally'>rendering…</div>
"""

PAGE_TAIL = """<script src='mermaid.min.js'></script>
<script>
mermaid.initialize({startOnLoad:false});
(async () => {
  const nodes = [...document.querySelectorAll('pre.mermaid')];
  let ok = 0; const bad = [];
  for (const n of nodes) {
    const label = n.parentElement.previousElementSibling.textContent;
    try { await mermaid.parse(n.textContent); ok++; }
    catch (e) { bad.push(label + ' :: ' + (e.message || e).split('\\n')[0]); }
  }
  await mermaid.run({nodes});
  const t = document.getElementById('tally');
  t.textContent = bad.length
    ? `FAIL ${bad.length}/${nodes.length}  |  ` + bad.join('  ||  ')
    : `ALL ${ok}/${nodes.length} DIAGRAMS PARSED AND RENDERED OK`;
  t.style.background = bad.length ? '#a11' : '#161';
})();
</script>"""


def collect() -> list[tuple[str, str]]:
    found = []
    for md in sorted(DOCS.glob("*.md")):
        for i, m in enumerate(BLOCK.finditer(md.read_text(encoding="utf-8")), 1):
            found.append((f"{md.name} #{i}", m.group(1)))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mermaid", required=True,
                    help="Path to mermaid.min.js (node_modules/mermaid/dist/mermaid.min.js)")
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()

    src = pathlib.Path(args.mermaid)
    if not src.is_file():
        print(f"mermaid.min.js not found at {src}")
        return 1

    diagrams = collect()
    if not diagrams:
        print("No mermaid blocks found in docs/.")
        return 1

    parts = [PAGE_HEAD]
    for name, body in diagrams:
        parts.append(f"<h3>{html.escape(name)}</h3>")
        parts.append(f"<div class='box'><pre class='mermaid'>{html.escape(body)}</pre></div>")
    parts.append(PAGE_TAIL)

    # Served from a temp dir so nothing is vendored into the repo -
    # mermaid.min.js is several MB and has no business in version control.
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="diagcheck-"))
    (tmp / "index.html").write_text("\n".join(parts), encoding="utf-8")
    shutil.copy(src, tmp / "mermaid.min.js")

    print(f"{len(diagrams)} diagrams from {len({n.split(' #')[0] for n, _ in diagrams})} files")
    for name, _ in diagrams:
        print(f"  - {name}")
    print(f"\nServing http://localhost:{args.port}/  (Ctrl-C to stop)")
    print("Open it and read the banner at the top of the page.\n")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(tmp), **kw)

        def log_message(self, *a):  # keep the console readable
            pass

    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
