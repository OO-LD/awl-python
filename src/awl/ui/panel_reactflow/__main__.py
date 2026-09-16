"""Serve the editor: ``python -m awl.ui.panel_reactflow --port 8104``.

The other four variants are anywidgets and need no server at all; this one is a
Panel application, so running it is starting one. That is the cost of the choice
and it is stated here rather than in a footnote.
"""

from __future__ import annotations

import argparse

from awl.ui.panel_reactflow import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8104, help="the port to serve on")
    parser.add_argument("--show", action="store_true", help="open a browser")
    arguments = parser.parse_args()
    serve(port=arguments.port, show=arguments.show)


if __name__ == "__main__":
    main()
