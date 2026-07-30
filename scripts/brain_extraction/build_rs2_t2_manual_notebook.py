#!/usr/bin/env python3
"""Build the exact-TTA RS2/M-seam Colab notebook for LYS_T2w_manual_v1."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[2]
BASE_BUILDER = ROOT / "scripts/brain_extraction/build_rs2_all_mice_notebook.py"
OUTPUT = ROOT / "notebooks/brain_extraction_rs2_m_seam_t2_manual_v1_colab.ipynb"


def _load_base_notebook() -> dict:
    spec = importlib.util.spec_from_file_location("lys_rs2_all_mice_builder", BASE_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load notebook builder: {BASE_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return deepcopy(module.build_notebook())


def _cell(notebook: dict, cell_id: str) -> dict:
    matches = [cell for cell in notebook["cells"] if cell.get("id") == cell_id]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one notebook cell {cell_id!r}, found {len(matches)}")
    return matches[0]


def _set_source(notebook: dict, cell_id: str, source: str) -> None:
    source = dedent(source).strip("\n") + "\n"
    _cell(notebook, cell_id)["source"] = source.splitlines(keepends=True)


def build_notebook() -> dict:
    notebook = _load_base_notebook()

    _set_source(
        notebook,
        "overview",
        """
        # Exact-TTA RS2 + M-seam brain-mask pre-labels for LYS T2w manual v1

        This notebook runs the same pinned RS2-Net inference, eight-way test-time
        mirroring, selected M-seam cut, and conservative continuity cleanup used for
        the pre-Gd T1 draft masks. It processes only the 258 `scan.nii.gz` T2 images
        in the exact `LYS_T2w_manual_v1.tar.gz` archive; lesion masks are never used
        as inputs.

        The archive's scans are 256×256×18×1. The notebook verifies that layout,
        removes only the singleton fourth dimension for RS2, and writes native-grid
        3-D brain masks matching the spatial geometry of the archive's lesion labels.

        ## Run instructions

        1. Upload this notebook to Google Colab.
        2. Select **Runtime → Change runtime type → T4 GPU**.
        3. Run the dependency-bootstrap cell. Colab restarts once on the first run.
        4. After reconnecting, select **Runtime → Run all**.
        5. Upload the exact `LYS_T2w_manual_v1.tar.gz` file when prompted.
        6. Keep the browser connected through inference and the final download.

        The result ZIP contains flat ITK-SNAP pre-labels and a dataset-layout copy
        named `scan_brain_rs2_m_seam.nii.gz` beside each original scan path.

        **Scientific status:** the M-seam thresholds were selected on the T1 cohort,
        not validated on this T2 cohort. Every result is an automatic, unapproved
        pre-label. Review every slice, especially for superior cortical loss, before
        using a mask for analysis.
        """,
    )

    _set_source(
        notebook,
        "configuration",
        """
        from pathlib import Path
        import os, shutil, subprocess, sys
        import torch

        RS2_USE_TTA = True
        RUN_ALTERNATIVE_REFINEMENTS = False
        RUN_RANDOM_WALKER = False
        EXPECTED_CASE_COUNT = 258
        EXPECTED_ARCHIVE_SHA256 = 'a1ea6a999858db4f13498fdd9113f71c38d36300b59bfb9988f90f5b7b113701'
        RS2_WEIGHT_SHA256 = 'f7fef315d77c8568cd6d19867445ff51587505586c19b273087b65ccf3659371'
        RS2_COMMIT = '144b032df4885a3da00e0d1824fdd777b3cd304f'
        RS2_REPOSITORY = 'https://github.com/VitoLin21/Rodent-Skull-Stripping.git'
        RS2_DRIVE_FOLDER_ID = '1cTlFFGL9iTUoZOT5Rgqi2ZAyqyPlXYd-'

        BASE = Path('/content/lys_t2_manual_v1_brain_masks')
        PACKAGE_AREA = BASE / 'package'
        EXTERNAL = BASE / 'external'
        WORK = BASE / 'work'
        RESULTS = BASE / 't2_manual_v1_rs2_m_seam_results'
        for directory in (PACKAGE_AREA, EXTERNAL, WORK, RESULTS):
            directory.mkdir(parents=True, exist_ok=True)

        if not torch.cuda.is_available():
            raise RuntimeError(
                'No GPU detected. Select Runtime → Change runtime type → T4 GPU, then rerun.'
            )
        print('GPU:', torch.cuda.get_device_name(0))
        print('Python:', sys.version.split()[0], 'PyTorch:', torch.__version__)
        """,
    )

    _set_source(
        notebook,
        "upload-package",
        """
        # Upload, checksum, and prepare only the T2 scans from the exact tar.gz.
        from google.colab import files
        import csv, hashlib, io, json, tarfile
        import nibabel as nib
        import numpy as np

        uploaded = files.upload()
        archive_names = [
            name for name in uploaded
            if name.lower().endswith(('.tar.gz', '.tgz'))
        ]
        if len(archive_names) != 1:
            raise ValueError(
                f'Upload exactly one .tar.gz archive; received: {list(uploaded)}'
            )
        upload_path = Path('/content') / archive_names[0]
        del uploaded

        def file_sha256(path, chunk_size=1024 * 1024):
            digest = hashlib.sha256()
            with Path(path).open('rb') as stream:
                while chunk := stream.read(chunk_size):
                    digest.update(chunk)
            return digest.hexdigest()

        observed_archive_sha256 = file_sha256(upload_path)
        if observed_archive_sha256 != EXPECTED_ARCHIVE_SHA256:
            raise ValueError(
                'Dataset archive checksum mismatch. Expected '
                f'{EXPECTED_ARCHIVE_SHA256}, observed {observed_archive_sha256}'
            )
        print('Dataset archive checksum verified:', observed_archive_sha256)

        if PACKAGE_AREA.exists():
            shutil.rmtree(PACKAGE_AREA)
        PACKAGE_AREA.mkdir(parents=True)
        if RESULTS.exists():
            shutil.rmtree(RESULTS)
        (RESULTS / 'inputs').mkdir(parents=True)

        with tarfile.open(upload_path, mode='r:gz') as archive:
            members = {member.name: member for member in archive.getmembers()}
            manifest_names = [
                name for name in members if name == 'LYS_T2w_manual_v1/manifest.csv'
            ]
            if len(manifest_names) != 1:
                raise ValueError(
                    f'Expected LYS_T2w_manual_v1/manifest.csv, found {manifest_names}'
                )
            manifest_member = members[manifest_names[0]]
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                raise ValueError('Could not read the dataset manifest')
            manifest_text = manifest_stream.read().decode('utf-8')
            PACKAGE_ROWS = list(csv.DictReader(io.StringIO(manifest_text)))

            case_ids = [row['case_id'] for row in PACKAGE_ROWS]
            if len(PACKAGE_ROWS) != EXPECTED_CASE_COUNT:
                raise ValueError(
                    f'Expected {EXPECTED_CASE_COUNT} cases, found {len(PACKAGE_ROWS)}'
                )
            if len(case_ids) != len(set(case_ids)):
                raise ValueError('The dataset manifest contains duplicate case IDs')

            CASES = []
            for index, row in enumerate(PACKAGE_ROWS, start=1):
                case_id = row['case_id']
                scan_path = row['scan_path']
                expected_path = (
                    f"LYS_T2w_manual_v1/{row['split']}/{row['study']}/"
                    f"{row['timepoint']}/{case_id}/scan.nii.gz"
                )
                if scan_path != expected_path:
                    raise ValueError(
                        f'Unexpected scan path for {case_id}: {scan_path}'
                    )
                member = members.get(scan_path)
                if member is None or not member.isfile() or member.issym() or member.islnk():
                    raise ValueError(f'Missing or unsafe scan member: {scan_path}')
                target = (PACKAGE_AREA / member.name).resolve()
                if not target.is_relative_to(PACKAGE_AREA.resolve()):
                    raise ValueError(f'Unsafe archive path: {member.name}')
                archive.extract(member, path=PACKAGE_AREA)
                source = PACKAGE_AREA / scan_path
                source_sha256 = file_sha256(source)

                image_object = nib.load(str(source))
                image_data = np.asanyarray(image_object.dataobj)
                if image_data.ndim != 4 or image_data.shape[-1] != 1:
                    raise ValueError(
                        f'{case_id} must have shape X×Y×Z×1, found {image_data.shape}'
                    )
                image_3d = np.asarray(image_data[..., 0], dtype=np.float32)
                destination = RESULTS / 'inputs' / f'{case_id}_t2w.nii.gz'
                header = image_object.header.copy()
                header.set_data_dtype(np.float32)
                prepared = nib.Nifti1Image(
                    image_3d, image_object.affine, header
                )
                prepared.set_qform(
                    image_object.affine, code=int(image_object.header['qform_code'])
                )
                prepared.set_sform(
                    image_object.affine, code=int(image_object.header['sform_code'])
                )
                nib.save(prepared, destination)
                if prepared.shape != image_data.shape[:3]:
                    raise RuntimeError(f'Failed to prepare a 3-D image for {case_id}')
                CASES.append({
                    'case_id': case_id,
                    'image': destination,
                    'source_scan_path': scan_path,
                    'source_scan_sha256': source_sha256,
                    'source_shape': list(image_data.shape),
                })
                source.unlink()
                if index % 25 == 0 or index == len(PACKAGE_ROWS):
                    print(f'Prepared {index}/{len(PACKAGE_ROWS)} T2 scans')

        (RESULTS / 'input_manifest.csv').write_text(manifest_text)
        (RESULTS / 'input_archive_provenance.json').write_text(json.dumps({
            'uploaded_filename': upload_path.name,
            'archive_sha256': observed_archive_sha256,
            'case_count': len(CASES),
            'input_rule': 'manifest scan_path entries only; lesion labels excluded',
            'singleton_axis_handling': 'X×Y×Z×1 converted to X×Y×Z for RS2',
        }, indent=2) + '\\n')
        upload_path.unlink()
        shutil.rmtree(PACKAGE_AREA)
        print('Prepared cases:', len(CASES))
        print('First:', CASES[0]['case_id'])
        print('Last:', CASES[-1]['case_id'])
        """,
    )

    helpers = "".join(_cell(notebook, "shared-helpers")["source"])
    helpers = helpers.replace(
        "# Output contract, provenance, orientation, and NIfTI helpers.",
        "# Output contract, provenance, orientation, and 3-D NIfTI helpers.",
    )
    _set_source(notebook, "shared-helpers", helpers)

    run_rs2 = "".join(_cell(notebook, "run-rs2")["source"])
    run_rs2 = run_rs2.replace(
        "'input_sha256': sha256(image), 'mask_sha256': sha256(mask),",
        (
            "'input_sha256': sha256(image), "
            "'source_scan_path': case['source_scan_path'],\n"
            "            'source_scan_sha256': case['source_scan_sha256'], "
            "'source_shape': case['source_shape'],\n"
            "            'mask_sha256': sha256(mask),"
        ),
    )
    _set_source(notebook, "run-rs2", run_rs2)

    algorithm = "".join(_cell(notebook, "refinement-algorithms")["source"])
    algorithm = algorithm.replace("T1-guided", "T2-guided")
    algorithm = algorithm.replace("T1 intensity", "T2 intensity")
    _set_source(notebook, "refinement-algorithms", algorithm)

    apply_refinements = "".join(_cell(notebook, "apply-refinements")["source"])
    apply_refinements = apply_refinements.replace(
        "'Marker-controlled watershed on the local T1 gradient'",
        "'Marker-controlled watershed on the local T2 gradient'",
    )
    apply_refinements = apply_refinements.replace(
        "'Marker-based random walker on local T1 intensity'",
        "'Marker-based random walker on local T2 intensity'",
    )
    apply_refinements = apply_refinements.replace(
        "'input_sha256': sha256(image_path), 'source_mask_sha256': sha256(raw_path),",
        (
            "'input_sha256': sha256(image_path),\n"
            "                'source_scan_path': case['source_scan_path'],\n"
            "                'source_scan_sha256': case['source_scan_sha256'],\n"
            "                'source_mask_sha256': sha256(raw_path),"
        ),
    )
    _set_source(notebook, "apply-refinements", apply_refinements)

    qc = "".join(_cell(notebook, "qc-montages")["source"])
    qc = qc.replace("raw-versus-M-seam montages", "T2 raw-versus-M-seam montages")
    qc = qc.replace(
        "f'{case_id}_rs2_refinement_comparison.png'",
        "f'{case_id}_t2_rs2_m_seam_comparison.png'",
    )
    _set_source(notebook, "qc-montages", qc)

    _set_source(
        notebook,
        "summary-table",
        """
        # Review the extent of every proposed T2 correction before downloading.
        import pandas as pd

        summary = pd.DataFrame(SUMMARY_ROWS).sort_values(['case_id', 'method'])
        display(summary)
        print('\\nInterpretation:')
        print('- unchanged_no_confident_correction means the image gate retained raw RS2.')
        print('- A large removed percentage requires careful superior-cortex review.')
        print('- Regularity warnings prioritize review; they do not reject or approve a mask.')
        print('- The T1-selected M-seam thresholds are transferred here without T2 validation.')
        print('- All outputs are automatic candidates, not quantification-ready masks.')
        """,
    )

    _set_source(
        notebook,
        "validate-download",
        """
        # Validate, create flat and dataset-layout handoffs, then download one ZIP.
        validation_rows = []
        for case in CASES:
            case_id, image_path = case['case_id'], case['image']
            image_object = nib.load(str(image_path))
            image_native = np.asanyarray(image_object.dataobj)
            _, orientation = native_to_rsa(image_native, image_object.affine)
            native_spacing = tuple(
                float(value) for value in image_object.header.get_zooms()[:3]
            )
            spacing_rsa = tuple(
                native_spacing[axis] for axis in orientation['order']
            )
            raw_path = (
                RESULTS / 'predictions' / 'rs2net_raw'
                / f'{case_id}_brain_mask.nii.gz'
            )
            raw_object = nib.load(str(raw_path))
            raw = np.asanyarray(raw_object.dataobj) > 0
            for model_id in MODEL_ORDER:
                mask_path = (
                    RESULTS / 'predictions' / model_id
                    / f'{case_id}_brain_mask.nii.gz'
                )
                mask_object = nib.load(str(mask_path))
                mask_data = np.asanyarray(mask_object.dataobj)
                mask = mask_data > 0
                shape_ok = mask_object.shape == image_object.shape
                source_spatial_shape_ok = (
                    tuple(mask_object.shape) == tuple(case['source_shape'][:3])
                )
                affine_ok = np.allclose(
                    mask_object.affine, image_object.affine, rtol=1e-5, atol=1e-5
                )
                binary_ok = set(np.unique(mask_data)).issubset({0, 1})
                nonempty_ok = bool(mask.any() and not mask.all())
                subset_of_raw = bool(not np.any(mask & ~raw))
                mask_rsa, _ = native_to_rsa(mask, image_object.affine)
                regularity = assess_mask_regularity(
                    mask_rsa, spacing_rsa, REGULARITY_CONFIG
                )
                if not all((
                    shape_ok, source_spatial_shape_ok, affine_ok, binary_ok,
                    nonempty_ok, subset_of_raw,
                )):
                    raise ValueError(f'Validation failed for {case_id} {model_id}')
                validation_rows.append({
                    'case_id': case_id,
                    'model_id': model_id,
                    'shape_ok': shape_ok,
                    'source_spatial_shape_ok': source_spatial_shape_ok,
                    'affine_ok': affine_ok,
                    'binary_ok': binary_ok,
                    'nonempty_ok': nonempty_ok,
                    'subset_of_raw_rs2': subset_of_raw,
                    'foreground_voxels': int(mask.sum()),
                    'regularity_warning_count': len(regularity.warnings),
                    'regularity_warnings': ';'.join(regularity.warnings),
                    'max_adjacent_area_change_fraction': round(
                        regularity.max_adjacent_area_change_fraction, 6
                    ),
                    'max_centroid_step_mm': round(
                        regularity.max_centroid_step_mm, 6
                    ),
                    'surface_area_mm2': round(regularity.surface_area_mm2, 6),
                    'compactness': round(regularity.compactness, 6),
                })

        with (RESULTS / 'validation_summary.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(validation_rows[0]))
            writer.writeheader()
            writer.writerows(validation_rows)

        selected_dir = RESULTS / 'itksnap_prelabels'
        selected_dir.mkdir(parents=True, exist_ok=True)
        selected_rows = []
        for case in CASES:
            case_id = case['case_id']
            source = (
                RESULTS / 'predictions' / 'rs2_m_seam'
                / f'{case_id}_brain_mask.nii.gz'
            )
            destination = selected_dir / f'{case_id}_rs2_m_seam_mask.nii.gz'
            shutil.copy2(source, destination)
            selected_rows.append({
                'case_id': case_id,
                'source_scan_path': case['source_scan_path'],
                'source_scan_sha256': case['source_scan_sha256'],
                'prepared_input_sha256': sha256(case['image']),
                'mask_sha256': sha256(destination),
                'mask': relative(destination),
            })
        selected_manifest = RESULTS / 'itksnap_prelabels_manifest.csv'
        with selected_manifest.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(selected_rows[0]))
            writer.writeheader()
            writer.writerows(selected_rows)

        readme = (
            'Exact-TTA RS2/M-seam LYS T2w manual v1 brain-mask pre-labels\\n\\n'
            'Every mask is automatic and unapproved. Human review is mandatory.\\n'
            'The M-seam parameters were selected on T1 and are not validated on T2.\\n'
            '`predictions/rs2net_raw` preserves the immutable RS2 baseline.\\n'
            '`itksnap_prelabels` and `dataset_layout` contain the M-seam draft.\\n\\n'
            'Input handling:\\n'
            '  only manifest scan_path T2 images were read\\n'
            '  lesion masks were excluded\\n'
            '  X×Y×Z×1 scans were converted to X×Y×Z for RS2\\n'
            '  output masks are native-grid 3-D NIfTI files\\n\\n'
            'QC colors: yellow=raw RS2, cyan=M-seam, magenta=removed voxels.\\n'
            'Inspect all 18 slices and specifically check for lost superior cortex.\\n'
            'Save manual corrections as new files; never overwrite these pre-labels.\\n'
        )
        (RESULTS / 'README.txt').write_text(readme)
        run_metadata = {
            'created_at': utc_now(),
            'purpose': (
                'Exact-TTA RS2 plus transferred T1-selected M-seam drafts '
                'for LYS_T2w_manual_v1'
            ),
            'input_archive_sha256': EXPECTED_ARCHIVE_SHA256,
            'case_count': len(CASES),
            'models': MODEL_ORDER,
            'refinement_configuration': asdict(REFINEMENT_CONFIG),
            'cleanup_configuration': asdict(M_SEAM_CLEANUP_CONFIG),
            'regularity_configuration': asdict(REGULARITY_CONFIG),
            'rs2_provenance': RS2_PROVENANCE,
            'runtime': RUNTIME,
            't2_validation_status': (
                'not validated; T1-selected thresholds transferred unchanged'
            ),
            'approval_status': 'none; all outputs require human review',
        }
        (RESULTS / 'run_metadata.json').write_text(
            json.dumps(run_metadata, indent=2) + '\\n'
        )

        HANDOFF = BASE / 't2_manual_v1_rs2_m_seam_handoff'
        if HANDOFF.exists():
            shutil.rmtree(HANDOFF)
        HANDOFF.mkdir(parents=True)
        shutil.copytree(
            RESULTS / 'itksnap_prelabels', HANDOFF / 'itksnap_prelabels'
        )
        shutil.copytree(RESULTS / 'predictions', HANDOFF / 'predictions')
        shutil.copytree(RESULTS / 'qc', HANDOFF / 'qc')
        shutil.copytree(RESULTS / 'metadata', HANDOFF / 'metadata')
        diagnostics = RESULTS / 'diagnostics'
        if diagnostics.is_dir():
            shutil.copytree(diagnostics, HANDOFF / 'diagnostics')

        dataset_layout = HANDOFF / 'dataset_layout'
        for case in CASES:
            source = (
                RESULTS / 'predictions' / 'rs2_m_seam'
                / f"{case['case_id']}_brain_mask.nii.gz"
            )
            relative_scan = Path(case['source_scan_path'])
            destination = (
                dataset_layout / relative_scan.parent
                / 'scan_brain_rs2_m_seam.nii.gz'
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        for filename in (
            'README.txt',
            'input_manifest.csv',
            'input_archive_provenance.json',
            'itksnap_prelabels_manifest.csv',
            'refinement_summary.csv',
            'run_manifest.csv',
            'validation_summary.csv',
            'run_metadata.json',
        ):
            shutil.copy2(RESULTS / filename, HANDOFF / filename)

        archive_base = Path('/content/t2_manual_v1_rs2_m_seam_handoff')
        archive_path = Path(shutil.make_archive(
            str(archive_base),
            'zip',
            root_dir=HANDOFF.parent,
            base_dir=HANDOFF.name,
        ))
        print(f'Validated {len(validation_rows)} image/mask combinations.')
        print('Cases:', len(CASES))
        print(
            'Archive:', archive_path,
            f'({archive_path.stat().st_size / 1e6:.1f} MB)'
        )
        files.download(str(archive_path))
        """,
    )

    notebook["metadata"]["colab"]["name"] = OUTPUT.name
    return notebook


def main() -> None:
    notebook = build_notebook()
    OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
