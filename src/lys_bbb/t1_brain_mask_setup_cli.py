"""Install the reviewed RS2 source and weights as a local T1 model release."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from lys_bbb.t1_brain_mask_release import (
    RS2_REPOSITORY_URL,
    RS2_SOURCE_COMMIT,
    RS2_WEIGHTS_FOLDER_URL,
    RS2_WEIGHT_SHA256,
    release_manifest_payload,
    sha256_file,
    validate_t1_brain_mask_release,
)


def install_local_t1_brain_mask_release(
    destination: Path,
    *,
    source_checkout: Path | None = None,
    weights_file: Path | None = None,
) -> Path:
    """Create a self-contained, checksummed local release without overwriting one."""

    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"T1 brain-mask release already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix=f".{destination.name}-install-"
    ) as temporary:
        release_root = Path(temporary) / destination.name
        release_root.mkdir()
        source_target = release_root / "Rodent-Skull-Stripping"
        if source_checkout is None:
            _run(
                [
                    "git",
                    "clone",
                    "--no-checkout",
                    RS2_REPOSITORY_URL,
                    str(source_target),
                ]
            )
            _run(
                [
                    "git",
                    "-C",
                    str(source_target),
                    "checkout",
                    "--detach",
                    RS2_SOURCE_COMMIT,
                ]
            )
        else:
            source_checkout = source_checkout.expanduser().resolve()
            _require_source_commit(source_checkout)
            shutil.copytree(source_checkout, source_target)

        weights_directory = release_root / "weights"
        weights_directory.mkdir()
        target_weights = weights_directory / "RS2_pretrained_model.pt"
        if weights_file is None:
            downloaded = _download_official_weights(weights_directory)
            if downloaded.resolve() != target_weights.resolve():
                shutil.copy2(downloaded, target_weights)
                downloaded.unlink()
        else:
            weights_file = weights_file.expanduser().resolve()
            if not weights_file.is_file():
                raise FileNotFoundError(f"RS2 weight file is unavailable: {weights_file}")
            shutil.copy2(weights_file, target_weights)
        actual_hash = sha256_file(target_weights)
        if actual_hash != RS2_WEIGHT_SHA256:
            raise ValueError(
                "Downloaded RS2 weight checksum does not match the reviewed Colab run: "
                f"{actual_hash}."
            )

        payload = release_manifest_payload(
            weights_path=target_weights,
            release_root=release_root,
        )
        payload["installed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (release_root / "release.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        validate_t1_brain_mask_release(release_root)
        release_root.replace(destination)
    validate_t1_brain_mask_release(destination)
    return destination


def _download_official_weights(destination: Path) -> Path:
    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError(
            "The gdown package is required to install official RS2 weights. Install "
            "the project's t1-inference extra first."
        ) from exc
    gdown.download_folder(
        url=RS2_WEIGHTS_FOLDER_URL,
        output=str(destination),
        quiet=False,
        remaining_ok=True,
    )
    candidates = sorted(destination.rglob("*pretrained_model.pt"))
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one RS2 pretrained model in the official download, "
            f"found {len(candidates)}."
        )
    return candidates[0]


def _require_source_commit(source_checkout: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(source_checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = completed.stdout.strip()
    if actual != RS2_SOURCE_COMMIT:
        raise ValueError(
            f"RS2 source checkout is at {actual}, expected {RS2_SOURCE_COMMIT}."
        )


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--source-checkout",
        type=Path,
        help="Optional existing pinned checkout; otherwise clone the official repository.",
    )
    parser.add_argument(
        "--weights",
        type=Path,
        help="Optional downloaded official weight; otherwise download it with gdown.",
    )
    args = parser.parse_args(argv)
    installed = install_local_t1_brain_mask_release(
        args.destination,
        source_checkout=args.source_checkout,
        weights_file=args.weights,
    )
    print(
        json.dumps(
            {
                "release": str(installed),
                "source_commit": RS2_SOURCE_COMMIT,
                "weights_sha256": RS2_WEIGHT_SHA256,
                "human_review_required": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
