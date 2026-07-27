from __future__ import annotations

from pathlib import Path

import numpy as np

from lys_bbb.t1_registration import (
    _alignment_qc_slices,
    _edge_overlap_rgb,
    _fusion_rgb,
    create_registration_qc,
)


RSA_AFFINE = np.array(
    [
        [0.15, 0.0, 0.0, -2.0],
        [0.0, 0.0, 0.5, -3.0],
        [0.0, 0.08, 0.0, -1.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


def test_alignment_qc_selects_substantial_brain_slices() -> None:
    mask = np.zeros((8, 7, 20), dtype=bool)
    mask[2:6, 2:5, 4:16] = True
    mask[3, 3, 2] = True
    mask[3, 3, 18] = True

    selected = _alignment_qc_slices(mask, 6, None, None)

    assert selected.tolist() == [4, 6, 8, 10, 12, 15]


def test_fusion_and_edges_become_neutral_when_images_align() -> None:
    image = np.zeros((24, 20), dtype=np.float32)
    image[6:18, 5:15] = 1.0
    mask = np.ones(image.shape, dtype=bool)

    fusion = _fusion_rgb(image, image)
    edges = _edge_overlap_rgb(image, image, mask)

    assert np.array_equal(fusion[..., 0], fusion[..., 1])
    assert np.array_equal(fusion[..., 1], fusion[..., 2])
    assert np.any(np.all(edges == 1.0, axis=-1))
    assert not np.any(
        (edges[..., 0] != edges[..., 1])
        | (edges[..., 1] != edges[..., 2])
    )


def test_registration_qc_renders_before_and_after_alignment_panels(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    shape = (32, 28, 14)
    coordinates = np.indices(shape, dtype=np.float32)
    pre = np.exp(
        -(
            ((coordinates[0] - 16) / 7) ** 2
            + ((coordinates[1] - 14) / 6) ** 2
            + ((coordinates[2] - 7) / 4) ** 2
        )
    ).astype(np.float32)
    post = np.roll(pre, shift=3, axis=0)
    registered = pre * 1.1
    brain_mask = pre > 0.08
    output = tmp_path / "registration_qc.png"

    result = create_registration_qc(
        pre,
        post,
        registered,
        brain_mask,
        output,
        slice_start=None,
        slice_stop=None,
        slice_count=4,
        affine=RSA_AFFINE,
        before_xcorr=0.5,
        after_xcorr=0.95,
    )

    assert result == output
    assert output.is_file()
    assert output.stat().st_size > 10_000
