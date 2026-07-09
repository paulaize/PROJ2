#!/usr/bin/env python
"""CLI for quantifying one pre/post T1 FLASH gadolinium pair."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.flash_pair import main


if __name__ == "__main__":
    raise SystemExit(main())
