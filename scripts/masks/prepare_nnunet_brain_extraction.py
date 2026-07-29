#!/usr/bin/env python
"""Prepare nnU-Net raw data for the T1 brain-mask model."""

from __future__ import annotations

from lys_bbb.mask_workflow import main_prepare_nnunet


if __name__ == "__main__":
    raise SystemExit(main_prepare_nnunet())
