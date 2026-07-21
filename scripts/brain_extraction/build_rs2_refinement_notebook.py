#!/usr/bin/env python3
"""Build the self-contained RS2/T1 refinement Colab notebook.

The experimental algorithms live in ``src/lys_bbb/brain_mask_refinement.py`` so they
can be unit tested.  This builder embeds that source into the notebook because the
frozen ten-image upload archive intentionally contains data only, not a repository
checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "notebooks" / "brain_extraction_rs2_refinement_colab.ipynb"
ALGORITHM_SOURCE = (ROOT / "src" / "lys_bbb" / "brain_mask_refinement.py").read_text()


def lines(source: str) -> list[str]:
    source = dedent(source).strip("\n") + "\n"
    return source.splitlines(keepends=True)


def markdown(cell_id: str, source: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": lines(source)}


def code(cell_id: str, source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id,
        "metadata": {},
        "outputs": [],
        "source": lines(source),
    }


CELLS = [
    markdown(
        "overview",
        r"""
        # RS2-Net + T1-guided superior-skull refinement experiment

        This notebook takes the same frozen 10 pre-Gd T1 images used by the primary
        benchmark and produces four directly comparable **automatic pre-labels**:

        1. `rs2net_raw` — untouched RS2-Net output;
        2. `rs2_m_seam` — direct cut along a detected dark M-shaped superior gap;
        3. `rs2_marker_watershed` — marker-controlled watershed near that gap;
        4. `rs2_random_walker` — marker-based random walker near that gap.

        The correction methods never add foreground. They search only near the superior
        RS2 boundary and leave a slice unchanged when the image does not supply a
        sufficiently continuous dark gap. These safeguards do **not** make the masks
        ground truth: every candidate still requires visual review, especially for
        cortical under-segmentation. Non-destructive 3-D regularity checks also flag
        discontinuous area profiles, centroid jumps, isolated one-slice changes, and
        physically irregular surfaces for closer review.

        ## Run instructions

        1. In Colab choose **Runtime → Change runtime type → T4 GPU**.
        2. Run every cell in order.
        3. Upload `t1_brain_extraction_benchmark_10.zip` when prompted.
        4. Use the interactive viewer and saved montages to compare all four masks.
        5. Download `t1_brain_extraction_rs2_refinement_results.zip` from the final cell.

        The untouched RS2 mask is preserved. Correction outputs are experimental and
        separately named; nothing is silently selected as the winner.
        """,
    ),
    code(
        "configuration",
        r"""
        from pathlib import Path
        import os, shutil, subprocess, sys
        import torch

        RS2_USE_TTA = True
        RUN_RANDOM_WALKER = True
        RS2_COMMIT = '144b032df4885a3da00e0d1824fdd777b3cd304f'
        RS2_REPOSITORY = 'https://github.com/VitoLin21/Rodent-Skull-Stripping.git'
        RS2_DRIVE_FOLDER_ID = '1cTlFFGL9iTUoZOT5Rgqi2ZAyqyPlXYd-'

        BASE = Path('/content/lys_brain_refinement')
        PACKAGE_AREA = BASE / 'package'
        EXTERNAL = BASE / 'external'
        WORK = BASE / 'work'
        RESULTS = BASE / 't1_brain_extraction_rs2_refinement_results'
        for directory in (PACKAGE_AREA, EXTERNAL, WORK, RESULTS):
            directory.mkdir(parents=True, exist_ok=True)

        if not torch.cuda.is_available():
            raise RuntimeError('No GPU detected. Select Runtime → Change runtime type → T4 GPU, then rerun.')
        print('GPU:', torch.cuda.get_device_name(0))
        print('Python:', sys.version.split()[0], 'PyTorch:', torch.__version__)
        """,
    ),
    code(
        "upload-package",
        r"""
        # Upload and unpack the already prepared frozen ten-image package.
        from google.colab import files
        import csv, json, zipfile

        uploaded = files.upload()
        zip_names = [name for name in uploaded if name.lower().endswith('.zip')]
        if len(zip_names) != 1:
            raise ValueError(f'Upload exactly one .zip package; received: {list(uploaded)}')
        upload_path = Path('/content') / zip_names[0]
        if PACKAGE_AREA.exists():
            shutil.rmtree(PACKAGE_AREA)
        PACKAGE_AREA.mkdir(parents=True)
        with zipfile.ZipFile(upload_path) as archive:
            for member in archive.infolist():
                target = (PACKAGE_AREA / member.filename).resolve()
                if not target.is_relative_to(PACKAGE_AREA.resolve()):
                    raise ValueError(f'Unsafe archive path: {member.filename}')
            archive.extractall(PACKAGE_AREA)

        manifests = list(PACKAGE_AREA.rglob('benchmark_manifest.csv'))
        if len(manifests) != 1:
            raise ValueError(f'Expected one benchmark_manifest.csv, found {len(manifests)}')
        PACKAGE_ROOT = manifests[0].parent
        with manifests[0].open(newline='') as stream:
            PACKAGE_ROWS = list(csv.DictReader(stream))
        if len(PACKAGE_ROWS) != 10:
            raise ValueError(f'This experiment expects exactly 10 cases, found {len(PACKAGE_ROWS)}')

        if RESULTS.exists():
            shutil.rmtree(RESULTS)
        (RESULTS / 'inputs').mkdir(parents=True)
        CASES = []
        for row in PACKAGE_ROWS:
            source = PACKAGE_ROOT / row['image']
            destination = RESULTS / 'inputs' / f"{row['case_id']}_pre_t1.nii.gz"
            shutil.copy2(source, destination)
            CASES.append({'case_id': row['case_id'], 'image': destination})
        shutil.copy2(manifests[0], RESULTS / 'input_benchmark_manifest.csv')
        if (PACKAGE_ROOT / 'package_metadata.json').is_file():
            shutil.copy2(PACKAGE_ROOT / 'package_metadata.json', RESULTS / 'input_package_metadata.json')
        print('Cases:', ', '.join(case['case_id'] for case in CASES))
        """,
    ),
    code(
        "install-rs2",
        r"""
        # Install the known-working RS2 environment, pin its source, and fetch official weights.
        packages = [
            'monai==1.4.0', 'nibabel>=5.3,<6', 'nilearn>=0.12,<1',
            'scikit-image>=0.23,<1', 'einops>=0.8,<1', 'gdown>=5.2,<6',
            'acvl_utils==0.2.1', 'batchgenerators>=0.25,<1',
            'SimpleITK>=2.4,<3', 'tifffile', 'imageio', 'pandas', 'ipywidgets'
        ]
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', '--upgrade', *packages])
        runtime_preflight = (
            "import monai, torch; "
            "assert monai.__version__.startswith('1.4.'), monai.__version__; "
            "assert torch.cuda.is_available(), 'GPU unavailable to subprocess'; "
            "print('Runtime preflight: MONAI', monai.__version__, '| GPU', torch.cuda.get_device_name(0))"
        )
        subprocess.check_call([sys.executable, '-c', runtime_preflight])

        def clone_pinned(repository, commit, destination):
            if destination.exists():
                shutil.rmtree(destination)
            subprocess.check_call(['git', 'clone', '-q', repository, str(destination)])
            subprocess.check_call(['git', '-C', str(destination), 'checkout', '-q', commit])
            actual = subprocess.check_output(
                ['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True
            ).strip()
            if actual != commit:
                raise RuntimeError(f'Pinned checkout failed: expected {commit}, got {actual}')

        RS2_ROOT = EXTERNAL / 'Rodent-Skull-Stripping'
        clone_pinned(RS2_REPOSITORY, RS2_COMMIT, RS2_ROOT)
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', '-e', str(RS2_ROOT), '--no-deps'])

        # PyTorch >=2.6 defaults torch.load to weights_only=True. The official legacy
        # checkpoint contains NumPy metadata, so explicitly allow the trusted official file.
        RS2_PREDICT_SOURCE = RS2_ROOT / 'RS2' / 'inference' / 'predict.py'
        rs2_source = RS2_PREDICT_SOURCE.read_text()
        old_load = "torch.load(checkpoint_name, map_location=torch.device('cpu'))"
        new_load = "torch.load(checkpoint_name, map_location=torch.device('cpu'), weights_only=False)"
        if new_load not in rs2_source:
            if rs2_source.count(old_load) != 1:
                raise RuntimeError('Could not apply the pinned RS2 PyTorch compatibility patch')
            RS2_PREDICT_SOURCE.write_text(rs2_source.replace(old_load, new_load))

        model_preflight = '''
        from RS2.network.RSSNet import RSSNet
        model = RSSNet(img_size=(128, 128, 160), in_channels=1, out_channels=1, feature_size=48)
        del model
        print('RS2 model preflight passed')
        '''
        preflight_env = os.environ.copy()
        preflight_env['PYTHONPATH'] = os.pathsep.join([str(RS2_ROOT), preflight_env.get('PYTHONPATH', '')])
        subprocess.check_call([sys.executable, '-c', model_preflight], env=preflight_env)

        import gdown
        RS2_WEIGHTS_AREA = EXTERNAL / 'rs2_weights'
        RS2_WEIGHTS_AREA.mkdir(parents=True, exist_ok=True)
        if not list(RS2_WEIGHTS_AREA.rglob('*pretrained_model.pt')):
            print('Downloading official RS2-Net weights...')
            gdown.download_folder(
                id=RS2_DRIVE_FOLDER_ID, output=str(RS2_WEIGHTS_AREA),
                quiet=False, use_cookies=False
            )
        rs2_candidates = list(RS2_WEIGHTS_AREA.rglob('*pretrained_model.pt'))
        if len(rs2_candidates) != 1:
            raise FileNotFoundError(f'Expected one RS2 checkpoint, found {rs2_candidates}')
        RS2_WEIGHT = rs2_candidates[0]
        checkpoint_preflight = (
            "import torch; "
            f"checkpoint=torch.load({str(RS2_WEIGHT)!r}, map_location='cpu', weights_only=False); "
            "assert isinstance(checkpoint, dict) and 'state_dict' in checkpoint; "
            "print('RS2 checkpoint preflight: state_dict found')"
        )
        subprocess.check_call([sys.executable, '-c', checkpoint_preflight])
        """,
    ),
    code(
        "shared-helpers",
        r"""
        # Output contract, provenance, orientation, and NIfTI helpers.
        import hashlib, importlib.metadata, platform, time
        from datetime import datetime, timezone
        import nibabel as nib
        from nibabel.processing import resample_from_to
        import numpy as np

        RUN_FIELDS = ['case_id', 'model_id', 'status', 'image', 'mask', 'metadata', 'log', 'message']
        RUN_ROWS = {}

        def utc_now():
            return datetime.now(timezone.utc).isoformat(timespec='seconds')

        def sha256(path, chunk_size=1024 * 1024):
            digest = hashlib.sha256()
            with Path(path).open('rb') as stream:
                while chunk := stream.read(chunk_size):
                    digest.update(chunk)
            return digest.hexdigest()

        def relative(path):
            return str(Path(path).resolve().relative_to(RESULTS.resolve())) if path else ''

        def write_run_manifest():
            with (RESULTS / 'run_manifest.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=RUN_FIELDS)
                writer.writeheader()
                writer.writerows(RUN_ROWS[key] for key in sorted(RUN_ROWS))

        def record(case_id, model_id, status, image, mask=None, metadata=None, log=None, message=''):
            RUN_ROWS[(case_id, model_id)] = {
                'case_id': case_id, 'model_id': model_id, 'status': status,
                'image': relative(image), 'mask': relative(mask),
                'metadata': relative(metadata), 'log': relative(log), 'message': message,
            }
            write_run_manifest()

        def run_logged(command, log_path, cwd=None):
            log_path.parent.mkdir(parents=True, exist_ok=True)
            print('$', ' '.join(str(part) for part in command))
            with log_path.open('w') as log:
                process = subprocess.Popen(
                    [str(part) for part in command], cwd=cwd, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1
                )
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end='')
                    log.write(line)
                return process.wait()

        def standardize_mask(source, reference, destination):
            reference_image = nib.load(str(reference))
            mask_image = nib.load(str(source))
            resampled = False
            if mask_image.shape != reference_image.shape or not np.allclose(
                mask_image.affine, reference_image.affine, rtol=1e-5, atol=1e-5
            ):
                mask_image = resample_from_to(mask_image, reference_image, order=0)
                resampled = True
            mask = (np.asanyarray(mask_image.dataobj) > 0).astype(np.uint8)
            save_mask_like(mask, reference_image, destination)
            return {'resampled_to_input_grid': resampled, 'foreground_voxels': int(mask.sum())}

        def save_mask_like(mask, reference_image, destination):
            mask = np.asarray(mask, dtype=np.uint8)
            if mask.shape != reference_image.shape or not mask.any() or mask.all():
                raise ValueError(f'Invalid mask for {destination}: shape={mask.shape}, foreground={int(mask.sum())}')
            header = reference_image.header.copy()
            header.set_data_dtype(np.uint8)
            destination.parent.mkdir(parents=True, exist_ok=True)
            output = nib.Nifti1Image(mask, reference_image.affine, header)
            output.set_qform(reference_image.affine, code=int(reference_image.header['qform_code']))
            output.set_sform(reference_image.affine, code=int(reference_image.header['sform_code']))
            nib.save(output, destination)

        def native_to_rsa(array, affine):
            # Return array in R/S/A order and a reversible orientation record.
            codes = nib.aff2axcodes(affine)
            requested = [('R', 'L'), ('S', 'I'), ('A', 'P')]
            order = []
            flips = []
            for positive, negative in requested:
                matches = [index for index, code in enumerate(codes) if code in (positive, negative)]
                if len(matches) != 1:
                    raise ValueError(f'Cannot identify {positive}/{negative} axis from {codes}')
                axis = matches[0]
                order.append(axis)
                flips.append(codes[axis] == negative)
            oriented = np.transpose(np.asarray(array), order)
            for axis, should_flip in enumerate(flips):
                if should_flip:
                    oriented = np.flip(oriented, axis=axis)
            return oriented, {'native_axis_codes': codes, 'order': order, 'flips': flips}

        def rsa_to_native(array_rsa, orientation):
            native_ordered = np.asarray(array_rsa)
            for axis, should_flip in enumerate(orientation['flips']):
                if should_flip:
                    native_ordered = np.flip(native_ordered, axis=axis)
            return np.transpose(native_ordered, np.argsort(orientation['order']))

        RUNTIME = {
            'created_at': utc_now(), 'python': platform.python_version(),
            'pytorch': torch.__version__, 'monai': importlib.metadata.version('monai'),
            'scikit_image': importlib.metadata.version('scikit-image'),
            'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0),
        }
        RS2_PROVENANCE = {
            'repository': RS2_REPOSITORY, 'commit': RS2_COMMIT,
            'weights_url': f'https://drive.google.com/drive/folders/{RS2_DRIVE_FOLDER_ID}',
            'weight_sha256': sha256(RS2_WEIGHT), 'test_time_augmentation': RS2_USE_TTA,
            'checkpoint_compatibility': 'weights_only=False for trusted official legacy checkpoint',
        }
        """,
    ),
    code(
        "run-rs2",
        r"""
        # Run RS2-Net once. This raw prediction remains immutable.
        rs2_input = WORK / 'rs2net_inputs'
        rs2_raw = WORK / 'rs2net_outputs'
        for directory in (rs2_input, rs2_raw):
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True)
        for case in CASES:
            shutil.copy2(case['image'], rs2_input / f"{case['case_id']}_0000.nii.gz")

        batch_log = RESULTS / 'logs' / 'rs2net_raw' / 'rs2net_batch.log'
        command = [
            'RS2_predict', '-i', str(rs2_input), '-o', str(rs2_raw),
            '-m', str(RS2_WEIGHT), '-device', 'cuda', '-npp', '1', '-nps', '1',
        ]
        if not RS2_USE_TTA:
            command.append('--disable_tta')
        started = time.monotonic()
        returncode = run_logged(command, batch_log, cwd=RS2_ROOT)
        elapsed = round(time.monotonic() - started, 3)

        for case in CASES:
            case_id, image = case['case_id'], case['image']
            mask = RESULTS / 'predictions' / 'rs2net_raw' / f'{case_id}_brain_mask.nii.gz'
            metadata = RESULTS / 'metadata' / 'rs2net_raw' / f'{case_id}.json'
            metadata.parent.mkdir(parents=True, exist_ok=True)
            candidates = [rs2_raw / f'{case_id}.nii.gz', rs2_raw / f'{case_id}_0000.nii.gz']
            source = next((path for path in candidates if path.is_file()), None)
            try:
                if source is None:
                    raise FileNotFoundError(f'RS2-Net did not create an output; batch status {returncode}')
                standard = standardize_mask(source, image, mask)
                payload = {
                    'case_id': case_id, 'model_id': 'rs2net_raw', 'status': 'ok',
                    'role': 'immutable automatic pre-label', 'input': relative(image),
                    'output': relative(mask), 'preprocessing': 'official RS2 DefaultPreprocessor',
                    'batch_command': command, 'batch_runtime_seconds': elapsed,
                    'input_sha256': sha256(image), 'mask_sha256': sha256(mask),
                    **standard, **RS2_PROVENANCE, **RUNTIME,
                }
                metadata.write_text(json.dumps(payload, indent=2) + '\n')
                record(case_id, 'rs2net_raw', 'ok', image, mask, metadata, batch_log)
            except Exception as exc:
                message = f'{type(exc).__name__}: {exc}'
                record(case_id, 'rs2net_raw', 'failed', image, log=batch_log, message=message)
                print(f'FAILED {case_id}: {message}')

        failures = [row for row in RUN_ROWS.values() if row['model_id'] == 'rs2net_raw' and row['status'] != 'ok']
        if failures:
            raise RuntimeError(f'Raw RS2 prediction failed for {len(failures)} cases; stop before refinement.')
        print('Raw RS2 masks ready:', len(CASES))
        """,
    ),
    code("refinement-algorithms", ALGORITHM_SOURCE),
    code(
        "apply-refinements",
        r"""
        # Apply all three gated corrections to the same immutable raw prediction.
        from dataclasses import asdict
        import warnings

        REFINEMENT_CONFIG = GapRefinementConfig(
            max_search_depth_mm=2.8,
            min_cap_thickness_mm=0.30,
            valley_window_mm=0.32,
            line_smoothing_mm=0.10,
            min_valley_contrast=0.10,
            min_confident_width_fraction=0.22,
            central_fraction=0.75,
            max_column_jump_mm=0.55,
            seed_margin_mm=0.24,
            min_slice_removed_fraction=0.01,
            max_slice_removed_fraction=0.35,
            min_corrected_slices=3,
        )
        RANDOM_WALKER_BETA = 180.0
        REGULARITY_CONFIG = MaskRegularityConfig()
        M_SEAM_CLEANUP_CONFIG = MSeamCleanupConfig()
        METHOD_DESCRIPTIONS = {
            'rs2_m_seam': (
                'Direct removal superior to a detected dark M-shaped line plus conservative '
                'in-plane-island and short-run continuity cleanup'
            ),
            'rs2_marker_watershed': 'Marker-controlled watershed on the local T1 gradient',
            'rs2_random_walker': 'Marker-based random walker on local T1 intensity',
        }
        REFINEMENT_CACHE = {}
        SUMMARY_ROWS = []

        for case_index, case in enumerate(CASES, start=1):
            case_id, image_path = case['case_id'], case['image']
            print(f'[{case_index}/{len(CASES)}] Refining {case_id}')
            image_object = nib.load(str(image_path))
            raw_path = RESULTS / 'predictions' / 'rs2net_raw' / f'{case_id}_brain_mask.nii.gz'
            raw_native = np.asanyarray(nib.load(str(raw_path)).dataobj) > 0
            image_native = np.asanyarray(image_object.dataobj).astype(np.float32)
            image_rsa, orientation = native_to_rsa(image_native, image_object.affine)
            raw_rsa, mask_orientation = native_to_rsa(raw_native, image_object.affine)
            if orientation != mask_orientation:
                raise RuntimeError(f'Image/mask orientation mismatch for {case_id}')
            native_spacing = tuple(float(value) for value in image_object.header.get_zooms()[:3])
            spacing_rsa = tuple(native_spacing[axis] for axis in orientation['order'])
            normalized = robust_normalize(image_rsa, raw_rsa)
            gaps = detect_gap_volume(normalized, raw_rsa, spacing_rsa, REFINEMENT_CONFIG)
            raw_regularity = assess_mask_regularity(raw_rsa, spacing_rsa, REGULARITY_CONFIG)
            raw_metadata_path = RESULTS / 'metadata' / 'rs2net_raw' / f'{case_id}.json'
            raw_metadata = json.loads(raw_metadata_path.read_text())
            raw_metadata['regularity_qc'] = raw_regularity.to_dict()
            raw_metadata_path.write_text(json.dumps(raw_metadata, indent=2) + '\n')

            seam_before_cleanup, seam_stats = refine_direct_seam(
                raw_rsa, gaps, REFINEMENT_CONFIG
            )
            seam_mask, seam_cleanup = stabilize_m_seam_mask(
                seam_before_cleanup, raw_rsa, spacing_rsa, M_SEAM_CLEANUP_CONFIG
            )
            seam_stats['continuity_cleanup'] = seam_cleanup.to_dict()
            seam_stats['output_foreground_voxels'] = int(np.count_nonzero(seam_mask))
            seam_stats['removed_voxels'] = int(
                np.count_nonzero(raw_rsa) - np.count_nonzero(seam_mask)
            )
            seam_stats['removed_fraction'] = (
                seam_stats['removed_voxels'] / np.count_nonzero(raw_rsa)
            )
            watershed_mask, watershed_stats = refine_watershed(
                normalized, raw_rsa, gaps, spacing_rsa, REFINEMENT_CONFIG
            )
            results = {
                'rs2_m_seam': (seam_mask, seam_stats),
                'rs2_marker_watershed': (watershed_mask, watershed_stats),
            }
            if RUN_RANDOM_WALKER:
                with warnings.catch_warnings():
                    warnings.filterwarnings('once', message='The probability range is outside')
                    walker_mask, walker_stats = refine_random_walker(
                        normalized, raw_rsa, gaps, spacing_rsa,
                        REFINEMENT_CONFIG, beta=RANDOM_WALKER_BETA
                    )
                results['rs2_random_walker'] = (walker_mask, walker_stats)

            surface_rsa = np.zeros_like(raw_rsa, dtype=np.uint8)
            for z, gap in enumerate(gaps):
                if not gap.valid:
                    continue
                for x in range(gap.x_start, gap.x_stop):
                    if np.isfinite(gap.seam[x]):
                        surface_rsa[x, int(round(float(gap.seam[x]))), z] = 1
            surface_native = rsa_to_native(surface_rsa, orientation).astype(np.uint8)
            surface_path = RESULTS / 'diagnostics' / 'detected_gap' / f'{case_id}_detected_gap.nii.gz'
            if surface_native.any():
                save_mask_like(surface_native, image_object, surface_path)
            else:
                surface_path = None

            REFINEMENT_CACHE[case_id] = {
                'image_rsa': image_rsa, 'raw_rsa': raw_rsa, 'gaps': gaps,
                'spacing_rsa': spacing_rsa, 'orientation': orientation, 'results': results,
                'raw_regularity': raw_regularity,
            }
            for model_id, (candidate_rsa, stats) in results.items():
                regularity = assess_mask_regularity(
                    candidate_rsa, spacing_rsa, REGULARITY_CONFIG
                )
                stats['regularity_qc'] = regularity.to_dict()
                candidate_native = rsa_to_native(candidate_rsa, orientation).astype(np.uint8)
                output_path = RESULTS / 'predictions' / model_id / f'{case_id}_brain_mask.nii.gz'
                save_mask_like(candidate_native, image_object, output_path)
                removed_native = raw_native & ~candidate_native.astype(bool)
                removed_path = RESULTS / 'diagnostics' / 'removed' / model_id / f'{case_id}_removed_mask.nii.gz'
                if removed_native.any():
                    save_mask_like(removed_native, image_object, removed_path)
                else:
                    removed_path = None

                metadata_path = RESULTS / 'metadata' / model_id / f'{case_id}.json'
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    'case_id': case_id, 'model_id': model_id, 'status': 'ok',
                    'role': 'experimental automatic pre-label; human review required',
                    'description': METHOD_DESCRIPTIONS[model_id],
                    'input': relative(image_path), 'source_mask': relative(raw_path),
                    'output': relative(output_path),
                    'detected_gap': relative(surface_path) if surface_path else '',
                    'removed_mask': relative(removed_path) if removed_path else '',
                    'orientation_record': {
                        'native_axis_codes': list(orientation['native_axis_codes']),
                        'rsa_axis_order': orientation['order'], 'flips': orientation['flips'],
                    },
                    'input_sha256': sha256(image_path), 'source_mask_sha256': sha256(raw_path),
                    'mask_sha256': sha256(output_path), 'refinement_statistics': stats,
                    'scientific_warning': 'Candidate only; not approved and not valid for quantification without review.',
                    **RS2_PROVENANCE, **RUNTIME,
                }
                metadata_path.write_text(json.dumps(payload, indent=2) + '\n')
                record(case_id, model_id, 'ok', image_path, output_path, metadata_path)
                SUMMARY_ROWS.append({
                    'case_id': case_id, 'method': model_id, 'status': stats['status'],
                    'detected_gap_slices': len(stats['detected_gap_slices']),
                    'corrected_slices': len(stats['corrected_slices']),
                    'removed_voxels': stats['removed_voxels'],
                    'removed_percent': round(100.0 * stats['removed_fraction'], 3),
                    'slice_errors': len(stats.get('slice_errors', {})),
                    'regularity_warning_count': len(regularity.warnings),
                    'regularity_warnings': ';'.join(regularity.warnings),
                    'one_slice_outliers': len(regularity.one_slice_outlier_slices),
                    'max_centroid_step_mm': round(regularity.max_centroid_step_mm, 4),
                    'surface_area_mm2': round(regularity.surface_area_mm2, 4),
                })

        with (RESULTS / 'refinement_summary.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(SUMMARY_ROWS[0]))
            writer.writeheader()
            writer.writerows(SUMMARY_ROWS)
        print('Refinement candidates ready:', len(SUMMARY_ROWS))
        """,
    ),
    code(
        "qc-montages",
        r"""
        # Produce durable before/after montages and an interactive four-way viewer.
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        from IPython.display import display
        import ipywidgets as widgets

        MODEL_ORDER = ['rs2net_raw', 'rs2_m_seam', 'rs2_marker_watershed']
        if RUN_RANDOM_WALKER:
            MODEL_ORDER.append('rs2_random_walker')
        MODEL_TITLES = {
            'rs2net_raw': 'Raw RS2-Net',
            'rs2_m_seam': 'M-seam cut',
            'rs2_marker_watershed': 'Marker watershed',
            'rs2_random_walker': 'Random walker',
        }

        def case_arrays(case_id):
            cache = REFINEMENT_CACHE[case_id]
            arrays = {'rs2net_raw': cache['raw_rsa']}
            arrays.update({key: value[0] for key, value in cache['results'].items()})
            return cache['image_rsa'], arrays

        def display_limits(image, raw):
            values = image[raw & np.isfinite(image)]
            return tuple(np.percentile(values, (1, 99)))

        def informative_slices(raw, arrays, count=5):
            removed = np.zeros_like(raw, dtype=bool)
            for key, candidate in arrays.items():
                if key != 'rs2net_raw':
                    removed |= raw & ~candidate
            score = removed.sum(axis=(0, 1))
            choices = []
            for z in np.argsort(score)[::-1]:
                if score[z] == 0:
                    break
                if all(abs(int(z) - other) >= 8 for other in choices):
                    choices.append(int(z))
                if len(choices) == count:
                    break
            occupied = np.flatnonzero(raw.any(axis=(0, 1)))
            fallback = np.linspace(occupied[0], occupied[-1], count + 2, dtype=int)[1:-1]
            for z in fallback:
                if all(abs(int(z) - other) >= 5 for other in choices):
                    choices.append(int(z))
                if len(choices) == count:
                    break
            return sorted(choices[:count])

        qc_dir = RESULTS / 'qc'
        qc_dir.mkdir(parents=True, exist_ok=True)
        for case in CASES:
            case_id = case['case_id']
            image_rsa, arrays = case_arrays(case_id)
            raw = arrays['rs2net_raw']
            slices = informative_slices(raw, arrays)
            low, high = display_limits(image_rsa, raw)
            figure, axes = plt.subplots(
                len(MODEL_ORDER), len(slices), figsize=(3.2 * len(slices), 3.2 * len(MODEL_ORDER)),
                squeeze=False
            )
            for row, model_id in enumerate(MODEL_ORDER):
                candidate = arrays[model_id]
                for column, z in enumerate(slices):
                    axis = axes[row, column]
                    axis.imshow(image_rsa[:, :, z].T, origin='lower', cmap='gray', vmin=low, vmax=high)
                    axis.contour(raw[:, :, z].T, levels=[0.5], colors='yellow', linewidths=0.7)
                    if model_id != 'rs2net_raw':
                        removed = raw[:, :, z] & ~candidate[:, :, z]
                        axis.imshow(
                            np.ma.masked_where(~removed.T, removed.T), origin='lower',
                            cmap=ListedColormap(['magenta']), alpha=0.45, vmin=0, vmax=1
                        )
                        axis.contour(candidate[:, :, z].T, levels=[0.5], colors='cyan', linewidths=0.9)
                    axis.set_title(f'{MODEL_TITLES[model_id]} | coronal {z}')
                    axis.axis('off')
            figure.suptitle(
                f'{case_id}: yellow=raw RS2, cyan=corrected boundary, magenta=removed', fontsize=13
            )
            figure.tight_layout()
            output = qc_dir / f'{case_id}_rs2_refinement_comparison.png'
            figure.savefig(output, dpi=150, bbox_inches='tight')
            plt.close(figure)
        print(f'Created {len(CASES)} QC montages in {qc_dir}')

        def show_case(case_id, coronal_slice):
            image_rsa, arrays = case_arrays(case_id)
            z = min(int(coronal_slice), image_rsa.shape[2] - 1)
            raw = arrays['rs2net_raw']
            low, high = display_limits(image_rsa, raw)
            figure, axes = plt.subplots(2, 2, figsize=(11, 10))
            for axis, model_id in zip(axes.ravel(), MODEL_ORDER):
                candidate = arrays[model_id]
                axis.imshow(image_rsa[:, :, z].T, origin='lower', cmap='gray', vmin=low, vmax=high)
                axis.contour(raw[:, :, z].T, levels=[0.5], colors='yellow', linewidths=0.8)
                if model_id != 'rs2net_raw':
                    removed = raw[:, :, z] & ~candidate[:, :, z]
                    axis.imshow(
                        np.ma.masked_where(~removed.T, removed.T), origin='lower',
                        cmap=ListedColormap(['magenta']), alpha=0.45, vmin=0, vmax=1
                    )
                    axis.contour(candidate[:, :, z].T, levels=[0.5], colors='cyan', linewidths=1.0)
                axis.set_title(MODEL_TITLES[model_id])
                axis.axis('off')
            figure.suptitle(
                f'{case_id} | coronal slice {z} | yellow raw, cyan corrected, magenta removed'
            )
            figure.tight_layout()
            plt.show()

        max_slices = max(REFINEMENT_CACHE[case['case_id']]['image_rsa'].shape[2] for case in CASES)
        case_widget = widgets.Dropdown(
            options=[case['case_id'] for case in CASES], description='Case:'
        )
        slice_widget = widgets.IntSlider(
            value=min(125, max_slices - 1), min=0, max=max_slices - 1,
            step=1, description='Coronal:', continuous_update=False
        )
        display(widgets.HBox([case_widget, slice_widget]))
        display(widgets.interactive_output(
            show_case, {'case_id': case_widget, 'coronal_slice': slice_widget}
        ))
        """,
    ),
    code(
        "summary-table",
        r"""
        # Review the extent of every proposed correction before downloading.
        import pandas as pd

        summary = pd.DataFrame(SUMMARY_ROWS).sort_values(['case_id', 'method'])
        display(summary)
        print('\nInterpretation:')
        print('- unchanged_no_confident_correction means the image-based safety gate retained raw RS2.')
        print('- A large removed percentage is not automatically good; inspect the cortex for under-segmentation.')
        print('- Regularity warnings prioritize review; they do not reject, repair, or approve a mask.')
        print('- Compare the same method across all 10 cases. Do not select a method from one attractive slice.')
        print('- These outputs are automatic candidates, not reviewed masks and not quantification inputs.')
        """,
    ),
    code(
        "validate-download",
        r"""
        # Validate grids/subset behavior, record the experiment, and download one archive.
        validation_rows = []
        for case in CASES:
            case_id, image_path = case['case_id'], case['image']
            image_object = nib.load(str(image_path))
            image_native = np.asanyarray(image_object.dataobj)
            _, orientation = native_to_rsa(image_native, image_object.affine)
            native_spacing = tuple(float(value) for value in image_object.header.get_zooms()[:3])
            spacing_rsa = tuple(native_spacing[axis] for axis in orientation['order'])
            raw_path = RESULTS / 'predictions' / 'rs2net_raw' / f'{case_id}_brain_mask.nii.gz'
            raw_object = nib.load(str(raw_path))
            raw = np.asanyarray(raw_object.dataobj) > 0
            for model_id in MODEL_ORDER:
                mask_path = RESULTS / 'predictions' / model_id / f'{case_id}_brain_mask.nii.gz'
                mask_object = nib.load(str(mask_path))
                mask = np.asanyarray(mask_object.dataobj) > 0
                shape_ok = mask_object.shape == image_object.shape
                affine_ok = np.allclose(mask_object.affine, image_object.affine, rtol=1e-5, atol=1e-5)
                binary_ok = set(np.unique(np.asanyarray(mask_object.dataobj))).issubset({0, 1})
                nonempty_ok = bool(mask.any() and not mask.all())
                subset_of_raw = bool(not np.any(mask & ~raw))
                mask_rsa, _ = native_to_rsa(mask, image_object.affine)
                regularity = assess_mask_regularity(
                    mask_rsa, spacing_rsa, REGULARITY_CONFIG
                )
                if not all((shape_ok, affine_ok, binary_ok, nonempty_ok, subset_of_raw)):
                    raise ValueError(f'Validation failed for {case_id} {model_id}')
                validation_rows.append({
                    'case_id': case_id, 'model_id': model_id, 'shape_ok': shape_ok,
                    'affine_ok': affine_ok, 'binary_ok': binary_ok,
                    'nonempty_ok': nonempty_ok, 'subset_of_raw_rs2': subset_of_raw,
                    'foreground_voxels': int(mask.sum()),
                    'regularity_warning_count': len(regularity.warnings),
                    'regularity_warnings': ';'.join(regularity.warnings),
                    'max_adjacent_area_change_fraction': round(
                        regularity.max_adjacent_area_change_fraction, 6
                    ),
                    'max_centroid_step_mm': round(regularity.max_centroid_step_mm, 6),
                    'surface_area_mm2': round(regularity.surface_area_mm2, 6),
                    'compactness': round(regularity.compactness, 6),
                })

        with (RESULTS / 'validation_summary.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(validation_rows[0]))
            writer.writeheader()
            writer.writerows(validation_rows)

        readme = (
            'RS2-Net T1-guided refinement experiment\n\n'
            'Every mask in this archive is an automatic pre-label. Human review is mandatory.\n'
            '`rs2net_raw` is immutable. The other folders contain experimental corrections.\n\n'
            'QC colors:\n'
            '  yellow  raw RS2 boundary\n'
            '  cyan    corrected boundary\n'
            '  magenta voxels removed from raw RS2\n\n'
            'After downloading, review all masks with:\n'
            '  conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \\\n'
            '    ~/Downloads/t1_brain_extraction_rs2_refinement_results.zip\n\n'
            'Inspect the full anterior-posterior extent and specifically check for lost superior cortex.\n'
            'Regularity warnings are review aids only; they do not approve or repair a mask.\n'
            'Do not use an automatic candidate for quantification until it has been accepted or corrected.\n'
        )
        (RESULTS / 'README.txt').write_text(readme)
        run_metadata = {
            'created_at': utc_now(),
            'purpose': 'Experimental T1-guided correction of superior skull in RS2-Net masks',
            'case_count': len(CASES), 'models': MODEL_ORDER,
            'refinement_configuration': asdict(REFINEMENT_CONFIG),
            'regularity_configuration': asdict(REGULARITY_CONFIG),
            'random_walker_enabled': RUN_RANDOM_WALKER,
            'random_walker_beta': RANDOM_WALKER_BETA if RUN_RANDOM_WALKER else None,
            'rs2_provenance': RS2_PROVENANCE, 'runtime': RUNTIME,
            'approval_status': 'none; all outputs require human review',
        }
        (RESULTS / 'run_metadata.json').write_text(json.dumps(run_metadata, indent=2) + '\n')

        archive_base = Path('/content/t1_brain_extraction_rs2_refinement_results')
        archive_path = Path(shutil.make_archive(
            str(archive_base), 'zip', root_dir=RESULTS.parent, base_dir=RESULTS.name
        ))
        print(f'Validated {len(validation_rows)} image/mask combinations.')
        print('Archive:', archive_path, f'({archive_path.stat().st_size / 1e6:.1f} MB)')
        files.download(str(archive_path))
        """,
    ),
]


NOTEBOOK = {
    "cells": CELLS,
    "metadata": {
        "accelerator": "GPU",
        "colab": {"gpuType": "T4", "provenance": []},
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}


def main() -> None:
    OUTPUT.write_text(json.dumps(NOTEBOOK, indent=1, ensure_ascii=False) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
