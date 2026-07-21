import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from lys_bbb.t1_brain_mask import (
    _patch_rs2_mps_tta,
    _patch_rs2_runtime,
    build_t1_brain_mask_draft,
    native_to_rsa,
    rsa_to_native,
)


def _write_synthetic_pair(root: Path) -> tuple[Path, Path]:
    shape = (72, 96, 21)
    xx, yy = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    image = np.zeros(shape, dtype=np.float32)
    raw = np.zeros(shape, dtype=np.uint8)
    for slice_index in range(shape[2]):
        brain = ((xx - 36) / 24) ** 2 + ((yy - 43) / 29) ** 2 <= 1
        seam = 68 - (np.abs(xx - 36) / 8).astype(int)
        cap = (np.abs(xx - 36) <= 20) & (yy > seam) & (yy <= 82)
        combined = brain | cap
        image[:, :, slice_index][brain] = 0.62
        image[:, :, slice_index][cap] = 0.88
        image[:, :, slice_index][combined & (np.abs(yy - seam) <= 1)] = 0.03
        raw[:, :, slice_index] = combined
    affine = np.diag([0.15, 0.08, 0.10, 1.0])
    input_path = root / "mouse_pre_t1.nii.gz"
    raw_path = root / "mouse_raw_rs2.nii.gz"
    nib.save(nib.Nifti1Image(image, affine), input_path)
    nib.save(nib.Nifti1Image(raw, affine), raw_path)
    return input_path, raw_path


def test_orientation_conversion_round_trips_without_interpolation() -> None:
    native = np.arange(3 * 4 * 5).reshape((3, 4, 5))
    affine = np.diag([-0.2, 0.3, -0.4, 1.0])

    rsa, record = native_to_rsa(native, affine)
    restored = rsa_to_native(rsa, record)

    assert record.native_axis_codes == ("L", "A", "I")
    assert np.array_equal(restored, native)


def test_build_t1_brain_mask_draft_writes_native_grid_and_provenance(
    tmp_path: Path,
) -> None:
    input_path, raw_path = _write_synthetic_pair(tmp_path)
    output_root = tmp_path / "result"

    output = build_t1_brain_mask_draft(
        input_path,
        raw_path,
        output_root,
        case_id="Mouse-001",
    )

    reference = nib.load(str(input_path))
    raw = np.asanyarray(nib.load(str(output.raw_rs2_mask)).dataobj) > 0
    draft_image = nib.load(str(output.draft_mask))
    draft = np.asanyarray(draft_image.dataobj) > 0
    metadata = json.loads(output.metadata_path.read_text())
    assert draft_image.shape == reference.shape
    assert np.allclose(draft_image.affine, reference.affine)
    assert not np.any(draft & ~raw)
    assert np.count_nonzero(draft) < np.count_nonzero(raw)
    assert output.qc_preview.is_file()
    assert metadata["human_review_required"] is True
    assert metadata["approved"] is False
    assert metadata["draft_mask_sha256"] == output.draft_mask_sha256
    assert metadata["m_seam_cleanup"]["subset_of_raw_rs2"] is True


def test_build_t1_brain_mask_draft_refuses_to_overwrite(tmp_path: Path) -> None:
    input_path, raw_path = _write_synthetic_pair(tmp_path)
    output_root = tmp_path / "existing"
    output_root.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        build_t1_brain_mask_draft(input_path, raw_path, output_root)


def test_rs2_runtime_patch_is_narrow_and_repeatable(tmp_path: Path) -> None:
    source_path = tmp_path / "predict.py"
    source_path.write_text(
        "checkpoint = torch.load(checkpoint_name, map_location=torch.device('cpu'))\n"
        "    parameters = checkpoint['state_dict']\n"
        "\n    network = torch.compile(network)\n"
    )

    _patch_rs2_runtime(source_path)
    _patch_rs2_runtime(source_path)

    patched = source_path.read_text()
    assert "weights_only=False" in patched
    assert "key.removeprefix('_orig_mod.')" in patched
    assert "torch.compile disabled" in patched
    assert "network = torch.compile(network)" not in patched


def test_rs2_mps_tta_patch_keeps_all_eight_mirrors(tmp_path: Path) -> None:
    source_path = tmp_path / "sliding_window_prediction.py"
    source_path.write_text(
        "def maybe_mirror_and_predict(network, x, mirror_axes=None):\n"
        "    return network(x)\n"
        "\n"
        "def predict_sliding_window_return_logits():\n"
        "    pass\n"
    )

    _patch_rs2_mps_tta(source_path)

    patched = source_path.read_text()
    assert "accumulation_device = torch.device('cpu')" in patched
    assert "num_predictions = 2 ** len(mirror_axes)" in patched
    assert "forward((2, 3, 4))" in patched
    assert "torch.mps.synchronize()" in patched
    assert "empty_cache(x.device)" in patched
