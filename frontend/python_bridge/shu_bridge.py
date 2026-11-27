"""Compatibility entry point for the integrated SHU desktop UI (no HTTP server)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.interface.frontend import main

if __name__ == "__main__":
    raise SystemExit(main())
