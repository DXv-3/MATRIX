"""Entry point for MATRIX.app — starts API+Web and opens browser."""

from __future__ import annotations

import os
import sys

# Ensure project root on path when launched from .app
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT))

from matrix.macos_app import open_matrix_app  # noqa: E402


def main() -> None:
    host = os.environ.get("MATRIX_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MATRIX_API_PORT", "8765"))
    msg = open_matrix_app(host=host, port=port)
    print(msg)


if __name__ == "__main__":
    main()