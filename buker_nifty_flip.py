#!/usr/bin/env python
"""Compatibility wrapper for the Bruker T1 FLASH converter.

Prefer `scripts/conversion/convert_bruker_t1_flash.py` for new pipeline
commands. This wrapper is kept so older documented commands and local notes do
not break while the project layout is being cleaned up.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.conversion import main


if __name__ == "__main__":
    raise SystemExit(main())
