from __future__ import annotations

import csv
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
import SimpleITK as sitk
from nibabel.processing import resample_from_to

from lys_bbb.atlas_mapping import (
    AtlasCompositeRequest,
    MappingApprovalGate,
    collapse_source_labels,
    compose_point_mapping_affines,
    compute_native_t2_lesion_overlap,
    create_native_composite_labels,
    validate_major_label_array,
)
from lys_bbb.atlas_qc import (
    create_composite_all_slice_qc,
    create_t1_to_t2_all_slice_qc,
)
from lys_bbb.atlas_registration import (
    AntsExecutables,
    AtlasToT1Request,
    CommandExecution,
    run_atlas_to_t1_candidates,
)
from lys_bbb.atlas_release import (
    AtlasReleaseSpec,
    create_annotation_support_template_mask,
    inspect_nifti_geometry,
    load_major_region_scheme,
    require_same_physical_grid,
    validate_atlas_release,
)
from lys_bbb.hashing import sha256_file
from lys_bbb.t1_t2_registration import (
    T1ToT2Request,
    run_t1_to_t2_registration,
)


AFFINE = np.array(
    [
        [0.2, 0.0, 0.0, -1.0],
        [0.0, 0.25, 0.0, -1.0],
        [0.0, 0.0, 0.5, -2.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray = AFFINE) -> Path:
    image = nib.Nifti1Image(data, affine)
    image.set_qform(affine, code=1)
    image.set_sform(affine, code=1)
    nib.save(image, str(path))
    return path


def _write_lookup(path: Path, ids: tuple[int, ...] = (1, 2)) -> Path:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("label_id", "acronym", "name", "hemisphere")
        )
        writer.writeheader()
        for label_id in ids:
            writer.writerow(
                {
                    "label_id": label_id,
                    "acronym": f"FINE{label_id}",
                    "name": f"Fine source label {label_id}",
                    "hemisphere": "left" if label_id == 1 else "right",
                }
            )
    return path


def _write_scheme(path: Path, *, complete: bool = True) -> Path:
    rows = [
        {
            "source_label_id": 1,
            "major_region_id": 101,
            "major_region_acronym": "CTX",
            "major_region_name": "Cerebral cortex",
            "hemisphere": "left",
            "mapping_version": "major_regions_test_v1",
            "mapping_status": "PROPOSED",
        },
        {
            "source_label_id": 2,
            "major_region_id": 201,
            "major_region_acronym": "CTX",
            "major_region_name": "Cerebral cortex",
            "hemisphere": "right",
            "mapping_version": "major_regions_test_v1",
            "mapping_status": "PROPOSED",
        },
    ]
    if not complete:
        rows.pop()
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _atlas_fixture(tmp_path: Path) -> AtlasReleaseSpec:
    template_data = np.zeros((12, 10, 8), dtype=np.float32)
    template_data[2:10, 2:8, 1:7] = 1.0
    labels_data = np.zeros(template_data.shape, dtype=np.int16)
    labels_data[2:6, 2:8, 1:7] = 1
    labels_data[6:10, 2:8, 1:7] = 2
    template = _write_nifti(tmp_path / "template.nii.gz", template_data)
    labels = _write_nifti(tmp_path / "labels.nii.gz", labels_data)
    lookup = _write_lookup(tmp_path / "lookup.csv")
    mask, mask_sha256 = create_annotation_support_template_mask(
        labels, tmp_path / "atlas_mask.nii.gz"
    )
    return AtlasReleaseSpec(
        template_path=template,
        labels_path=labels,
        source_lookup_path=lookup,
        template_mask_path=mask,
        revision="3408ed46ea097f9fff5adbcdd7da6da6102f283a",
        template_sha256=sha256_file(template),
        labels_sha256=sha256_file(labels),
        source_lookup_sha256=sha256_file(lookup),
        template_mask_sha256=mask_sha256,
    )


class FakeAntsRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, args: tuple[str, ...], cwd: Path) -> CommandExecution:
        self.commands.append(args)
        executable = Path(args[0]).name
        if executable == "N4BiasFieldCorrection":
            source = Path(args[args.index("-i") + 1])
            output = Path(args[args.index("-o") + 1])
            image = nib.load(str(source))
            nib.save(image, str(output))
        elif executable == "antsRegistration":
            output_spec = args[args.index("--output") + 1]
            prefix_text, warped_text = output_spec.strip("[]").split(",", maxsplit=1)
            initial = args[args.index("--initial-moving-transform") + 1]
            fixed_text = initial.strip("[]").split(",", maxsplit=1)[0]
            fixed = nib.load(fixed_text)
            warped = Path(warped_text)
            nib.save(
                nib.Nifti1Image(np.ones(fixed.shape, dtype=np.float32), fixed.affine),
                str(warped),
            )
            transform = Path(f"{prefix_text}0GenericAffine.mat")
            sitk.WriteTransform(sitk.AffineTransform(3), str(transform))
        elif executable == "antsApplyTransforms":
            source = nib.load(args[args.index("--input") + 1])
            reference = nib.load(args[args.index("--reference-image") + 1])
            output = Path(args[args.index("--output") + 1])
            order = (
                0
                if args[args.index("--interpolation") + 1] == "GenericLabel"
                else 1
            )
            resampled = resample_from_to(
                source,
                (reference.shape, reference.affine),
                order=order,
                mode="constant",
                cval=0.0,
            )
            nib.save(resampled, str(output))
        else:  # pragma: no cover - protects the fake contract
            raise AssertionError(f"Unexpected fake command: {args}")
        return CommandExecution(args, 0, "fake stdout", "", 0.01)


@pytest.fixture
def fake_tools(tmp_path: Path) -> AntsExecutables:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return AntsExecutables(
        registration=bin_dir / "antsRegistration",
        apply_transforms=bin_dir / "antsApplyTransforms",
        n4_bias_field_correction=bin_dir / "N4BiasFieldCorrection",
        create_jacobian=bin_dir / "CreateJacobianDeterminantImage",
    )


def test_atlas_resource_checksums_geometry_and_lookup_are_bound(tmp_path: Path):
    spec = _atlas_fixture(tmp_path)
    validated = validate_atlas_release(spec)
    assert validated.label_ids == (1, 2)
    assert validated.template_geometry.qform_code == 1
    assert validated.template_geometry.sform_code == 1

    changed = spec.source_lookup_path.read_text().replace("FINE1", "CHANGED")
    spec.source_lookup_path.write_text(changed)
    with pytest.raises(ValueError, match="lookup checksum changed"):
        validate_atlas_release(spec)


def test_qform_sform_and_physical_grid_validation(tmp_path: Path):
    first = _write_nifti(tmp_path / "first.nii.gz", np.ones((4, 5, 6)))
    image = nib.load(str(first))
    other_affine = AFFINE.copy()
    other_affine[0, 3] += 1.0
    image.set_qform(AFFINE, code=1)
    image.set_sform(other_affine, code=1)
    mismatch = tmp_path / "mismatch.nii.gz"
    nib.save(image, str(mismatch))
    with pytest.raises(ValueError, match="qform and sform disagree"):
        inspect_nifti_geometry(mismatch)

    second = _write_nifti(
        tmp_path / "second.nii.gz", np.ones((4, 5, 6)), other_affine
    )
    with pytest.raises(ValueError, match="affines differ"):
        require_same_physical_grid(
            inspect_nifti_geometry(first),
            inspect_nifti_geometry(second),
            names=("first", "second"),
        )


def test_major_region_mapping_requires_every_source_and_never_leaks_fine_labels(
    tmp_path: Path,
):
    incomplete = _write_scheme(tmp_path / "incomplete.csv", complete=False)
    with pytest.raises(ValueError, match="incomplete"):
        load_major_region_scheme(incomplete, source_label_ids=(1, 2), approved=False)

    scheme_path = _write_scheme(tmp_path / "scheme.csv")
    scheme = load_major_region_scheme(
        scheme_path, source_label_ids=(1, 2), approved=False
    )
    labels = np.zeros((6, 6, 6), dtype=np.int16)
    labels[1:3] = 1
    labels[3:5] = 2
    source = _write_nifti(tmp_path / "source_labels.nii.gz", labels)
    collapsed = collapse_source_labels(source, scheme, tmp_path / "major.nii.gz")
    result = np.asanyarray(nib.load(str(collapsed)).dataobj)
    assert set(np.unique(result)) == {0, 101, 201}
    assert nib.load(str(collapsed)).get_data_dtype().kind in {"i", "u"}
    with pytest.raises(ValueError, match="Fine or unknown"):
        validate_major_label_array(np.array([1, 101]), scheme.allowed_major_region_ids)


def test_known_noncommuting_point_mapping_order_is_t2_to_pre_to_atlas():
    pre_to_atlas = np.eye(4)
    pre_to_atlas[0, 0] = 2.0
    t2_to_pre = np.eye(4)
    t2_to_pre[0, 3] = 3.0
    composed = compose_point_mapping_affines(pre_to_atlas, t2_to_pre)
    landmark_in_t2 = np.array([1.0, 1.0, 1.0, 1.0])
    assert np.allclose(composed @ landmark_in_t2, [8.0, 1.0, 1.0, 1.0])
    assert not np.allclose(
        composed @ landmark_in_t2,
        t2_to_pre @ (pre_to_atlas @ landmark_in_t2),
    )
    assert np.allclose(
        composed @ landmark_in_t2,
        pre_to_atlas @ (t2_to_pre @ landmark_in_t2),
    )


def test_direct_one_step_t2_labels_and_native_lesion_remain_unchanged(
    tmp_path: Path, fake_tools: AntsExecutables
):
    spec = _atlas_fixture(tmp_path)
    scheme = load_major_region_scheme(
        _write_scheme(tmp_path / "scheme.csv"), source_label_ids=(1, 2), approved=False
    )
    native_pre = _write_nifti(
        tmp_path / "pre.nii.gz", np.ones((12, 10, 8), dtype=np.float32)
    )
    native_t2 = _write_nifti(
        tmp_path / "t2.nii.gz", np.ones((12, 10, 8), dtype=np.float32)
    )
    atlas_transform = tmp_path / "atlas_to_pre.mat"
    t1_t2_transform = tmp_path / "pre_to_t2.mat"
    sitk.WriteTransform(sitk.AffineTransform(3), str(atlas_transform))
    sitk.WriteTransform(sitk.AffineTransform(3), str(t1_t2_transform))
    lesion = np.zeros((12, 10, 8), dtype=np.uint8)
    lesion[3:5, 3:5, 3:5] = 1
    lesion_path = _write_nifti(tmp_path / "lesion.nii.gz", lesion)
    before_bytes = lesion_path.read_bytes()
    before_hash = sha256_file(lesion_path)
    runner = FakeAntsRunner()

    result = create_native_composite_labels(
        AtlasCompositeRequest(
            source_atlas_labels_path=spec.labels_path,
            major_region_scheme=scheme,
            native_pre_t1_path=native_pre,
            native_t2_path=native_t2,
            atlas_to_t1_transform_path=atlas_transform,
            t1_to_t2_transform_path=t1_t2_transform,
            output_directory=tmp_path / "composite",
        ),
        runner=runner,
        executables=fake_tools,
    )

    t2_apply = json.loads(
        (result.labels_in_native_t2_path.parent / "apply_major_labels_directly_to_native_t2.json").read_text()
    )["args"]
    transform_positions = [
        index for index, value in enumerate(t2_apply) if value == "--transform"
    ]
    assert t2_apply[transform_positions[0] + 1] == str(t1_t2_transform)
    assert t2_apply[transform_positions[1] + 1] == str(atlas_transform)
    assert "major_labels_in_native_pre_t1" not in " ".join(t2_apply)
    assert lesion_path.read_bytes() == before_bytes
    assert sha256_file(lesion_path) == before_hash


def test_regional_overlap_is_approval_gated_and_reports_sensitivity(tmp_path: Path):
    scheme = load_major_region_scheme(
        _write_scheme(tmp_path / "scheme.csv"), source_label_ids=(1, 2), approved=True
    )
    shape = (12, 10, 18)
    t2 = _write_nifti(tmp_path / "t2.nii.gz", np.ones(shape, dtype=np.float32))
    labels = np.zeros(shape, dtype=np.int16)
    labels[:6] = 101
    labels[6:] = 201
    labels_path = _write_nifti(tmp_path / "labels.nii.gz", labels)
    support_path = _write_nifti(
        tmp_path / "support.nii.gz", (labels != 0).astype(np.uint8)
    )
    lesion = np.zeros(shape, dtype=np.uint8)
    lesion[5:7, 4:6, 8:10] = 1
    lesion_path = _write_nifti(tmp_path / "lesion.nii.gz", lesion)
    incomplete = MappingApprovalGate(True, True, True, True, False)
    with pytest.raises(ValueError, match="approved composite"):
        compute_native_t2_lesion_overlap(
            native_t2_path=t2,
            native_lesion_mask_path=lesion_path,
            major_labels_in_t2_path=labels_path,
            atlas_support_in_t2_path=support_path,
            scheme=scheme,
            approval_gate=incomplete,
            reviewed_orientation="RAS",
            output_directory=tmp_path / "blocked",
        )

    lesion_hash = sha256_file(lesion_path)
    result = compute_native_t2_lesion_overlap(
        native_t2_path=t2,
        native_lesion_mask_path=lesion_path,
        major_labels_in_t2_path=labels_path,
        atlas_support_in_t2_path=support_path,
        scheme=scheme,
        approval_gate=MappingApprovalGate(True, True, True, True, True),
        reviewed_orientation="RAS",
        output_directory=tmp_path / "result",
    )
    rows = list(csv.DictReader(result.result_csv_path.open()))
    assert {row["major_region_id"] for row in rows} == {"101", "201"}
    assert all("source_label" not in key for key in rows[0])
    assert result.lesion_voxel_count == 8
    assert result.mapped_lesion_voxels == 8
    assert result.lesion_sha256 == lesion_hash == sha256_file(lesion_path)
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["ap_sensitivity_perturbation_mm"] == 0.5
    assert metadata["ap_sensitivity_is_confidence_interval"] is False


def test_fake_atlas_and_t1_t2_registration_are_review_candidates(
    tmp_path: Path, fake_tools: AntsExecutables
):
    spec = _atlas_fixture(tmp_path)
    pre_data = np.zeros((20, 18, 16), dtype=np.float32)
    pre_data[4:16, 3:15, 2:14] = 5
    pre = _write_nifti(tmp_path / "pre.nii.gz", pre_data)
    pre_mask = _write_nifti(
        tmp_path / "pre_mask.nii.gz", (pre_data != 0).astype(np.uint8)
    )
    runner = FakeAntsRunner()
    atlas_output = run_atlas_to_t1_candidates(
        AtlasToT1Request(
            case_id="case-1",
            pre_t1_path=pre,
            approved_brain_mask_path=pre_mask,
            atlas_release=spec,
            output_directory=tmp_path / "atlas_job",
        ),
        runner=runner,
        executables=fake_tools,
    )
    assert [candidate.candidate for candidate in atlas_output.candidates] == [
        "rigid",
        "affine",
    ]
    assert all(candidate.transform_sha256 for candidate in atlas_output.candidates)
    assert all("--metric" in command for command in runner.commands if Path(command[0]).name == "antsRegistration")

    t2_data = np.ones((20, 18, 18), dtype=np.float32)
    t2 = _write_nifti(tmp_path / "t2.nii.gz", t2_data)
    t2_support = _write_nifti(
        tmp_path / "t2_support.nii.gz", np.ones(t2_data.shape, dtype=np.uint8)
    )
    with pytest.raises(ValueError, match="registration-support mask"):
        run_t1_to_t2_registration(
            T1ToT2Request(
                case_id="case-1",
                pre_t1_path=pre,
                approved_t1_brain_mask_path=pre_mask,
                native_t2_path=t2,
                t2_registration_support_mask_path=None,
                output_directory=tmp_path / "blocked_t1_t2",
                pre_t1_identity="subject=case-1;session=D1;input=pre",
                t2_identity="subject=case-1;session=D1;input=t2",
            ),
            runner=runner,
            executables=fake_tools,
        )
    t1_t2_output = run_t1_to_t2_registration(
        T1ToT2Request(
            case_id="case-1",
            pre_t1_path=pre,
            approved_t1_brain_mask_path=pre_mask,
            native_t2_path=t2,
            t2_registration_support_mask_path=t2_support,
            output_directory=tmp_path / "t1_t2_job",
            pre_t1_identity="subject=case-1;session=D1;input=pre",
            t2_identity="subject=case-1;session=D1;input=t2",
        ),
        runner=runner,
        executables=fake_tools,
    )
    assert t1_t2_output.affine_metrics["determinant"] == pytest.approx(1.0)
    assert t1_t2_output.transformed_t1_brain_mask_path.is_file()


def test_all_eighteen_t2_slices_are_present_in_both_qc_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    shape = (20, 16, 18)
    t2 = _write_nifti(tmp_path / "t2.nii.gz", np.ones(shape, dtype=np.float32))
    t1 = _write_nifti(tmp_path / "t1_in_t2.nii.gz", np.ones(shape, dtype=np.float32))
    brain = _write_nifti(
        tmp_path / "brain.nii.gz", np.ones(shape, dtype=np.uint8)
    )
    lesion_data = np.zeros(shape, dtype=np.uint8)
    lesion_data[8:12, 6:10, 8:11] = 1
    lesion = _write_nifti(tmp_path / "lesion.nii.gz", lesion_data)
    labels_data = np.zeros(shape, dtype=np.int16)
    labels_data[:10] = 101
    labels_data[10:] = 201
    labels = _write_nifti(tmp_path / "labels.nii.gz", labels_data)

    rigid_qc = create_t1_to_t2_all_slice_qc(
        native_t2_path=t2,
        transformed_t1_path=t1,
        transformed_t1_brain_mask_path=brain,
        t2_registration_support_mask_path=brain,
        native_lesion_mask_path=lesion,
        output_directory=tmp_path / "rigid_qc",
        transform_summary={"determinant": 1.0},
    )
    composite_qc = create_composite_all_slice_qc(
        native_t2_path=t2,
        major_labels_path=labels,
        native_lesion_mask_path=lesion,
        allowed_major_region_ids=frozenset({101, 201}),
        output_directory=tmp_path / "composite_qc",
    )
    assert len(rigid_qc.slice_paths) == 18
    assert len(composite_qc.slice_paths) == 18
    assert all(path.is_file() for path in rigid_qc.slice_paths + composite_qc.slice_paths)
    assert json.loads(rigid_qc.manifest_path.read_text())[
        "all_original_slices_rendered"
    ]
    assert json.loads(composite_qc.manifest_path.read_text())[
        "original_t2_slice_count"
    ] == 18
