import json
from pathlib import Path

NOTEBOOK = Path("notebooks/t1_brain_mask_standard3d_nnunet_kaggle.ipynb")
PROTOCOL = Path("docs/t1_brain_mask_nnunet_training.md")


def test_t1_nnunet_notebook_is_clean_json_with_compilable_code() -> None:
    notebook = json.loads(NOTEBOOK.read_text())
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 32
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
                f"t1-nnunet-notebook-cell-{index}",
                "exec",
            )


def test_t1_nnunet_notebook_pins_grouping_and_compact_release_contract() -> None:
    notebook = json.loads(NOTEBOOK.read_text())
    source = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"]
    )
    assert "468cf803df9b267150ae2b6c0c59b8ac84f16227" in source
    assert 'CONFIGURATION = "3d_fullres"' in source
    assert 'PLANNER = "ExperimentPlanner"' in source
    assert "PlainConvUNet" in source
    assert "ResidualEncoderUNet" in source
    assert "animal_id" in source
    assert "mask_review" in source
    assert "reviewer" in source
    assert "reviewed_at" in source
    assert "image_sha256" in source
    assert "mask_sha256" in source
    assert "self.save_every = 1" in source
    assert '"fold": "all"' in source
    assert '"model_count": 1' in source
    assert "portable_checkpoint" in source
    assert '"postprocessing": "none"' in source
    assert "--disable_tta" in source
    assert "pooled_voxel_dice" in source
    assert "surface_dice" in source
    assert "Overall voxel accuracy is intentionally absent" in source
    assert "predictions_are_drafts" in source


def test_t1_nnunet_protocol_preserves_quantification_boundary() -> None:
    source = PROTOCOL.read_text()
    assert "34 pre-Gd T1-weighted scans" in source
    assert "17 animal identifiers" in source
    assert "30,785,994" in source
    assert "117.4 MiB" in source
    assert "not estimate gadolinium concentration" in source
    assert "postprocessing none" in source
    assert "one final all-data model" in source
    assert "Every released prediction remains a draft mask" in source
