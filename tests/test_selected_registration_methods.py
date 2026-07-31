from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
import SimpleITK as sitk

from lys_bbb.registration_runtime import (
    ANTSPYX_ENGINE,
    ANTSPYX_VERSION,
    AntsExecutables,
    CommandExecution,
)
from lys_bbb.t1_registration import (
    T1_REGISTRATION_METHOD_VERSION,
    T1RegistrationRequest,
    run_t1_registration,
)
from lys_bbb.t1_t2_registration import (
    T1_TO_T2_ANTSPYX_METHOD_VERSION,
    T1ToT2Request,
    run_t1_to_t2_registration,
)


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray) -> Path:
    image = nib.Nifti1Image(data, affine)
    image.set_qform(affine, code=1)
    image.set_sform(affine, code=1)
    nib.save(image, str(path))
    return path


@pytest.fixture
def tools() -> AntsExecutables:
    root = Path("antspyx-compiled")
    return AntsExecutables(
        registration=root / "antsRegistration",
        apply_transforms=root / "antsApplyTransforms",
        n4_bias_field_correction=root / "N4BiasFieldCorrection",
        create_jacobian=root / "CreateJacobianDeterminantImage",
        engine=ANTSPYX_ENGINE,
        version=ANTSPYX_VERSION,
    )


class SyntheticAntsRunner:
    def __init__(self, *, mutate: Path | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.mutate = mutate

    def __call__(self, args: tuple[str, ...], cwd: Path) -> CommandExecution:
        self.commands.append(args)
        operation = Path(args[0]).name
        if operation == "antsRegistration":
            initial = args[args.index("--initial-moving-transform") + 1]
            fixed_path = Path(initial.strip("[]").split(",", maxsplit=1)[0])
            fixed = nib.load(str(fixed_path))
            output = args[args.index("--output") + 1]
            prefix_text, warped_text = output.strip("[]").split(",", maxsplit=1)
            warped = Path(warped_text)
            warped.parent.mkdir(parents=True, exist_ok=True)
            nib.save(
                nib.Nifti1Image(
                    fixed.get_fdata(dtype=np.float32),
                    fixed.affine,
                    fixed.header,
                ),
                str(warped),
            )
            sitk.WriteTransform(
                sitk.Euler3DTransform(),
                f"{prefix_text}0GenericAffine.mat",
            )
        elif operation == "antsApplyTransforms":
            reference = nib.load(str(args[args.index("--reference-image") + 1]))
            output = Path(args[args.index("--output") + 1])
            nib.save(
                nib.Nifti1Image(
                    np.ones(reference.shape, dtype=np.uint8),
                    reference.affine,
                    reference.header,
                ),
                str(output),
            )
        if self.mutate is not None:
            image = nib.load(str(self.mutate))
            changed = image.get_fdata(dtype=np.float32)
            changed.flat[0] += 1
            _write_nifti(self.mutate, changed, image.affine)
            self.mutate = None
        return CommandExecution(args, 0, "synthetic\n", "", 0.01)


def _inputs(tmp_path: Path) -> dict[str, Path]:
    affine = np.array(
        [
            [0.15, 0.0, 0.0, -1.0],
            [0.0, 0.08, 0.0, -2.0],
            [0.0, 0.0, 0.5, -3.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    t1_shape = (12, 14, 8)
    t2_shape = (10, 13, 6)
    t1 = np.arange(np.prod(t1_shape), dtype=np.float32).reshape(t1_shape)
    t2_affine = affine.copy()
    t2_affine[0, 0] = 0.07
    t2_affine[1, 1] = 0.07
    return {
        "pre": _write_nifti(tmp_path / "pre.nii.gz", t1, affine),
        "post": _write_nifti(tmp_path / "post.nii.gz", t1 + 2, affine),
        "mask": _write_nifti(
            tmp_path / "mask.nii.gz", np.ones(t1_shape, dtype=np.uint8), affine
        ),
        "t2": _write_nifti(
            tmp_path / "t2.nii.gz", np.ones(t2_shape, dtype=np.float32), t2_affine
        ),
    }


def test_selected_prepost_direction_grid_provenance_and_overwrite_refusal(
    tmp_path: Path,
    tools: AntsExecutables,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    paths = _inputs(tmp_path)
    runner = SyntheticAntsRunner()
    output_dir = tmp_path / "prepost"
    request = T1RegistrationRequest(
        case_id="case",
        pre_t1_path=paths["pre"],
        post_t1_path=paths["post"],
        brain_mask_path=paths["mask"],
        registered_post_path=output_dir / "post_in_pre.nii.gz",
        transform_path=output_dir / "post_to_pre_ants_0GenericAffine.mat",
        qc_preview_path=output_dir / "qc.png",
        pre_t1_identity="study_subject_id=case",
        post_t1_identity="study_subject_id=case",
        qc_slice_count=2,
    )
    result = run_t1_registration(request, runner=runner, executables=tools)

    command = runner.commands[0]
    initial = command[command.index("--initial-moving-transform") + 1]
    assert initial == f"[{paths['pre']},{paths['post']},0]"
    assert "--masks" not in command
    assert result.method_version == T1_REGISTRATION_METHOD_VERSION
    assert nib.load(str(result.registered_post_path)).shape == nib.load(
        str(paths["pre"])
    ).shape
    assert np.allclose(
        nib.load(str(result.registered_post_path)).affine,
        nib.load(str(paths["pre"])).affine,
    )
    assert result.metadata["scientific_status"] == "DRAFT_REVIEW_REQUIRED"
    assert result.metadata["inputs_sha256"]
    assert result.metadata["outputs_sha256"]
    registration_record = json.loads(
        (output_dir / "registration_command.json").read_text()
    )
    assert registration_record["runtime_seconds"] == pytest.approx(0.01)

    with pytest.raises(FileExistsError, match="overwrite"):
        run_t1_registration(request, runner=runner, executables=tools)


def test_selected_registration_identity_grid_and_changed_hash_gates(
    tmp_path: Path,
    tools: AntsExecutables,
) -> None:
    paths = _inputs(tmp_path)
    with pytest.raises(ValueError, match="identities differ"):
        run_t1_to_t2_registration(
            T1ToT2Request(
                case_id="case",
                pre_t1_path=paths["pre"],
                approved_t1_brain_mask_path=paths["mask"],
                native_t2_path=paths["t2"],
                t2_registration_support_mask_path=None,
                output_directory=tmp_path / "identity-blocked",
                pre_t1_identity="study_subject_id=case-a",
                t2_identity="study_subject_id=case-b",
            ),
            runner=SyntheticAntsRunner(),
            executables=tools,
        )
    assert not (tmp_path / "identity-blocked").exists()

    wrong_affine = nib.load(str(paths["pre"])).affine.copy()
    wrong_affine[0, 3] += 2
    wrong_mask = _write_nifti(
        tmp_path / "wrong_mask.nii.gz",
        np.ones(nib.load(str(paths["pre"])).shape, dtype=np.uint8),
        wrong_affine,
    )
    with pytest.raises(ValueError, match="affines differ"):
        run_t1_to_t2_registration(
            T1ToT2Request(
                case_id="case",
                pre_t1_path=paths["pre"],
                approved_t1_brain_mask_path=wrong_mask,
                native_t2_path=paths["t2"],
                t2_registration_support_mask_path=None,
                output_directory=tmp_path / "grid-blocked",
                pre_t1_identity="study_subject_id=case",
                t2_identity="study_subject_id=case",
            ),
            runner=SyntheticAntsRunner(),
            executables=tools,
        )

    with pytest.raises(ValueError, match="changed during"):
        run_t1_to_t2_registration(
            T1ToT2Request(
                case_id="case",
                pre_t1_path=paths["pre"],
                approved_t1_brain_mask_path=paths["mask"],
                native_t2_path=paths["t2"],
                t2_registration_support_mask_path=None,
                output_directory=tmp_path / "changed",
                pre_t1_identity="study_subject_id=case",
                t2_identity="study_subject_id=case",
            ),
            runner=SyntheticAntsRunner(mutate=paths["pre"]),
            executables=tools,
        )


def test_selected_t1_to_t2_direction_and_native_output_grid(
    tmp_path: Path,
    tools: AntsExecutables,
) -> None:
    paths = _inputs(tmp_path)
    runner = SyntheticAntsRunner()
    result = run_t1_to_t2_registration(
        T1ToT2Request(
            case_id="case",
            pre_t1_path=paths["pre"],
            approved_t1_brain_mask_path=paths["mask"],
            native_t2_path=paths["t2"],
            t2_registration_support_mask_path=None,
            output_directory=tmp_path / "t1-t2",
            pre_t1_identity="study_subject_id=case",
            t2_identity="study_subject_id=case",
        ),
        runner=runner,
        executables=tools,
    )

    registration = runner.commands[0]
    initial = registration[registration.index("--initial-moving-transform") + 1]
    assert initial == f"[{paths['t2']},{paths['pre']},0]"
    assert "--masks" not in registration
    assert result.method_version == T1_TO_T2_ANTSPYX_METHOD_VERSION
    for output in (
        result.transformed_t1_path,
        result.transformed_t1_brain_mask_path,
    ):
        assert nib.load(str(output)).shape == nib.load(str(paths["t2"])).shape
        assert np.allclose(
            nib.load(str(output)).affine,
            nib.load(str(paths["t2"])).affine,
        )
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["method_spec"]["scientific_status"] == "DRAFT_REVIEW_REQUIRED"
    assert metadata["registration_metric_masks_used"] is False
    assert metadata["native_t2_resampled"] is False

    with pytest.raises(FileExistsError, match="overwrite"):
        run_t1_to_t2_registration(
            T1ToT2Request(
                case_id="case",
                pre_t1_path=paths["pre"],
                approved_t1_brain_mask_path=paths["mask"],
                native_t2_path=paths["t2"],
                t2_registration_support_mask_path=None,
                output_directory=tmp_path / "t1-t2",
                pre_t1_identity="study_subject_id=case",
                t2_identity="study_subject_id=case",
            ),
            runner=runner,
            executables=tools,
        )
