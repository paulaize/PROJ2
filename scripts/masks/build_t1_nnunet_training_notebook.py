#!/usr/bin/env python3
"""Build the deployment-oriented pre-Gd T1 brain-mask nnU-Net Kaggle notebook."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "notebooks/t1_brain_mask_standard3d_nnunet_kaggle.ipynb"


def markdown(cell_id: str, source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": cell_id,
        "metadata": {},
        "source": dedent(source).strip().splitlines(keepends=True),
    }


def code(cell_id: str, source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id,
        "metadata": {},
        "outputs": [],
        "source": dedent(source).strip().splitlines(keepends=True),
    }


NOTEBOOK = {
    "cells": [
        markdown(
            "overview",
            """
            # LYS pre-Gd T1 brain masking — compact standard 3-D nnU-Net

            This notebook trains an official standard `PlainConvUNet` for mouse
            pre-Gd T1-weighted brain masking. It is deployment-oriented: five
            animal-disjoint folds provide out-of-fold evidence, but the released
            model is one final model trained on all approved labels.

            Current local audit (2026-07-27): 34 scans from 17 animals, all
            96×185×256 at approximately 0.15×0.07784×0.078125 mm. The editable
            masks are not yet a fully approved training set. Do not upload the
            untouched RS2/M-seam prelabels as labels.

            Attach one approved training package containing `training_manifest.csv`
            plus its relative image and mask paths. Enable a Kaggle GPU and Internet.
            A T4×2 session is supported.

            The five-epoch output is only a software, size, and hardware benchmark.
            Predictions remain draft masks requiring native-grid human review.
            """,
        ),
        markdown(
            "configuration-heading",
            """
            ## 1 — Configuration

            Run the five-epoch benchmark first. Run the five 250-epoch folds across
            resumable sessions next. Train `fold_all` only after the pooled OOF
            report has been reviewed.
            """,
        ),
        code(
            "configuration",
            """
            import hashlib
            import importlib.metadata
            import inspect
            import json
            import os
            import shutil
            import subprocess
            import sys
            import tarfile
            import time
            import zipfile
            from pathlib import Path

            import nibabel as nib
            import numpy as np
            import pandas as pd
            import torch
            from IPython.display import FileLink, Image, display

            RUN_SEED = 20260727
            NNUNET_COMMIT = "468cf803df9b267150ae2b6c0c59b8ac84f16227"  # v2.8.1
            DATASET_ID = 502
            DATASET_NAME = "Dataset502_LYST1BrainMaskV1"
            PLANNER = "ExperimentPlanner"
            PLANS = "nnUNetPlans"
            CONFIGURATION = "3d_fullres"
            BENCHMARK_TRAINER = "nnUNetTrainer_5epochs_SaveEveryEpoch"
            CV_TRAINER = "nnUNetTrainer_250epochs_SaveEveryEpoch"

            RUN_BENCHMARK_5E = True
            RUN_CV_250 = False
            RUN_FINAL_ALL_250 = False
            FOLDS_TO_RUN = [0, 1, 2, 3, 4]
            NUM_GPUS = 2
            BUILD_RESUME_ARCHIVE = True

            # Set only if automatic discovery finds the wrong item.
            TRAINING_PACKAGE_OVERRIDE = None  # package root, manifest, or .zip
            RESUME_ARCHIVE_OVERRIDE = None    # ...standard3d_resume.tar.gz

            # Change these only after an explicit, documented inclusion correction.
            EXPECTED_APPROVED_CASES = 34
            EXPECTED_ANIMAL_GROUPS = 17
            SURFACE_TOLERANCE_MM = 0.15
            DEPLOY_DISABLE_TTA = True

            assert set(FOLDS_TO_RUN) <= set(range(5))
            assert len(FOLDS_TO_RUN) == len(set(FOLDS_TO_RUN))
            assert NUM_GPUS in (1, 2)

            WORK = Path("/kaggle/working")
            EXPERIMENT_ROOT = WORK / "LYS_T1_brainmask_standard3d"
            PROVENANCE = EXPERIMENT_ROOT / "provenance"
            RUNS = EXPERIMENT_ROOT / "runs"
            NNUNET_RAW = WORK / "nnUNet_raw"
            NNUNET_PREPROCESSED = WORK / "nnUNet_preprocessed"
            NNUNET_RESULTS = WORK / "nnUNet_results"
            for key, value in {
                "nnUNet_raw": NNUNET_RAW,
                "nnUNet_preprocessed": NNUNET_PREPROCESSED,
                "nnUNet_results": NNUNET_RESULTS,
            }.items():
                os.environ[key] = str(value)

            def sha256(path: Path) -> str:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                return digest.hexdigest()

            display({
                "benchmark_5e": RUN_BENCHMARK_5E,
                "cv_250": RUN_CV_250,
                "final_all_250": RUN_FINAL_ALL_250,
                "folds": FOLDS_TO_RUN,
                "num_gpus": NUM_GPUS,
                "deploy_disable_tta": DEPLOY_DISABLE_TTA,
            })
            """,
        ),
        markdown(
            "install-heading",
            """
            ## 2 — Install pinned nnU-Net and inspect its interfaces

            The notebook records the live PyTorch/CUDA environment and refuses an
            unsupported GPU architecture (the failure mode seen with newer PyTorch
            builds on a P100).
            """,
        ),
        code(
            "install",
            """
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-q",
                    f"git+https://github.com/MIC-DKFZ/nnUNet.git@{NNUNET_COMMIT}",
                    "nibabel",
                    "pandas",
                    "scipy",
                    "surface-distance",
                    "matplotlib",
                ],
                check=True,
            )
            assert importlib.metadata.version("nnunetv2") == "2.8.1"
            assert torch.cuda.is_available(), "Enable a Kaggle GPU"
            assert torch.cuda.device_count() >= NUM_GPUS, (
                torch.cuda.device_count(), NUM_GPUS
            )
            supported_arches = set(torch.cuda.get_arch_list())
            gpu_records = []
            for index in range(NUM_GPUS):
                major, minor = torch.cuda.get_device_capability(index)
                architecture = f"sm_{major}{minor}"
                assert architecture in supported_arches, (
                    f"{torch.cuda.get_device_name(index)} uses {architecture}, "
                    f"but this PyTorch build supports {sorted(supported_arches)}"
                )
                gpu_records.append({
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "capability": f"{major}.{minor}",
                })

            subprocess.run(["nvidia-smi"], check=True)
            for command in (
                "nnUNetv2_plan_and_preprocess",
                "nnUNetv2_train",
                "nnUNetv2_predict_from_modelfolder",
            ):
                assert shutil.which(command), command
                subprocess.run(
                    [command, "--help"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )

            import nnunetv2
            from nnunetv2.training.nnUNetTrainer.nnUNetTrainer import nnUNetTrainer

            print("nnU-Net package:", Path(nnunetv2.__file__).resolve())
            print("Base trainer:", inspect.getfile(nnUNetTrainer))
            display({
                "torch": torch.__version__,
                "cuda_runtime": torch.version.cuda,
                "nnunet": importlib.metadata.version("nnunetv2"),
                "nnunet_commit": NNUNET_COMMIT,
                "gpus": gpu_records,
            })
            """,
        ),
        markdown(
            "resume-heading",
            """
            ## 3 — Restore optional resume state

            Attach at most one prior resume archive. It contains checkpoints and
            reports, never source T1 images or manual masks.
            """,
        ),
        code(
            "restore-resume",
            """
            def safe_extract_tar(archive_path: Path, destination: Path) -> None:
                root = destination.resolve()
                with tarfile.open(archive_path, "r:*") as archive:
                    for member in archive.getmembers():
                        target = (destination / member.name).resolve()
                        assert target == root or root in target.parents, member.name
                    archive.extractall(destination)

            if RESUME_ARCHIVE_OVERRIDE:
                resume_archives = [Path(RESUME_ARCHIVE_OVERRIDE)]
            else:
                resume_archives = sorted(
                    Path("/kaggle/input").rglob(
                        "LYS_T1_brainmask_standard3d_resume.tar.gz"
                    )
                )
            assert len(resume_archives) <= 1, resume_archives
            if resume_archives:
                assert not EXPERIMENT_ROOT.exists()
                assert not (NNUNET_RESULTS / DATASET_NAME).exists()
                safe_extract_tar(resume_archives[0], WORK)
                print("Restored:", resume_archives[0])
            else:
                print("No resume archive attached.")

            PROVENANCE.mkdir(parents=True, exist_ok=True)
            RUNS.mkdir(parents=True, exist_ok=True)
            """,
        ),
        markdown(
            "input-heading",
            """
            ## 4 — Locate and validate the approved training package

            Required manifest columns are:

            `case_id, animal_id, modality, acquisition_role, image, mask,
            include_for_nnunet, mask_review, reviewer, reviewed_at,
            image_sha256, mask_sha256`

            `animal_id` is explicit metadata; the notebook never derives it from a
            filename. Included labels must be individually approved with reviewer
            and timestamp. Paths must be relative to the manifest.
            """,
        ),
        code(
            "validate-input",
            """
            REQUIRED_COLUMNS = {
                "case_id",
                "animal_id",
                "modality",
                "acquisition_role",
                "image",
                "mask",
                "include_for_nnunet",
                "mask_review",
                "reviewer",
                "reviewed_at",
                "image_sha256",
                "mask_sha256",
            }
            TRUE_VALUES = {"1", "true", "yes", "y"}
            PASS_VALUES = {"pass", "passed", "approved", "approve", "accepted"}

            def safe_extract_zip(archive_path: Path, destination: Path) -> None:
                root = destination.resolve()
                with zipfile.ZipFile(archive_path) as archive:
                    for member in archive.infolist():
                        target = (destination / member.filename).resolve()
                        assert target == root or root in target.parents, member.filename
                    archive.extractall(destination)

            def locate_manifest() -> Path:
                if TRAINING_PACKAGE_OVERRIDE:
                    candidate = Path(TRAINING_PACKAGE_OVERRIDE)
                    if candidate.is_file() and candidate.name == "training_manifest.csv":
                        return candidate
                    if candidate.is_dir():
                        matches = sorted(candidate.rglob("training_manifest.csv"))
                        assert len(matches) == 1, matches
                        return matches[0]
                    assert candidate.suffix.lower() == ".zip", candidate
                    extraction = WORK / "uploaded_training_package"
                    extraction.mkdir(parents=True, exist_ok=True)
                    safe_extract_zip(candidate, extraction)
                    matches = sorted(extraction.rglob("training_manifest.csv"))
                    assert len(matches) == 1, matches
                    return matches[0]

                matches = sorted(Path("/kaggle/input").rglob("training_manifest.csv"))
                if len(matches) == 1:
                    return matches[0]
                assert not matches, f"Multiple training manifests: {matches}"
                archives = sorted(
                    Path("/kaggle/input").rglob(
                        "LYS_T1_brainmask_manual_v1.zip"
                    )
                )
                assert len(archives) == 1, (
                    "Attach exactly one approved T1 brain-mask package; "
                    f"found {archives}"
                )
                extraction = WORK / "uploaded_training_package"
                extraction.mkdir(parents=True, exist_ok=True)
                safe_extract_zip(archives[0], extraction)
                matches = sorted(extraction.rglob("training_manifest.csv"))
                assert len(matches) == 1, matches
                return matches[0]

            def relative_member(root: Path, value: str) -> Path:
                text = str(value).strip()
                assert text and not Path(text).is_absolute(), text
                candidate = (root / text).resolve()
                resolved_root = root.resolve()
                assert candidate == resolved_root or resolved_root in candidate.parents
                assert candidate.is_file(), candidate
                return candidate

            TRAINING_MANIFEST = locate_manifest()
            PACKAGE_ROOT = TRAINING_MANIFEST.parent
            all_rows = pd.read_csv(TRAINING_MANIFEST, keep_default_na=False)
            assert REQUIRED_COLUMNS <= set(all_rows.columns), (
                REQUIRED_COLUMNS - set(all_rows.columns)
            )
            assert all_rows.case_id.is_unique
            include = (
                all_rows.include_for_nnunet.astype(str).str.strip().str.lower()
                .isin(TRUE_VALUES)
            )
            approved = (
                all_rows.mask_review.astype(str).str.strip().str.lower()
                .isin(PASS_VALUES)
            )
            assert not (include & ~approved).any(), (
                "An included mask lacks explicit human approval"
            )
            rows = all_rows.loc[include].copy().reset_index(drop=True)
            assert len(rows) == EXPECTED_APPROVED_CASES, (
                len(rows), EXPECTED_APPROVED_CASES
            )
            assert rows.animal_id.astype(str).str.strip().ne("").all()
            assert rows.animal_id.nunique() == EXPECTED_ANIMAL_GROUPS, (
                rows.animal_id.nunique(), EXPECTED_ANIMAL_GROUPS
            )
            assert rows.reviewer.astype(str).str.strip().ne("").all()
            reviewed_times = pd.to_datetime(rows.reviewed_at, utc=True, errors="coerce")
            assert reviewed_times.notna().all(), "Missing/invalid reviewed_at"
            assert (
                rows.modality.astype(str).str.strip().str.lower() == "t1w"
            ).all()
            assert (
                rows.acquisition_role.astype(str).str.strip().str.lower()
                == "pre_gd"
            ).all()

            geometry_records = []
            verified_paths = {}
            for record in rows.to_dict("records"):
                case_id = str(record["case_id"]).strip()
                assert case_id
                image_path = relative_member(PACKAGE_ROOT, record["image"])
                mask_path = relative_member(PACKAGE_ROOT, record["mask"])
                assert sha256(image_path) == str(record["image_sha256"]).lower()
                assert sha256(mask_path) == str(record["mask_sha256"]).lower()
                image = nib.load(str(image_path))
                mask = nib.load(str(mask_path))
                assert image.ndim == mask.ndim == 3, case_id
                assert image.shape == mask.shape, case_id
                assert np.allclose(image.affine, mask.affine, atol=1e-5), case_id
                image_data = np.asarray(image.dataobj)
                mask_data = np.asarray(mask.dataobj)
                assert np.isfinite(image_data).all(), case_id
                values = np.unique(mask_data)
                assert set(values.tolist()) <= {0, 1}, (case_id, values)
                assert np.count_nonzero(mask_data) > 0, case_id
                verified_paths[case_id] = (image_path, mask_path)
                geometry_records.append({
                    "case_id": case_id,
                    "animal_id": record["animal_id"],
                    "shape": "x".join(map(str, image.shape)),
                    "spacing_mm": "x".join(
                        f"{value:.9g}" for value in image.header.get_zooms()[:3]
                    ),
                    "brain_voxels": int(np.count_nonzero(mask_data)),
                    "image_sha256": sha256(image_path),
                    "mask_sha256": sha256(mask_path),
                })
                del image_data, mask_data

            input_manifest_copy = PROVENANCE / "training_manifest.csv"
            if input_manifest_copy.is_file():
                assert sha256(input_manifest_copy) == sha256(TRAINING_MANIFEST)
            else:
                shutil.copy2(TRAINING_MANIFEST, input_manifest_copy)
            geometry = pd.DataFrame(geometry_records)
            geometry.to_csv(PROVENANCE / "input_geometry.csv", index=False)
            display({
                "manifest": str(TRAINING_MANIFEST),
                "approved_cases": len(rows),
                "animal_groups": rows.animal_id.nunique(),
                "shapes": geometry["shape"].value_counts().to_dict(),
                "spacings_mm": geometry["spacing_mm"].value_counts().to_dict(),
            })
            """,
        ),
        markdown(
            "materialize-heading",
            """
            ## 5 — Materialize nnU-Net raw data and fixed grouped folds

            A seeded deterministic allocator balances whole animal groups across
            five folds. Longitudinal scans and repeat acquisitions with the same
            explicit `animal_id` cannot cross folds.
            """,
        ),
        code(
            "materialize",
            """
            RAW_DATASET = NNUNET_RAW / DATASET_NAME
            images_tr = RAW_DATASET / "imagesTr"
            labels_tr = RAW_DATASET / "labelsTr"
            images_tr.mkdir(parents=True, exist_ok=True)
            labels_tr.mkdir(parents=True, exist_ok=True)

            mapping_records = []
            for index, record in enumerate(
                rows.sort_values("case_id").to_dict("records")
            ):
                case_id = str(record["case_id"])
                nnunet_case_id = f"T1BM_{index:03d}"
                source_image, source_mask = verified_paths[case_id]
                output_image = images_tr / f"{nnunet_case_id}_0000.nii.gz"
                output_mask = labels_tr / f"{nnunet_case_id}.nii.gz"
                if not output_image.is_file():
                    shutil.copy2(source_image, output_image)
                mask_image = nib.load(str(source_mask))
                binary = (np.asarray(mask_image.dataobj) > 0).astype(np.uint8)
                if not output_mask.is_file():
                    header = mask_image.header.copy()
                    header.set_data_dtype(np.uint8)
                    clean_mask = nib.Nifti1Image(
                        binary, mask_image.affine, header=header
                    )
                    qform, qcode = mask_image.get_qform(coded=True)
                    sform, scode = mask_image.get_sform(coded=True)
                    clean_mask.set_qform(qform, int(qcode))
                    clean_mask.set_sform(sform, int(scode))
                    nib.save(clean_mask, str(output_mask))
                mapping_records.append({
                    "case_id": case_id,
                    "nnunet_case_id": nnunet_case_id,
                    "animal_id": str(record["animal_id"]),
                    "reviewer": str(record["reviewer"]),
                    "reviewed_at": str(record["reviewed_at"]),
                    "source_image_sha256": str(record["image_sha256"]).lower(),
                    "source_mask_sha256": str(record["mask_sha256"]).lower(),
                })

            dataset_json = {
                "channel_names": {"0": "pre-Gd T1w"},
                "labels": {"background": 0, "brain": 1},
                "numTraining": len(mapping_records),
                "file_ending": ".nii.gz",
            }
            (RAW_DATASET / "dataset.json").write_text(
                json.dumps(dataset_json, indent=2, sort_keys=True) + "\\n"
            )
            mapping = pd.DataFrame(mapping_records)
            mapping.to_csv(RAW_DATASET / "case_mapping.csv", index=False)

            # Descending group size, with a seeded hash only as a deterministic tie-break.
            group_cases = {
                animal_id: sorted(part.nnunet_case_id.tolist())
                for animal_id, part in mapping.groupby("animal_id")
            }
            ordered_groups = sorted(
                group_cases,
                key=lambda animal_id: (
                    -len(group_cases[animal_id]),
                    hashlib.sha256(
                        f"{RUN_SEED}:{animal_id}".encode()
                    ).hexdigest(),
                ),
            )
            fold_groups = [set() for _ in range(5)]
            fold_case_counts = [0] * 5
            for animal_id in ordered_groups:
                fold = min(
                    range(5),
                    key=lambda value: (
                        fold_case_counts[value],
                        len(fold_groups[value]),
                        value,
                    ),
                )
                fold_groups[fold].add(animal_id)
                fold_case_counts[fold] += len(group_cases[animal_id])

            all_ids = set(mapping.nnunet_case_id)
            splits = []
            split_records = []
            for fold, validation_groups in enumerate(fold_groups):
                validation_ids = sorted(
                    mapping.loc[
                        mapping.animal_id.isin(validation_groups),
                        "nnunet_case_id",
                    ]
                )
                training_ids = sorted(all_ids - set(validation_ids))
                assert set(training_ids).isdisjoint(validation_ids)
                assert set(training_ids) | set(validation_ids) == all_ids
                splits.append({"train": training_ids, "val": validation_ids})
                for record in mapping.to_dict("records"):
                    split_records.append({
                        **record,
                        "fold": fold,
                        "role": (
                            "validation"
                            if record["nnunet_case_id"] in validation_ids
                            else "training"
                        ),
                    })

            for animal_id, part in pd.DataFrame(split_records).groupby(
                ["fold", "animal_id"]
            ):
                assert part.role.nunique() == 1, animal_id
            (RAW_DATASET / "splits_final.json").write_text(
                json.dumps(splits, indent=2, sort_keys=True) + "\\n"
            )
            split_assignments = pd.DataFrame(split_records)
            split_assignments.to_csv(
                PROVENANCE / "split_assignments.csv", index=False
            )
            shutil.copy2(
                RAW_DATASET / "case_mapping.csv",
                PROVENANCE / "case_mapping.csv",
            )
            shutil.copy2(
                RAW_DATASET / "dataset.json",
                PROVENANCE / "dataset.json",
            )
            shutil.copy2(
                RAW_DATASET / "splits_final.json",
                PROVENANCE / "splits_final.json",
            )
            display(
                split_assignments.loc[
                    split_assignments.role == "validation"
                ].groupby("fold").agg(
                    cases=("case_id", "count"),
                    animals=("animal_id", "nunique"),
                )
            )
            """,
        ),
        markdown(
            "plan-heading",
            """
            ## 6 — Plan and preprocess the official compact 3-D candidate

            The architecture gate forbids an accidental ResEnc rerun. On the
            audited 34-case geometry, the expected plan has a batch size of 2,
            patch 80×192×160, 30,785,994 parameters, and about 117 MiB of
            float32 inference weights.
            """,
        ),
        code(
            "plan-preprocess",
            """
            PREPROCESSED_DATASET = NNUNET_PREPROCESSED / DATASET_NAME
            PLAN_PATH = PREPROCESSED_DATASET / f"{PLANS}.json"
            if not PLAN_PATH.is_file():
                subprocess.run(
                    [
                        "nnUNetv2_plan_and_preprocess",
                        "-d",
                        str(DATASET_ID),
                        "-pl",
                        PLANNER,
                        "-c",
                        CONFIGURATION,
                        "-npfp",
                        "2",
                        "-np",
                        "2",
                        "--verify_dataset_integrity",
                    ],
                    check=True,
                )
            assert PLAN_PATH.is_file()
            shutil.copy2(
                RAW_DATASET / "splits_final.json",
                PREPROCESSED_DATASET / "splits_final.json",
            )

            from nnunetv2.utilities.get_network_from_plans import (
                get_network_from_plans,
            )

            plans_json = json.loads(PLAN_PATH.read_text())
            planned = plans_json["configurations"][CONFIGURATION]
            architecture = planned["architecture"]
            assert architecture["network_class_name"].endswith("PlainConvUNet")
            assert "ResidualEncoderUNet" not in architecture["network_class_name"]
            assert planned["batch_size"] >= NUM_GPUS, (
                "The global batch must be at least the DDP world size"
            )
            network = get_network_from_plans(
                architecture["network_class_name"],
                architecture["arch_kwargs"],
                architecture["_kw_requires_import"],
                input_channels=1,
                output_channels=2,
                allow_init=False,
                deep_supervision=False,
            )
            parameter_count = sum(value.numel() for value in network.parameters())
            del network
            assert parameter_count <= 35_000_000, parameter_count
            plan_summary = {
                "network_class": architecture["network_class_name"],
                "parameter_count": parameter_count,
                "float32_weight_mib": parameter_count * 4 / 1024**2,
                "batch_size": planned["batch_size"],
                "patch_size": planned["patch_size"],
                "spacing": planned["spacing"],
                "median_image_size_in_voxels": (
                    planned["median_image_size_in_voxels"]
                ),
                "features_per_stage": (
                    architecture["arch_kwargs"]["features_per_stage"]
                ),
                "plans_sha256": sha256(PLAN_PATH),
            }
            (PROVENANCE / "plan_summary.json").write_text(
                json.dumps(plan_summary, indent=2, sort_keys=True) + "\\n"
            )

            identity = {
                "protocol": "lys_t1_brainmask_standard3d_v1",
                "run_seed": RUN_SEED,
                "approved_case_count": len(rows),
                "animal_group_count": int(rows.animal_id.nunique()),
                "training_manifest_sha256": sha256(TRAINING_MANIFEST),
                "split_sha256": sha256(PROVENANCE / "splits_final.json"),
                "nnunet_version": importlib.metadata.version("nnunetv2"),
                "nnunet_source_commit": NNUNET_COMMIT,
                "torch_version": torch.__version__,
                "cuda_runtime": torch.version.cuda,
                "gpus": gpu_records,
                "planner": PLANNER,
                "plans": PLANS,
                "configuration": CONFIGURATION,
                "postprocessing": "none",
                "released_model_count": 1,
                "human_review_required": True,
            }
            identity_path = PROVENANCE / "protocol_identity.json"
            if identity_path.is_file():
                assert json.loads(identity_path.read_text()) == identity
            else:
                identity_path.write_text(
                    json.dumps(identity, indent=2, sort_keys=True) + "\\n"
                )
            display(plan_summary)
            """,
        ),
        markdown(
            "trainer-heading",
            """
            ## 7 — Install resume-safe trainer variants

            Upstream nnU-Net saves `checkpoint_latest.pth` every 50 epochs. These
            otherwise unchanged 5- and 250-epoch variants overwrite that latest
            checkpoint after every epoch. This improves crash recovery without
            changing the network or loss.
            """,
        ),
        code(
            "custom-trainers",
            '''
            from nnunetv2.training.nnUNetTrainer import nnUNetTrainer as trainer_package

            trainer_directory = Path(trainer_package.__file__).resolve().parent
            custom_trainer_file = trainer_directory / "lys_t1_save_every_epoch.py"
            custom_trainer_source = """import importlib


            length_trainers = importlib.import_module(
                "nnunetv2.training.nnUNetTrainer.variants.training_length."
                "nnUNetTrainer_Xepochs"
            )


            class nnUNetTrainer_5epochs_SaveEveryEpoch(
                length_trainers.nnUNetTrainer_5epochs
            ):
                def __init__(self, plans, configuration, fold, dataset_json, device):
                    super().__init__(plans, configuration, fold, dataset_json, device)
                    self.save_every = 1


            class nnUNetTrainer_250epochs_SaveEveryEpoch(
                length_trainers.nnUNetTrainer_250epochs
            ):
                def __init__(self, plans, configuration, fold, dataset_json, device):
                    super().__init__(plans, configuration, fold, dataset_json, device)
                    self.save_every = 1
            """
            custom_trainer_file.write_text(custom_trainer_source)
            (PROVENANCE / "custom_trainer.py").write_text(custom_trainer_source)
            print("Custom trainer:", custom_trainer_file)
            print("SHA-256:", sha256(custom_trainer_file))
            ''',
        ),
        markdown(
            "training-heading",
            """
            ## 8 — Resume-safe training helpers

            A stopped fold continues from its per-epoch latest checkpoint. A
            completed development fold is accepted only when its best checkpoint,
            summary, and exact expected validation IDs are present.
            """,
        ),
        code(
            "training-helpers",
            """
            def model_root(trainer: str) -> Path:
                return (
                    NNUNET_RESULTS
                    / DATASET_NAME
                    / f"{trainer}__{PLANS}__{CONFIGURATION}"
                )

            def model_folder(trainer: str, fold) -> Path:
                return model_root(trainer) / f"fold_{fold}"

            def expected_validation_ids(fold: int) -> set[str]:
                split = json.loads(
                    (PROVENANCE / "splits_final.json").read_text()
                )[fold]
                return set(split["val"])

            def training_command(trainer: str, fold) -> list[str]:
                return [
                    "nnUNetv2_train",
                    str(DATASET_ID),
                    CONFIGURATION,
                    str(fold),
                    "-tr",
                    trainer,
                    "-p",
                    PLANS,
                    "-num_gpus",
                    str(NUM_GPUS),
                ]

            def train_and_validate(trainer: str, fold: int, marker: Path) -> dict:
                folder = model_folder(trainer, fold)
                best = folder / "checkpoint_best.pth"
                final = folder / "checkpoint_final.pth"
                latest = folder / "checkpoint_latest.pth"
                validation = folder / "validation"
                expected = expected_validation_ids(fold)
                if marker.is_file():
                    recorded = json.loads(marker.read_text())
                    assert best.is_file()
                    assert recorded["checkpoint_best_sha256"] == sha256(best)
                    assert {path.stem for path in validation.glob("*.npz")} == expected
                    return recorded

                command = training_command(trainer, fold)
                started = time.time()
                if final.is_file():
                    subprocess.run(
                        command + ["--val", "--npz", "--val_best"],
                        check=True,
                    )
                else:
                    if latest.is_file():
                        command.append("--c")
                    subprocess.run(
                        command + ["--npz", "--val_best"],
                        check=True,
                    )
                elapsed = time.time() - started

                assert best.is_file()
                assert (validation / "summary.json").is_file()
                observed = {path.stem for path in validation.glob("*.npz")}
                assert observed == expected, {
                    "missing": sorted(expected - observed),
                    "unexpected": sorted(observed - expected),
                }
                checkpoint = torch.load(
                    best, map_location="cpu", weights_only=False
                )
                parameters = sum(
                    tensor.numel()
                    for tensor in checkpoint["network_weights"].values()
                )
                record = {
                    "trainer": trainer,
                    "fold": fold,
                    "elapsed_seconds_this_call": elapsed,
                    "checkpoint_best_sha256": sha256(best),
                    "checkpoint_best_bytes": best.stat().st_size,
                    "parameter_count": parameters,
                    "n_validation_cases": len(expected),
                    "checkpoint_selection": "best validation EMA pseudo-Dice",
                    "postprocessing": "none",
                }
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    json.dumps(record, indent=2, sort_keys=True) + "\\n"
                )
                return record

            def train_all(marker: Path) -> dict:
                folder = model_folder(CV_TRAINER, "all")
                final = folder / "checkpoint_final.pth"
                latest = folder / "checkpoint_latest.pth"
                if marker.is_file():
                    recorded = json.loads(marker.read_text())
                    assert final.is_file()
                    assert recorded["checkpoint_final_sha256"] == sha256(final)
                    return recorded
                command = training_command(CV_TRAINER, "all")
                started = time.time()
                if not final.is_file():
                    if latest.is_file():
                        command.append("--c")
                    subprocess.run(command, check=True)
                record = {
                    "trainer": CV_TRAINER,
                    "fold": "all",
                    "elapsed_seconds_this_call": time.time() - started,
                    "checkpoint_final_sha256": sha256(final),
                    "checkpoint_final_bytes": final.stat().st_size,
                    "training_cases": len(mapping),
                    "release_checkpoint": "checkpoint_final",
                    "development_validation_claim": False,
                }
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    json.dumps(record, indent=2, sort_keys=True) + "\\n"
                )
                return record
            """,
        ),
        markdown(
            "benchmark-heading",
            """
            ## 9 — Fold-0 five-epoch benchmark

            This tests execution and packaging only. Its apparent Dice is not an
            estimate of the final model and must not select a method.
            """,
        ),
        code(
            "benchmark",
            """
            benchmark_record = None
            if RUN_BENCHMARK_5E:
                benchmark_record = train_and_validate(
                    BENCHMARK_TRAINER,
                    0,
                    RUNS / "benchmark_5e/fold_0/complete.json",
                )
                display(benchmark_record)
                progress = model_folder(BENCHMARK_TRAINER, 0) / "progress.png"
                if progress.is_file():
                    display(Image(filename=str(progress)))
            else:
                print("Five-epoch benchmark disabled.")
            """,
        ),
        markdown(
            "benchmark-package-heading",
            """
            ## 10 — Download the inference-only five-epoch benchmark

            The bundle contains one float32 network and only the metadata nnU-Net
            needs for inference. Training optimizer state is deliberately removed.
            """,
        ),
        code(
            "benchmark-package",
            """
            def portable_checkpoint(
                source: Path, destination: Path, portable_trainer: str
            ) -> dict:
                checkpoint = torch.load(
                    source, map_location="cpu", weights_only=False
                )
                required = {
                    "network_weights",
                    "init_args",
                    "inference_allowed_mirroring_axes",
                }
                assert required <= set(checkpoint)
                compact = {
                    "network_weights": checkpoint["network_weights"],
                    "trainer_name": portable_trainer,
                    "init_args": checkpoint["init_args"],
                    "inference_allowed_mirroring_axes": (
                        checkpoint["inference_allowed_mirroring_axes"]
                    ),
                }
                destination.parent.mkdir(parents=True, exist_ok=True)
                torch.save(compact, destination)
                return {
                    "source_sha256": sha256(source),
                    "portable_sha256": sha256(destination),
                    "portable_bytes": destination.stat().st_size,
                    "preserved_keys": sorted(compact),
                }

            if RUN_BENCHMARK_5E:
                bundle_parent = WORK / "benchmark_inference_bundle"
                bundle_name = (
                    "nnUNetTrainer_5epochs__nnUNetPlans__3d_fullres"
                )
                bundle_root = bundle_parent / bundle_name
                if bundle_parent.exists():
                    shutil.rmtree(bundle_parent)
                bundle_root.mkdir(parents=True)
                source_root = model_root(BENCHMARK_TRAINER)
                shutil.copy2(source_root / "plans.json", bundle_root / "plans.json")
                shutil.copy2(
                    source_root / "dataset.json", bundle_root / "dataset.json"
                )
                portable_record = portable_checkpoint(
                    source_root / "fold_0/checkpoint_best.pth",
                    bundle_root / "fold_0/checkpoint_best.pth",
                    "nnUNetTrainer_5epochs",
                )
                (bundle_root / "benchmark_manifest.json").write_text(
                    json.dumps(
                        {
                            **portable_record,
                            "benchmark_only": True,
                            "fold": 0,
                            "disable_tta_for_cpu_test": True,
                            "plan": plan_summary,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\\n"
                )
                benchmark_zip = (
                    WORK / "LYS_T1_standard3d_5epoch_inference_only.zip"
                )
                with zipfile.ZipFile(
                    benchmark_zip,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    for path in sorted(bundle_parent.rglob("*")):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, path.relative_to(bundle_parent))
                    for path in (
                        PROVENANCE / "protocol_identity.json",
                        PROVENANCE / "plan_summary.json",
                        PROVENANCE / "split_assignments.csv",
                    ):
                        archive.write(
                            path, Path("benchmark_provenance") / path.name
                        )
                print(
                    "Benchmark:",
                    benchmark_zip,
                    f"{benchmark_zip.stat().st_size / 1024**2:.1f} MiB",
                )
                display(FileLink(str(benchmark_zip)))
            """,
        ),
        markdown(
            "cv-heading",
            """
            ## 11 — Five animal-disjoint 250-epoch development folds

            Run these only after the benchmark model completes a satisfactory CPU
            runtime/memory test on the ZenBook. Finished folds are skipped; an
            interrupted fold resumes from the last completed epoch.
            """,
        ),
        code(
            "cross-validation",
            """
            cv_records = []
            if RUN_CV_250:
                for fold in FOLDS_TO_RUN:
                    record = train_and_validate(
                        CV_TRAINER,
                        fold,
                        RUNS / f"cv_250/fold_{fold}/complete.json",
                    )
                    cv_records.append(record)
                    display(record)
            else:
                print("250-epoch CV disabled.")
            """,
        ),
        markdown(
            "oof-heading",
            """
            ## 12 — Pooled OOF evaluation, including the fast no-TTA policy

            When all folds finish, the notebook predicts each held-out fold again
            without mirroring. It reports paired full-case Dice, precision, recall,
            volume error, HD95, and 0.15-mm surface Dice for default TTA and no-TTA.
            Overall voxel accuracy is intentionally absent.
            """,
        ),
        code(
            "oof-evaluation",
            """
            OOF_ROOT = EXPERIMENT_ROOT / "oof_250"
            complete_markers = [
                RUNS / f"cv_250/fold_{fold}/complete.json"
                for fold in range(5)
            ]

            def predict_validation_without_tta(fold: int) -> Path:
                split = json.loads(
                    (PROVENANCE / "splits_final.json").read_text()
                )[fold]
                input_folder = OOF_ROOT / f"fold_{fold}/no_tta_input"
                output_folder = OOF_ROOT / f"fold_{fold}/no_tta_predictions"
                input_folder.mkdir(parents=True, exist_ok=True)
                expected = set(split["val"])
                for case_id in expected:
                    source = images_tr / f"{case_id}_0000.nii.gz"
                    destination = input_folder / source.name
                    if not destination.is_file():
                        shutil.copy2(source, destination)
                if {
                    path.name.removesuffix(".nii.gz")
                    for path in output_folder.glob("*.nii.gz")
                } != expected:
                    subprocess.run(
                        [
                            "nnUNetv2_predict_from_modelfolder",
                            "-i",
                            str(input_folder),
                            "-o",
                            str(output_folder),
                            "-m",
                            str(model_root(CV_TRAINER)),
                            "-f",
                            str(fold),
                            "-chk",
                            "checkpoint_best.pth",
                            "-device",
                            "cuda",
                            "-npp",
                            "2",
                            "-nps",
                            "2",
                            "--disable_tta",
                        ],
                        check=True,
                    )
                observed = {
                    path.name.removesuffix(".nii.gz")
                    for path in output_folder.glob("*.nii.gz")
                }
                assert observed == expected, (observed, expected)
                return output_folder

            def case_metrics(target_path: Path, prediction_path: Path) -> dict:
                from surface_distance import metrics as surface_metrics

                target_image = nib.load(str(target_path))
                prediction_image = nib.load(str(prediction_path))
                assert target_image.shape == prediction_image.shape
                assert np.allclose(
                    target_image.affine, prediction_image.affine, atol=1e-4
                )
                target = np.asarray(target_image.dataobj) > 0
                prediction = np.asarray(prediction_image.dataobj) > 0
                tp = int(np.count_nonzero(target & prediction))
                fp = int(np.count_nonzero(~target & prediction))
                fn = int(np.count_nonzero(target & ~prediction))
                dice = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0
                precision = tp / (tp + fp) if tp + fp else 1.0
                recall = tp / (tp + fn) if tp + fn else 1.0
                target_voxels = int(np.count_nonzero(target))
                predicted_voxels = int(np.count_nonzero(prediction))
                volume_error_pct = (
                    100 * (predicted_voxels - target_voxels) / target_voxels
                )
                spacing = target_image.header.get_zooms()[:3]
                distances = surface_metrics.compute_surface_distances(
                    target, prediction, spacing
                )
                return {
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "dice": dice,
                    "precision": precision,
                    "recall": recall,
                    "volume_error_pct": volume_error_pct,
                    "abs_volume_error_pct": abs(volume_error_pct),
                    "hd95_mm": surface_metrics.compute_robust_hausdorff(
                        distances, 95
                    ),
                    "surface_dice": (
                        surface_metrics.compute_surface_dice_at_tolerance(
                            distances, SURFACE_TOLERANCE_MM
                        )
                    ),
                    "empty_prediction": predicted_voxels == 0,
                }

            def summarize_metrics(part: pd.DataFrame) -> dict:
                tp = int(part.tp.sum())
                fp = int(part.fp.sum())
                fn = int(part.fn.sum())
                return {
                    "cases": len(part),
                    "pooled_voxel_dice": 2 * tp / (2 * tp + fp + fn),
                    "mean_case_dice": float(part.dice.mean()),
                    "median_case_dice": float(part.dice.median()),
                    "minimum_case_dice": float(part.dice.min()),
                    "mean_precision": float(part.precision.mean()),
                    "mean_recall": float(part.recall.mean()),
                    "mean_abs_volume_error_pct": float(
                        part.abs_volume_error_pct.mean()
                    ),
                    "median_hd95_mm": float(part.hd95_mm.median()),
                    "mean_surface_dice": float(part.surface_dice.mean()),
                    "empty_predictions": int(part.empty_prediction.sum()),
                }

            if RUN_CV_250 and all(path.is_file() for path in complete_markers):
                metric_records = []
                mapping_by_nnunet = mapping.set_index("nnunet_case_id")
                for fold in range(5):
                    no_tta_folder = predict_validation_without_tta(fold)
                    tta_folder = model_folder(CV_TRAINER, fold) / "validation"
                    for nnunet_case_id in expected_validation_ids(fold):
                        identity_row = mapping_by_nnunet.loc[nnunet_case_id]
                        target = labels_tr / f"{nnunet_case_id}.nii.gz"
                        for policy, folder in (
                            ("default_tta", tta_folder),
                            ("no_tta", no_tta_folder),
                        ):
                            metric_records.append({
                                "case_id": identity_row.case_id,
                                "animal_id": identity_row.animal_id,
                                "nnunet_case_id": nnunet_case_id,
                                "fold": fold,
                                "inference_policy": policy,
                                **case_metrics(
                                    target,
                                    folder / f"{nnunet_case_id}.nii.gz",
                                ),
                            })
                oof_metrics = pd.DataFrame(metric_records)
                assert len(oof_metrics) == 2 * len(mapping)
                assert not oof_metrics.duplicated(
                    ["case_id", "inference_policy"]
                ).any()
                oof_metrics.to_csv(
                    OOF_ROOT / "oof_case_metrics.csv", index=False
                )
                summaries = {
                    policy: summarize_metrics(part)
                    for policy, part in oof_metrics.groupby("inference_policy")
                }
                paired = oof_metrics.pivot(
                    index="case_id",
                    columns="inference_policy",
                    values="dice",
                )
                summaries["paired_no_tta_minus_tta_dice"] = {
                    "mean": float(
                        (paired.no_tta - paired.default_tta).mean()
                    ),
                    "median": float(
                        (paired.no_tta - paired.default_tta).median()
                    ),
                    "minimum": float(
                        (paired.no_tta - paired.default_tta).min()
                    ),
                }
                (OOF_ROOT / "oof_summary.json").write_text(
                    json.dumps(summaries, indent=2, sort_keys=True) + "\\n"
                )
                display(summaries)
            else:
                print("OOF evaluation waits for all five completed CV folds.")
            """,
        ),
        markdown(
            "final-heading",
            """
            ## 13 — Train one final 250-epoch model on all approved labels

            Set `RUN_FINAL_ALL_250=True` only after reviewing the complete OOF
            report. `fold_all` is training-only and makes no validation claim;
            its release checkpoint is `checkpoint_final.pth`.
            """,
        ),
        code(
            "final-training",
            """
            final_record = None
            if RUN_FINAL_ALL_250:
                assert (OOF_ROOT / "oof_summary.json").is_file(), (
                    "Review complete grouped OOF evidence before final training"
                )
                final_record = train_all(
                    RUNS / "final_all_250/complete.json"
                )
                display(final_record)
            else:
                print("Final all-data training disabled.")
            """,
        ),
        markdown(
            "final-package-heading",
            """
            ## 14 — Package the single inference-only release

            Optimizer, scheduler, scaler, and logger state are removed. This does
            not change network tensors or predictions. The custom save-frequency
            trainer name is replaced by the equivalent installed upstream
            250-epoch trainer so the model remains portable.
            """,
        ),
        code(
            "final-package",
            """
            if RUN_FINAL_ALL_250:
                release_parent = WORK / "final_inference_release"
                release_name = (
                    "nnUNetTrainer_250epochs__nnUNetPlans__3d_fullres"
                )
                release_root = release_parent / release_name
                if release_parent.exists():
                    shutil.rmtree(release_parent)
                release_root.mkdir(parents=True)
                source_root = model_root(CV_TRAINER)
                shutil.copy2(source_root / "plans.json", release_root / "plans.json")
                shutil.copy2(
                    source_root / "dataset.json", release_root / "dataset.json"
                )
                release_checkpoint_record = portable_checkpoint(
                    source_root / "fold_all/checkpoint_final.pth",
                    release_root / "fold_all/checkpoint_final.pth",
                    "nnUNetTrainer_250epochs",
                )
                release_manifest = {
                    **release_checkpoint_record,
                    "fold": "all",
                    "checkpoint": "checkpoint_final.pth",
                    "model_count": 1,
                    "disable_tta": DEPLOY_DISABLE_TTA,
                    "postprocessing": "none",
                    "predictions_are_drafts": True,
                    "parameter_count": plan_summary["parameter_count"],
                    "training_manifest_sha256": sha256(TRAINING_MANIFEST),
                    "oof_summary_sha256": sha256(
                        OOF_ROOT / "oof_summary.json"
                    ),
                }
                (release_root / "release_manifest.json").write_text(
                    json.dumps(release_manifest, indent=2, sort_keys=True) + "\\n"
                )
                for path in (
                    PROVENANCE / "protocol_identity.json",
                    PROVENANCE / "plan_summary.json",
                    PROVENANCE / "split_assignments.csv",
                    OOF_ROOT / "oof_summary.json",
                    OOF_ROOT / "oof_case_metrics.csv",
                ):
                    destination = release_root / "provenance" / path.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)

                release_zip = (
                    WORK / "LYS_T1_brainmask_standard3d_final_inference.zip"
                )
                with zipfile.ZipFile(
                    release_zip,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    for path in sorted(release_parent.rglob("*")):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, path.relative_to(release_parent))
                print(
                    "Final inference release:",
                    release_zip,
                    f"{release_zip.stat().st_size / 1024**2:.1f} MiB",
                )
                display(FileLink(str(release_zip)))
            """,
        ),
        markdown(
            "review-heading",
            """
            ## 15 — Build review and resume artifacts

            Run this at the end of every session, including after a stopped training
            cell. The review ZIP excludes weights. The resume tar retains training
            checkpoints but excludes source MRI, manual masks, and preprocessed data.
            """,
        ),
        code(
            "review-resume",
            """
            review_zip = WORK / "LYS_T1_brainmask_standard3d_review.zip"
            allowed_suffixes = {
                ".json", ".csv", ".txt", ".md", ".png", ".pdf", ".py"
            }
            with zipfile.ZipFile(
                review_zip, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for root in (EXPERIMENT_ROOT, RAW_DATASET, PREPROCESSED_DATASET):
                    if not root.exists():
                        continue
                    for path in sorted(root.rglob("*")):
                        if (
                            path.is_file()
                            and not path.is_symlink()
                            and path.suffix.lower() in allowed_suffixes
                            and path.stat().st_size <= 25 * 1024 * 1024
                        ):
                            archive.write(path, path.relative_to(WORK))
            print(
                "Review:",
                review_zip,
                f"{review_zip.stat().st_size / 1024**2:.1f} MiB",
            )
            display(FileLink(str(review_zip)))

            if BUILD_RESUME_ARCHIVE:
                resume_tar = (
                    WORK / "LYS_T1_brainmask_standard3d_resume.tar.gz"
                )
                with tarfile.open(resume_tar, "w:gz", compresslevel=1) as archive:
                    if EXPERIMENT_ROOT.exists():
                        archive.add(
                            EXPERIMENT_ROOT,
                            arcname=EXPERIMENT_ROOT.relative_to(WORK),
                        )
                    results = NNUNET_RESULTS / DATASET_NAME
                    if results.exists():
                        archive.add(results, arcname=results.relative_to(WORK))
                print(
                    "Resume:",
                    resume_tar,
                    f"{resume_tar.stat().st_size / 1024**3:.2f} GiB",
                )
                display(FileLink(str(resume_tar)))
            """,
        ),
        markdown(
            "interpretation",
            """
            ## Interpretation boundary

            - This is 34-scan/17-animal development evidence, not independent validation.
            - The five-epoch benchmark is not accuracy evidence.
            - The released all-data model has no unbiased validation score of its own.
            - Static pre/post T1-weighted scans support relative or semi-quantitative
              enhancement, not gadolinium concentration, absolute T1, Ktrans, Ki, DCE,
              or a direct permeability estimate.
            - Register post-Gd T1 to native pre-Gd T1 and apply the exact approved
              pre-space brain mask to both.
            - Every model output remains a draft until reviewed on the native pre-Gd
              grid and explicitly approved.
            """,
        ),
    ],
    "metadata": {
        "accelerator": "GPU",
        "colab": {
            "name": OUTPUT.name,
            "provenance": [],
        },
        "kaggle": {
            "accelerator": "gpu",
            "dataSources": [],
            "dockerImageVersionId": None,
            "isGpuEnabled": True,
            "isInternetEnabled": True,
        },
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(NOTEBOOK, indent=1, ensure_ascii=False) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
