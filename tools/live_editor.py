"""Serve one editor variant to a real browser.

The variants' own harnesses reach Python through Playwright's
``expose_function``, which exists only inside a Playwright page. That is the
right call for a test and makes them unopenable in an ordinary browser, so this
serves the same harness with the same widget and replaces that one binding with
an HTTP round trip.

Nothing else is replaced. The widget module is the package's own ``_esm``, the
traits are the widget's, and every edit goes through ``awl.ui.EditorModel``, so
what you click is what the tests exercise.

Usage::

    python tools/live_editor.py --variant blockly --root <checkout> --port 8101
"""

from __future__ import annotations

import argparse
import http.server
import json
import sys
from pathlib import Path
from typing import Any

#: The bridge each variant's harness calls, and the traits it round-trips.
BRIDGES = {
    # Every trait the variant's own tests sync. A short list is not a smaller
    # widget, it is a broken one: leaving out `highlighted` served a blank
    # source pane, which reads as an unimplemented requirement rather than as
    # a launcher that forgot to carry it.
    "blockly": (
        "awlSync",
        ("level", "palette", "overlay", "source", "highlighted", "error", "status", "loop_mode"),
    ),
    "reactflow_jedison": ("awlDispatch", ("selection", "pending_edit", "open_step", "close_to")),
}

#: What each variant needs before its run button can do anything. Without it
#: the button renders and says there is no entry point, which reads as a
#: broken widget rather than as an unconfigured host: the host decides what
#: running means, because a stand-in for a module that drives hardware is an
#: object and no JSON channel carries one.
RUNS = {
    "blockly": {"entry": "procedure", "arguments": (3,)},
    "reactflow_jedison": {"run_with": {"entry": "procedure", "arguments": (3,)}},
}

#: Injected before the harness's own module runs, so the binding exists by the
#: time it is called. A promise, because Playwright's version is async and the
#: harness awaits it.
SHIM = """<script>
window.%(bridge)s = async function (payload) {
  const response = await fetch('/bridge', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(payload || {}),
  })
  return await response.json()
}
</script>
"""


def _asset(value: Any) -> bytes:
    """Return an anywidget asset, which is a path in one variant and the text
    itself in another. Both are what anywidget accepts for ``_esm``.
    """
    if isinstance(value, Path):
        return value.read_bytes()
    text = str(value)
    return Path(text).read_bytes() if len(text) < 260 and Path(text).exists() else text.encode("utf-8")


def _model(root: Path):
    """Return the sample every variant opens on.

    The text comes from this checkout and the model from the variant's, so a
    worktree that has not pulled the sample yet still opens on it and the three
    are still being compared on one procedure.
    """
    from awl import ui

    sample = Path(__file__).resolve().parents[1] / "src" / "awl" / "ui" / "sample.py"
    return ui.load(sample.read_text(encoding="utf-8"), module="awl.ui.sample", file="sample.py")


def serve(variant: str, root: Path, port: int) -> None:
    """Serve *variant* from the checkout at *root* on *port*."""
    sys.path.insert(0, str(root / "src"))
    module = __import__(f"awl.ui.{variant}", fromlist=["*"])

    bridge, traits = BRIDGES[variant]
    widget = next(
        getattr(module, name)(_model(root), scope="procedure", **RUNS.get(variant, {}))
        for name in dir(module)
        if name.endswith("Editor")
    )

    harness = (root / "tests" / "ui" / "harness.html").read_text(encoding="utf-8")
    harness = harness.replace("<body>", "<body>\n" + SHIM % {"bridge": bridge}, 1)

    def state() -> dict[str, Any]:
        if hasattr(widget, "state"):
            return widget.state()
        return {name: getattr(widget, name) for name in traits}

    routes = {
        "/": ("text/html; charset=utf-8", harness.encode("utf-8")),
        "/index.html": ("text/html; charset=utf-8", harness.encode("utf-8")),
        "/widget.js": ("text/javascript; charset=utf-8", _asset(module.ESM)),
        "/widget.css": ("text/css; charset=utf-8", _asset(module.CSS)),
    }

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _handler(widget, state, routes))
    print(f"{variant}: http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()


def _handler(widget: Any, state: Any, routes: dict[str, tuple[str, bytes]]) -> type:
    """Return the request handler serving one widget."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class names it this
            """Quiet: this runs in the background behind a browser."""

        def _send(self, kind: str, body: bytes) -> None:
            self.send_response(200)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/state.json":
                self._send("application/json", json.dumps(state()).encode("utf-8"))
                return
            found = routes.get(path)
            if found is None:
                self.send_error(404)
                return
            self._send(*found)

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["content-length"] or 0)) or b"{}")
            for name, value in payload.items():
                if hasattr(widget, name) and value is not None and value != getattr(widget, name):
                    setattr(widget, name, value)
            self._send("application/json", json.dumps(state()).encode("utf-8"))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=sorted(BRIDGES))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    arguments = parser.parse_args()
    serve(arguments.variant, arguments.root.resolve(), arguments.port)


if __name__ == "__main__":
    main()
