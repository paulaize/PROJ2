"""Tests for the restricted native ANTsPyx registration backend."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import nibabel as nib
import numpy as np
import pytest
import SimpleITK as sitk

from lys_bbb.antspyx_backend import (
    ANTSPYX_ENGINE,
    ANTSPYX_VERSION,
    antspyx_command_runner,
    antspyx_executables,
    antspyx_subprocess_command_runner,
)
from lys_bbb.atlas_registration import AtlasToT1Config
from lys_bbb.t1_t2_registration import (
    T1ToT2Config,
    T1ToT2Request,
    run_t1_to_t2_registration,
)


def test_antspyx_runner_only_dispatches_allow_listed_compiled_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []
    fake_ants = ModuleType("ants")
    fake_ants.__path__ = []  # type: ignore[attr-defined]
    fake_ants.__version__ = ANTSPYX_VERSION
    fake_internal = ModuleType("ants.internal")

    def get_lib_fn(name: str):
        def execute(arguments: list[str]) -> int:
            calls.append((name, arguments))
            return 0

        return execute

    fake_internal.get_lib_fn = get_lib_fn  # type: ignore[attr-defined]
    fake_internal.process_arguments = list  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ants", fake_ants)
    monkeypatch.setitem(sys.modules, "ants.internal", fake_internal)

    execution = antspyx_command_runner(
        ("antspyx-compiled/antsApplyTransforms", "--dimensionality", "3"),
        tmp_path,
    )
    assert execution.return_code == 0
    assert calls == [("antsApplyTransforms", ["--dimensionality", "3"])]
    assert ANTSPYX_VERSION in execution.stdout

    rejected = antspyx_command_runner(
        ("antspyx-compiled/unknownOperation", "--unsafe", "value"),
        tmp_path,
    )
    assert rejected.return_code == 1
    assert "not allow-listed" in rejected.stderr
    assert len(calls) == 1


def test_antspyx_has_a_distinct_hashed_method_identity() -> None:
    cli_atlas = AtlasToT1Config()
    antspyx_atlas = AtlasToT1Config(
        runtime_engine=ANTSPYX_ENGINE,
        runtime_version=ANTSPYX_VERSION,
    )
    cli_t1_t2 = T1ToT2Config()
    antspyx_t1_t2 = T1ToT2Config(
        runtime_engine=ANTSPYX_ENGINE,
        runtime_version=ANTSPYX_VERSION,
    )

    assert antspyx_atlas.method_spec()["engine"] == ANTSPYX_ENGINE
    assert "antspyx_0_6_3" in antspyx_atlas.method_version
    assert antspyx_atlas.method_spec_sha256 != cli_atlas.method_spec_sha256
    assert antspyx_t1_t2.method_spec_sha256 != cli_t1_t2.method_spec_sha256


@pytest.mark.skipif(
    importlib.util.find_spec("ants") is None,
    reason="The optional pinned ANTsPyx package is not installed",
)
def test_real_antspyx_compiled_t1_to_t2_registration_bridge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl-cache"))
    shape = (18, 16, 14)
    coordinates = np.indices(shape, dtype=np.float32)
    centre = np.asarray([8.0, 7.0, 6.0], dtype=np.float32)[:, None, None, None]
    squared_distance = np.square(coordinates - centre).sum(axis=0)
    image_data = np.exp(-squared_distance / 18.0).astype(np.float32)
    image_data[4:8, 9:12, 3:6] += 0.6
    mask_data = (image_data > 0.08).astype(np.uint8)
    affine = np.diag([0.2, 0.2, 0.4, 1.0])

    pre_t1 = _write_nifti(tmp_path / "pre_t1.nii.gz", image_data, affine)
    t1_mask = _write_nifti(tmp_path / "t1_mask.nii.gz", mask_data, affine)
    native_t2 = _write_nifti(tmp_path / "native_t2.nii.gz", image_data, affine)
    t2_support = _write_nifti(tmp_path / "t2_support.nii.gz", mask_data, affine)
    tools = antspyx_executables()
    n4_output = tmp_path / "pre_t1_n4.nii.gz"
    n4_execution = antspyx_command_runner(
        (
            str(tools.n4_bias_field_correction),
            "-d",
            "3",
            "-i",
            str(pre_t1),
            "-x",
            str(t1_mask),
            "-s",
            "2",
            "-c",
            "[2x2x1,1e-7]",
            "-o",
            str(n4_output),
            "-v",
            "0",
        ),
        tmp_path,
    )
    assert n4_execution.return_code == 0
    assert n4_output.is_file()

    config = T1ToT2Config(
        iterations=(4, 2),
        runtime_engine=tools.engine,
        runtime_version=tools.version,
    )

    output = run_t1_to_t2_registration(
        T1ToT2Request(
            case_id="synthetic-identical",
            pre_t1_path=pre_t1,
            approved_t1_brain_mask_path=t1_mask,
            native_t2_path=native_t2,
            t2_registration_support_mask_path=t2_support,
            output_directory=tmp_path / "registration",
            pre_t1_identity="subject=synthetic;session=test;input=pre",
            t2_identity="subject=synthetic;session=test;input=t2",
            config=config,
        ),
        runner=antspyx_subprocess_command_runner,
        executables=tools,
    )

    assert output.transform_path.is_file()
    assert output.transformed_t1_path.is_file()
    assert output.transformed_t1_brain_mask_path.is_file()
    assert output.method_version == config.method_version
    assert nib.load(str(output.transformed_t1_path)).shape == shape
    command = json.loads(output.command_record_path.read_text())
    assert command["engine"] == ANTSPYX_ENGINE
    assert command["engine_version"] == ANTSPYX_VERSION
    assert command["return_code"] == 0
    native_logs = (
        Path(command["stdout_path"]).read_text()
        + Path(command["stderr_path"]).read_text()
    )
    assert native_logs.strip()


@pytest.mark.skipif(
    importlib.util.find_spec("ants") is None,
    reason="The optional pinned ANTsPyx package is not installed",
)
def test_real_antspyx_direct_transform_order_matches_sequential_resampling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl-cache"))
    shape = (28, 28, 28)
    affine = np.eye(4)
    labels = np.zeros(shape, dtype=np.uint8)
    labels[4:7, 11:14, 13:16] = 1
    source = _write_nifti(tmp_path / "source.nii.gz", labels, affine)
    reference = _write_nifti(
        tmp_path / "reference.nii.gz",
        np.zeros(shape, dtype=np.uint8),
        affine,
    )

    atlas_to_pre = tmp_path / "atlas_to_pre.mat"
    scaling = sitk.AffineTransform(3)
    scaling.SetMatrix((0.5, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
    sitk.WriteTransform(scaling, str(atlas_to_pre))
    pre_to_t2 = tmp_path / "pre_to_t2.mat"
    translation = sitk.TranslationTransform(3, (3.0, 0.0, 0.0))
    sitk.WriteTransform(translation, str(pre_to_t2))

    tools = antspyx_executables()
    sequential_pre = tmp_path / "sequential_pre.nii.gz"
    sequential_t2 = tmp_path / "sequential_t2.nii.gz"
    direct_t2 = tmp_path / "direct_t2.nii.gz"
    reverse_t2 = tmp_path / "reverse_t2.nii.gz"
    _run_label_apply(
        tools.apply_transforms,
        source,
        reference,
        sequential_pre,
        (atlas_to_pre,),
        tmp_path,
    )
    _run_label_apply(
        tools.apply_transforms,
        sequential_pre,
        reference,
        sequential_t2,
        (pre_to_t2,),
        tmp_path,
    )
    _run_label_apply(
        tools.apply_transforms,
        source,
        reference,
        direct_t2,
        (pre_to_t2, atlas_to_pre),
        tmp_path,
    )
    _run_label_apply(
        tools.apply_transforms,
        source,
        reference,
        reverse_t2,
        (atlas_to_pre, pre_to_t2),
        tmp_path,
    )

    sequential = np.asanyarray(nib.load(str(sequential_t2)).dataobj)
    direct = np.asanyarray(nib.load(str(direct_t2)).dataobj)
    reverse = np.asanyarray(nib.load(str(reverse_t2)).dataobj)
    assert np.array_equal(direct, sequential)
    assert not np.array_equal(reverse, sequential)


def _run_label_apply(
    executable: Path,
    source: Path,
    reference: Path,
    output: Path,
    transforms: tuple[Path, ...],
    cwd: Path,
) -> None:
    args = [
        str(executable),
        "--dimensionality",
        "3",
        "--input",
        str(source),
        "--reference-image",
        str(reference),
        "--output",
        str(output),
        "--interpolation",
        "GenericLabel",
        "--output-data-type",
        "uchar",
        "--default-value",
        "0",
    ]
    for transform in transforms:
        args.extend(("--transform", str(transform)))
    args.extend(("--float", "1", "--verbose", "0"))
    execution = antspyx_command_runner(tuple(args), cwd)
    assert execution.return_code == 0, execution.stderr
    assert output.is_file()


def _write_nifti(path: Path, data: np.ndarray, affine: np.ndarray) -> Path:
    image = nib.Nifti1Image(data, affine)
    image.set_qform(affine, code=1)
    image.set_sform(affine, code=1)
    nib.save(image, str(path))
    return path
