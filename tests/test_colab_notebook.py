import json
from pathlib import Path


NOTEBOOK = Path("notebooks/brain_extraction_colab_benchmark.ipynb")
EXTRA_NOTEBOOK = Path("notebooks/brain_extraction_colab_extra_baselines.ipynb")


def test_colab_notebook_is_clean_valid_json_with_compilable_code() -> None:
    notebook = json.loads(NOTEBOOK.read_text())
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 11
    assert all(cell.get("id") for cell in notebook["cells"])
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
            compile("".join(cell["source"]), f"notebook-cell-{index}", "exec")


def test_colab_notebook_pins_models_and_conforms_to_result_contract() -> None:
    source = "\n".join("".join(cell["source"]) for cell in json.loads(NOTEBOOK.read_text())["cells"])
    assert "5d67d622a0f67031494cc6e94867feabafee0bb8" in source
    assert "144b032df4885a3da00e0d1824fdd777b3cd304f" in source
    assert "mbe_invivo_iso" in source
    assert "mbe_invivo_aniso" in source
    assert "rs2net" in source
    assert "run_manifest.csv" in source
    assert "t1_brain_extraction_results.zip" in source
    assert "TensorFlow 1.15/Keras 2.2.4" in source
    assert "monai==1.4.0" in source
    assert "monai==1.3.0" not in source
    assert "Runtime preflight" in source
    assert "Model preflight" in source
    assert source.index("Runtime preflight") < source.index("Downloading MouseBrainExtractor weights")
    assert "weights_only=False" in source
    assert "RS2 checkpoint preflight: state_dict found" in source
    assert source.index("weights_only=False") < source.index("RS2_predict', '-i'")
    assert "rs2-probability-threshold-sweep" in NOTEBOOK.read_text()
    assert "--save_probabilities" in source
    assert "RS2_THRESHOLDS = (0.50, 0.60, 0.70, 0.80, 0.90, 0.95)" in source
    assert "orientation_validation_dice_at_0.50" in source
    assert "widgets.interactive_output" in source
    assert "rs2_threshold_sweep_results.zip" in source


def test_extra_colab_notebook_is_clean_valid_json_with_compilable_code() -> None:
    notebook = json.loads(EXTRA_NOTEBOOK.read_text())
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) == 9
    assert all(cell.get("id") for cell in notebook["cells"])
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
            compile("".join(cell["source"]), f"extra-notebook-cell-{index}", "exec")


def test_extra_colab_notebook_pins_controls_and_declares_domain_mismatch() -> None:
    source = "\n".join(
        "".join(cell["source"])
        for cell in json.loads(EXTRA_NOTEBOOK.read_text())["cells"]
    )
    assert "dfa1a123495628d5d8ffe576999f8f1ddfd1973a" in source
    assert "deepbet==1.0.2" in source
    assert "from deepbet.utils import DATA_PATH as DEEPBET_DATA_PATH" in source
    assert "Path(DEEPBET_DATA_PATH).rglob('*.pt')" in source
    assert "deepbet_package.rglob('*.pt')" not in source
    assert "keras==3.15.0" in source
    assert "KERAS_BACKEND" in source
    assert "compile=False" in source
    assert "camri_rodent_unet_t2" in source
    assert "deepbet_human_t1" in source
    assert "Cross-contrast control" in source
    assert "Cross-species control" in source
    assert "run_manifest.csv" in source
    assert "t1_brain_extraction_extra_results" in source
    assert "expected when all enabled: {len(CASES) * 2}" in source
    assert "SynthStrip" not in source
