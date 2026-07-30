import json
from pathlib import Path


NOTEBOOK = Path(
    "notebooks/t1_brain_mask_standard3d_fold_all_t4x2_kaggle.ipynb"
)


def test_fold_all_notebook_is_clean_and_compilable() -> None:
    notebook = json.loads(NOTEBOOK.read_text())
    assert notebook["nbformat"] == 4
    assert all(cell.get("id") for cell in notebook["cells"])
    assert len({cell["id"] for cell in notebook["cells"]}) == len(
        notebook["cells"]
    )
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
            compile(
                "".join(cell["source"]),
                f"t1-fold-all-notebook-cell-{index}",
                "exec",
            )


def test_fold_all_notebook_runs_only_fold_all_on_two_gpus() -> None:
    notebook = json.loads(NOTEBOOK.read_text())
    source = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"]
    )
    assert "RUN_BENCHMARK_5E = False" in source
    assert "RUN_CV_250 = False" in source
    assert "RUN_FINAL_ALL_250 = True" in source
    assert "NUM_GPUS = 2" in source
    assert '"fold": "all"' in source
    assert '"probability_threshold": PROBABILITY_THRESHOLD' in source
    assert '"threshold_selection": "default_not_tuned"' in source
    assert '"oof_validation": False' in source
    assert "Review complete grouped OOF evidence" not in source
    assert "def predict_validation_without_tta" not in source
