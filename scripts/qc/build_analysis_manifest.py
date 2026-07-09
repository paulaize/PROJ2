#!/usr/bin/env python
"""Build the gated cohort analysis manifest from QC outputs."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lys_bbb.analysis_manifest import main


if __name__ == "__main__":
    raise SystemExit(main())
