"""Serve the React Flow variant to a browser using its own harness server.

Separate from ``live_editor.py`` because this variant's harness is already a
real HTTP server rather than a Playwright binding, so there is nothing to
replace: it is started as it is.

The harness is loaded by path rather than imported by name. It lives in
another checkout, so there is no importable name for it here, and putting its
directory on the path would only mean a static checker resolving something
that is not there.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / ".claude" / "worktrees" / "agent-a9f5840cbb88abf26"


def _load(name: str, path: Path) -> Any:
    """Return the module at *path*, loaded under *name*."""
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ImportError(f"no module at {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from awl import ui

    harness = _load("awl_reactflow_harness", ROOT / "tests" / "ui" / "harness.py")

    sample = Path(__file__).resolve().parents[1] / "src" / "awl" / "ui" / "sample.py"
    model = ui.load(sample.read_text(encoding="utf-8"), module="awl.ui.sample", file="sample.py")
    live = harness.Harness(model, scope="procedure")
    print("reactflow:", live.url, flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
