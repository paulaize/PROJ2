"""Release tests for packaged T2 model discovery, integrity, and defaults."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from lys_bbb.t2_inference import (
    _nnunet_probability_to_native_shape,
    threshold_lesion_probability,
)
from lys_bbb.t2_model_release import validate_t2_model_release
from lys_bbb_app.platform_paths import (
    default_t2_model_release_path,
    t2_model_choices,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_RESOURCES = PROJECT_ROOT / "resources" / "models"


def test_packaged_model_discovery_has_fold1_as_the_only_default() -> None:
    choices = t2_model_choices()

    assert [choice.id for choice in choices] == [
        "lys-v3-standard3d-nnunet-fold1",
        "lys-v1-small-ratlesnetv2",
        "lys-v3-standard3d-nnunet-folds0-1",
    ]
    assert [choice.default for choice in choices] == [True, False, False]
    assert default_t2_model_release_path() == choices[0].path
    assert all(choice.path.is_dir() for choice in choices)


def test_packaged_checkpoints_and_hashes_validate_for_every_choice() -> None:
    standard, small, larger = (
        validate_t2_model_release(choice.path) for choice in t2_model_choices()
    )

    assert standard.runner == "nnunetv2"
    assert standard.folds == (1,)
    assert standard.threshold == 0.20
    assert small.runner == "ratlesnetv2"
    assert len(small.model_paths) == 5
    assert larger.runner == "nnunetv2"
    assert larger.folds == (0, 1)
    assert len(larger.model_paths) == 2


def test_threshold_0_20_is_applied_directly_to_lesion_probabilities() -> None:
    probability = np.array([0.0, 0.19999, 0.20, 0.9, 1.0], dtype=np.float32)

    mask = threshold_lesion_probability(probability, 0.20, case_id="mouse")

    np.testing.assert_array_equal(mask, [0, 0, 1, 1, 1])


def test_nnunet_nibabel_probability_axes_are_restored_to_native_order() -> None:
    nnunet_order = np.arange(5 * 4 * 3, dtype=np.float32).reshape(5, 4, 3)

    native_order = _nnunet_probability_to_native_shape(
        nnunet_order,
        (3, 4, 5),
        case_id="mouse",
    )

    assert native_order.shape == (3, 4, 5)
    assert native_order[2, 1, 4] == nnunet_order[4, 1, 2]
    with pytest.raises(ValueError, match="expected NibabelIO shape"):
        _nnunet_probability_to_native_shape(
            nnunet_order,
            (5, 4, 3),
            case_id="mouse",
        )


def test_missing_and_corrupt_resources_fail_with_clear_errors(
    tmp_path: Path,
) -> None:
    source = MODEL_RESOURCES / "lys_v3_standard3d_nnunet"
    tiny = tmp_path / "models" / "lys_v3_standard3d_nnunet"
    (tiny / "fold_1").mkdir(parents=True)
    for name in (
        "dataset.json",
        "plans.json",
        "model_metadata.json",
        "NNUNET_LICENSE.txt",
    ):
        (tiny / name).write_bytes((source / name).read_bytes())

    with pytest.raises(FileNotFoundError, match="checkpoint_best.pth"):
        validate_t2_model_release(tiny)

    (tiny / "fold_1" / "checkpoint_best.pth").write_bytes(b"corrupt")
    required_names = {
        "NNUNET_LICENSE.txt",
        "dataset.json",
        "fold_1/checkpoint_best.pth",
        "model_metadata.json",
        "plans.json",
    }
    (tiny / "SHA256SUMS").write_text(
        "\n".join(
            line
            for line in (source / "SHA256SUMS").read_text().splitlines()
            if line.split("  ", maxsplit=1)[1] in required_names
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_t2_model_release(tiny)


def test_resources_exclude_training_artifacts_and_workstation_paths() -> None:
    names = {
        path.relative_to(MODEL_RESOURCES).as_posix()
        for path in MODEL_RESOURCES.rglob("*")
        if path.is_file()
    }
    forbidden_names = (
        "checkpoint_latest.pth",
        "checkpoint_final.pth",
        "progress.png",
        "debug.json",
        ".npz",
        ".pkl",
        "training_log",
        "/validation/",
    )
    assert not any(
        forbidden in name for forbidden in forbidden_names for name in names
    )

    for path in MODEL_RESOURCES.rglob("*"):
        if path.suffix not in {".json", ".txt"} and path.name != "SHA256SUMS":
            continue
        text = path.read_text(errors="ignore").casefold()
        assert "/users/" not in text
        assert "/kaggle/" not in text
        assert "c:\\users\\" not in text


def test_metadata_records_threshold_provenance_as_pooled_not_fold1_only() -> None:
    metadata = json.loads(
        (
            MODEL_RESOURCES
            / "lys_v3_standard3d_nnunet"
            / "model_metadata.json"
        ).read_text()
    )

    assert metadata["validation"]["fold_1"]["held_out_mris"] == 40
    assert metadata["validation"]["fold_1"]["mean_dice"] == pytest.approx(
        0.8321459286453153
    )
    provenance = metadata["threshold_provenance"]
    assert provenance["unique_held_out_mris"] == 81
    assert "not fold-1-only" in provenance["calibrated_from"]
    assert provenance["threshold_0_20"]["mean_oof_dice"] == pytest.approx(
        0.8106762523671631
    )
