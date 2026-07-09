#!/usr/bin/env python
"""Build manual T1 brain-mask worklist, dashboard, and nnU-Net manifest."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.mask_workflow import main_build_workflow


if __name__ == "__main__":
    raise SystemExit(main_build_workflow())
