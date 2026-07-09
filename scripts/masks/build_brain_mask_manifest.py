#!/usr/bin/env python
"""Validate candidate brain masks from manual labels or model predictions."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.brain_mask_manifest import main


if __name__ == "__main__":
    raise SystemExit(main())
