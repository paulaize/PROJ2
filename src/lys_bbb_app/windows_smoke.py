"""The same executable startup check for Windows builds and offline installs."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import argparse
from pathlib import Path


def validate_models(root: Path) -> None:
    from lys_bbb.t2_model_release import validate_t2_model_release

    for relative in ("lys_v3_standard3d_nnunet",
                     "lys_v3_standard3d_nnunet/variants/folds_0_1",
                     "lys_v1_small_ratlesnetv2"):
        release = validate_t2_model_release(root / relative)
        print("Verified T2 model:", release.id, flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-directory", type=Path)
    args = parser.parse_args()
    if args.models_directory is not None:
        validate_models(args.models_directory)
    # Exercise inference imports as well as the desktop, not just pip metadata.
    import torch
    import ants
    import scipy
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
    from PySide6.QtWidgets import QApplication

    from lys_bbb_app.features import active_features
    from lys_bbb_app.ui.main_window import MainWindow

    require(ants.__version__ == "0.6.3", f"Unexpected ANTsPyx: {ants.__version__}")
    require(scipy.__version__ == "1.15.2", f"Unexpected SciPy: {scipy.__version__}")
    require(torch.ones(2, 2).matmul(torch.ones(2, 2)).sum().item() == 8,
            "Torch CPU calculation failed")
    nnUNetPredictor(device=torch.device("cpu"))
    for module in ("SimpleITK", "brkraw", "xlsxwriter", "sklearn", "yaml",
                   "webcolors", "PIL", "requests", "statsmodels", "torchvision"):
        importlib.import_module(module)
    app = QApplication.instance() or QApplication([])
    features = active_features()
    require(features.profile == "t2-only", "Expected the T2-only Windows profile")
    require(not features.t1_brain_mask, "T1 model generation must be disabled")
    require(not features.atlas_mapping, "Atlas mapping must remain disabled")
    require(features.ants_backend == "antspyx", "Unexpected registration backend")
    window = MainWindow(features=features)
    try:
        workspace = window.workspace_page
        require(workspace.atlas_mapping_panel is None, "Atlas UI unexpectedly enabled")
        require(not workspace.t1_brain_mask_panel.isEnabled(), "T1 model UI enabled")
        require(not workspace.tabs.isTabVisible(workspace._t1_brain_mask_tab),
                "T1 model tab is visible")
        require(workspace.t2_panel.isEnabled(), "T2 model UI is disabled")
        app.processEvents()
    finally:
        window.close()
    print(json.dumps({
        "status": "passed", "profile": features.profile,
        "versions": {name: importlib.metadata.version(name) for name in (
            "antspyx", "scipy", "numpy", "torch", "torchvision", "nnunetv2", "PySide6"
        )},
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
