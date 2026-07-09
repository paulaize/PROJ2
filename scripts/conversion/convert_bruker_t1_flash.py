#!/usr/bin/env python
"""CLI for converting Bruker T1 FLASH sessions to coronal NIfTI outputs."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.conversion import main


if __name__ == "__main__":
    raise SystemExit(main())
