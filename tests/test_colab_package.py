from pathlib import Path

import pytest

from scripts.brain_extraction.prepare_colab_package import (
    build_package,
    discover_cases,
    read_case_file,
    select_cases,
)


def touch(path: Path, content: bytes = b"test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_discover_and_select_cases(tmp_path: Path) -> None:
    for case_id in ("C1S1_D1", "C1S1_D7", "C2S1_D1"):
        touch(tmp_path / case_id / "pre_coronal.nii.gz")
    touch(tmp_path / "not_a_case" / "post_coronal.nii.gz")

    available = discover_cases(tmp_path)
    assert available == ["C1S1_D1", "C1S1_D7", "C2S1_D1"]
    assert select_cases(available, ["C1S1_D7"], None, 7) == ["C1S1_D7"]
    assert len(select_cases(available, [], 2, 7)) == 2

    with pytest.raises(ValueError, match="unknown or unconverted"):
        select_cases(available, ["missing"], None, 7)


def test_read_case_file_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "cases.txt"
    path.write_text("# benchmark\nC1S1_D1\n\n  C2S1_D7  \n")
    assert read_case_file(path) == ["C1S1_D1", "C2S1_D7"]


def test_build_package_copies_images_and_reviewed_reference(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    references = tmp_path / "references"
    package = tmp_path / "package"
    touch(input_root / "C1S1_D1" / "pre_coronal.nii.gz", b"image")
    touch(references / "C1S1_D1_pre_manual_mask_done.nii.gz", b"mask")

    rows = build_package(
        input_root=input_root,
        package_root=package,
        cases=["C1S1_D1"],
        reference_dir=references,
        require_reference=True,
        seed=17,
    )

    assert rows == [
        {
            "case_id": "C1S1_D1",
            "image": "images/C1S1_D1_pre_t1.nii.gz",
            "reference_mask": "references/C1S1_D1_brain_mask.nii.gz",
        }
    ]
    assert (package / "benchmark_manifest.csv").is_file()
    assert (package / rows[0]["image"]).read_bytes() == b"image"
    assert (package / rows[0]["reference_mask"]).read_bytes() == b"mask"
    assert '"cases": [' in (package / "package_metadata.json").read_text()
