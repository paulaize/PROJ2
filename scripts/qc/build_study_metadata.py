#!/usr/bin/env python
"""Build or refresh editable study metadata for side-aware quantification."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.study_metadata import main


if __name__ == "__main__":
    raise SystemExit(main())
