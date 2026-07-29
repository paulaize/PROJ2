#!/usr/bin/env python
"""Build manual T1 brain-mask worklist, dashboard, and nnU-Net manifest."""

from __future__ import annotations

from lys_bbb.mask_workflow import main_build_workflow


if __name__ == "__main__":
    raise SystemExit(main_build_workflow())
