"""Make `app` importable whether pytest is run from this directory or from an enclosing repo."""
from __future__ import annotations

import sys
from pathlib import Path

_APP_ROOT = str(Path(__file__).resolve().parents[1])
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)
