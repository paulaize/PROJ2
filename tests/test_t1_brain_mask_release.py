import json
import subprocess
from pathlib import Path

from lys_bbb import t1_brain_mask_release as releases


def test_validate_t1_brain_mask_release_checks_source_and_weight(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "release"
    source = root / "Rodent-Skull-Stripping"
    for relative in (
        "RS2/inference/predict.py",
        "RS2/network/RSSNet.py",
        "RS2/jsons/dataset.json",
        "RS2/jsons/plans.json",
        "LICENSE",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(source), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    weights = root / "weights/RS2_pretrained_model.pt"
    weights.parent.mkdir()
    weights.write_bytes(b"reviewed model fixture")
    weight_hash = releases.sha256_file(weights)
    monkeypatch.setattr(releases, "RS2_SOURCE_COMMIT", commit)
    monkeypatch.setattr(releases, "RS2_WEIGHT_SHA256", weight_hash)
    (root / "release.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "fixture",
                "source_commit": commit,
                "source_path": "Rodent-Skull-Stripping",
                "weights_path": "weights/RS2_pretrained_model.pt",
                "weights_sha256": weight_hash,
                "test_time_augmentation": True,
                "human_review_required": True,
            }
        )
    )

    release = releases.validate_t1_brain_mask_release(root)

    assert release.source_commit == commit
    assert release.weights_sha256 == weight_hash
    assert release.test_time_augmentation is True
