#!/usr/bin/env python
"""Prepare nnU-Net raw data for the T1 brain-mask model."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.mask_workflow import main_prepare_nnunet


if __name__ == "__main__":
    raise SystemExit(main_prepare_nnunet())
