#!/usr/bin/env python3
"""Build the exact-TTA RS2/M-seam Colab notebook for all converted pre-T1 cases."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE_BUILDER = ROOT / "scripts/brain_extraction/build_rs2_refinement_notebook.py"
OUTPUT = ROOT / "notebooks/brain_extraction_rs2_m_seam_all_mice_colab.ipynb"


def _load_base_notebook() -> dict:
    spec = importlib.util.spec_from_file_location("lys_rs2_notebook_builder", BASE_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load notebook builder: {BASE_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return deepcopy(module.NOTEBOOK)


def _cell(notebook: dict, cell_id: str) -> dict:
    matches = [cell for cell in notebook["cells"] if cell.get("id") == cell_id]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one notebook cell {cell_id!r}, found {len(matches)}")
    return matches[0]


def _source(notebook: dict, cell_id: str) -> str:
    return "".join(_cell(notebook, cell_id)["source"])


def _set_source(notebook: dict, cell_id: str, source: str) -> None:
    _cell(notebook, cell_id)["source"] = source.splitlines(keepends=True)


def _replace(source: str, old: str, new: str, *, label: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(
            f"Expected one {label} replacement target, found {source.count(old)}"
        )
    return source.replace(old, new)


def _replace_between(
    source: str,
    start_marker: str,
    stop_marker: str,
    replacement: str,
    *,
    label: str,
) -> str:
    start = source.find(start_marker)
    stop = source.find(stop_marker, start)
    if start < 0 or stop < 0:
        raise RuntimeError(f"Cannot locate {label} block")
    stop += len(stop_marker)
    return source[:start] + replacement + source[stop:]


def build_notebook() -> dict:
    notebook = _load_base_notebook()

    _set_source(
        notebook,
        "overview",
        """# Exact-TTA RS2 + selected M-seam masks for all converted pre-Gd T1 scans

This notebook generates **automatic, unapproved brain-mask pre-labels** for the
34 `pre_coronal.nii.gz` images packaged from `output/all_mice`.

It runs the exact reviewed RS2 source and weights on a CUDA GPU with eight-way
test-time mirroring, preserves the raw RS2 mask, and applies the selected
T1-guided M-seam plus conservative continuity cleanup. It does not run the
discarded watershed or random-walker alternatives.

## Run instructions

1. In Colab select **Runtime → Change runtime type → T4 GPU**.
2. Run the dependency-bootstrap cell. On its first run, Colab restarts once.
3. After Colab reconnects, select **Runtime → Run all**.
4. Upload `t1_brain_extraction_all_mice_34.zip` when prompted.
5. Keep the browser connected until the final result archive downloads.
6. On the Mac, use the archive's `itksnap_prelabels/` masks only as editable
   starting points. Inspect every native slice and save corrections as new files.

No automatic output is approved or valid for quantification without human review.
""",
    )

    configuration = _source(notebook, "configuration")
    configuration = _replace(
        configuration,
        "RS2_USE_TTA = True\nRUN_RANDOM_WALKER = True\n",
        (
            "RS2_USE_TTA = True\n"
            "RUN_ALTERNATIVE_REFINEMENTS = False\n"
            "RUN_RANDOM_WALKER = False\n"
            "EXPECTED_CASE_COUNT = 34\n"
            "RS2_WEIGHT_SHA256 = "
            "'f7fef315d77c8568cd6d19867445ff51587505586c19b273087b65ccf3659371'\n"
        ),
        label="all-mice configuration",
    )
    configuration = configuration.replace(
        "BASE = Path('/content/lys_brain_refinement')",
        "BASE = Path('/content/lys_all_mice_brain_masks')",
    )
    configuration = configuration.replace(
        "RESULTS = BASE / 't1_brain_extraction_rs2_refinement_results'",
        "RESULTS = BASE / 't1_brain_extraction_all_mice_rs2_m_seam_results'",
    )
    _set_source(notebook, "configuration", configuration)

    upload = _source(notebook, "upload-package")
    upload = upload.replace(
        "# Upload and unpack the already prepared frozen ten-image package.",
        "# Upload and unpack the checksummed all-mice pre-T1 package.",
    )
    upload = _replace(
        upload,
        "import csv, json, zipfile\n",
        "import csv, hashlib, json, zipfile\n",
        label="upload checksum dependency",
    )
    upload = _replace(
        upload,
        "    archive.extractall(PACKAGE_AREA)\n\nmanifests = ",
        "    archive.extractall(PACKAGE_AREA)\ndel uploaded\n\nmanifests = ",
        label="release uploaded archive bytes",
    )
    upload = _replace(
        upload,
        (
            "if len(PACKAGE_ROWS) != 10:\n"
            "    raise ValueError(f'This experiment expects exactly 10 cases, "
            "found {len(PACKAGE_ROWS)}')\n"
        ),
        (
            "case_ids = [row['case_id'] for row in PACKAGE_ROWS]\n"
            "if len(PACKAGE_ROWS) != EXPECTED_CASE_COUNT:\n"
            "    raise ValueError(\n"
            "        f'This run expects {EXPECTED_CASE_COUNT} cases, found "
            "{len(PACKAGE_ROWS)}'\n"
            "    )\n"
            "if len(case_ids) != len(set(case_ids)):\n"
            "    raise ValueError('The upload manifest contains duplicate case IDs')\n"
        ),
        label="all-mice case-count gate",
    )
    upload = _replace(
        upload,
        (
            "for row in PACKAGE_ROWS:\n"
            "    source = PACKAGE_ROOT / row['image']\n"
            "    destination = RESULTS / 'inputs' / "
            "f\"{row['case_id']}_pre_t1.nii.gz\"\n"
        ),
        (
            "for row in PACKAGE_ROWS:\n"
            "    source = PACKAGE_ROOT / row['image']\n"
            "    expected_sha256 = row.get('image_sha256', '').strip().lower()\n"
            "    if len(expected_sha256) != 64:\n"
            "        raise ValueError(f\"Missing image checksum for {row['case_id']}\")\n"
            "    observed_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()\n"
            "    if observed_sha256 != expected_sha256:\n"
            "        raise ValueError(f\"Input checksum mismatch for {row['case_id']}\")\n"
            "    destination = RESULTS / 'inputs' / "
            "f\"{row['case_id']}_pre_t1.nii.gz\"\n"
        ),
        label="uploaded image checksum gate",
    )
    _set_source(notebook, "upload-package", upload)

    install = _source(notebook, "install-rs2")
    install = _replace(
        install,
        "RS2_WEIGHT = rs2_candidates[0]\ncheckpoint_preflight = (\n",
        (
            "RS2_WEIGHT = rs2_candidates[0]\n"
            "import hashlib\n"
            "observed_weight_sha256 = hashlib.sha256(RS2_WEIGHT.read_bytes()).hexdigest()\n"
            "if observed_weight_sha256 != RS2_WEIGHT_SHA256:\n"
            "    raise RuntimeError(\n"
            "        f'RS2 weight checksum mismatch: {observed_weight_sha256}'\n"
            "    )\n"
            "print('RS2 weight checksum verified:', observed_weight_sha256)\n"
            "checkpoint_preflight = (\n"
        ),
        label="RS2 weight checksum gate",
    )
    _set_source(notebook, "install-rs2", install)

    refine = _source(notebook, "apply-refinements")
    refine = _replace(
        refine,
        "# Apply all three gated corrections to the same immutable raw prediction.",
        "# Apply the selected M-seam correction to the immutable raw RS2 prediction.",
        label="selected refinement heading",
    )
    refine = _replace_between(
        refine,
        "    watershed_mask, watershed_stats = refine_watershed(",
        "        results['rs2_random_walker'] = (walker_mask, walker_stats)\n",
        (
            "    results = {'rs2_m_seam': (seam_mask, seam_stats)}\n"
            "    if RUN_ALTERNATIVE_REFINEMENTS:\n"
            "        watershed_mask, watershed_stats = refine_watershed(\n"
            "            normalized, raw_rsa, gaps, spacing_rsa, REFINEMENT_CONFIG\n"
            "        )\n"
            "        results['rs2_marker_watershed'] = (\n"
            "            watershed_mask, watershed_stats\n"
            "        )\n"
            "        if RUN_RANDOM_WALKER:\n"
            "            with warnings.catch_warnings():\n"
            "                warnings.filterwarnings(\n"
            "                    'once', message='The probability range is outside'\n"
            "                )\n"
            "                walker_mask, walker_stats = refine_random_walker(\n"
            "                    normalized, raw_rsa, gaps, spacing_rsa,\n"
            "                    REFINEMENT_CONFIG, beta=RANDOM_WALKER_BETA\n"
            "                )\n"
            "            results['rs2_random_walker'] = (walker_mask, walker_stats)\n"
        ),
        label="discarded alternative refinements",
    )
    _set_source(notebook, "apply-refinements", refine)

    qc = _source(notebook, "qc-montages")
    qc = _replace(
        qc,
        "# Produce durable before/after montages and an interactive four-way viewer.",
        "# Produce raw-versus-M-seam montages and an interactive two-way viewer.",
        label="selected QC heading",
    )
    qc = _replace(
        qc,
        (
            "MODEL_ORDER = ['rs2net_raw', 'rs2_m_seam', 'rs2_marker_watershed']\n"
            "if RUN_RANDOM_WALKER:\n"
            "    MODEL_ORDER.append('rs2_random_walker')\n"
        ),
        (
            "MODEL_ORDER = ['rs2net_raw', 'rs2_m_seam']\n"
            "if RUN_ALTERNATIVE_REFINEMENTS:\n"
            "    MODEL_ORDER.append('rs2_marker_watershed')\n"
            "    if RUN_RANDOM_WALKER:\n"
            "        MODEL_ORDER.append('rs2_random_walker')\n"
        ),
        label="selected model order",
    )
    qc = _replace(
        qc,
        "    figure, axes = plt.subplots(2, 2, figsize=(11, 10))\n",
        (
            "    figure, axes = plt.subplots(\n"
            "        1, len(MODEL_ORDER), figsize=(5.5 * len(MODEL_ORDER), 5),\n"
            "        squeeze=False\n"
            "    )\n"
        ),
        label="two-model interactive viewer",
    )
    _set_source(notebook, "qc-montages", qc)

    summary = _source(notebook, "summary-table")
    summary = summary.replace(
        "Compare the same method across all 10 cases.",
        "Review the selected method across all 34 cases.",
    )
    _set_source(notebook, "summary-table", summary)

    final = _source(notebook, "validate-download")
    final = _replace(
        final,
        "readme = (\n",
        (
            "selected_dir = RESULTS / 'itksnap_prelabels'\n"
            "selected_dir.mkdir(parents=True, exist_ok=True)\n"
            "selected_rows = []\n"
            "for case in CASES:\n"
            "    case_id = case['case_id']\n"
            "    source = RESULTS / 'predictions' / 'rs2_m_seam' / "
            "f'{case_id}_brain_mask.nii.gz'\n"
            "    destination = selected_dir / f'{case_id}_rs2_m_seam_mask.nii.gz'\n"
            "    shutil.copy2(source, destination)\n"
            "    selected_rows.append({\n"
            "        'case_id': case_id,\n"
            "        'input_sha256': sha256(case['image']),\n"
            "        'mask_sha256': sha256(destination),\n"
            "        'mask': relative(destination),\n"
            "    })\n"
            "with (RESULTS / 'itksnap_prelabels_manifest.csv').open('w', newline='') "
            "as stream:\n"
            "    writer = csv.DictWriter(\n"
            "        stream, fieldnames=['case_id', 'input_sha256', 'mask_sha256', 'mask']\n"
            "    )\n"
            "    writer.writeheader()\n"
            "    writer.writerows(selected_rows)\n\n"
            "readme = (\n"
        ),
        label="ITK-SNAP prelabel handoff",
    )
    final = final.replace(
        "'RS2-Net T1-guided refinement experiment\\n\\n'",
        "'Exact-TTA RS2/M-seam all-mice brain-mask pre-labels\\n\\n'",
    )
    final = final.replace(
        "'`rs2net_raw` is immutable. The other folders contain experimental corrections.\\n\\n'",
        (
            "'`rs2net_raw` is immutable. `rs2_m_seam` is the selected automatic "
            "draft.\\n'\n"
            "'Use `itksnap_prelabels/` only as the source for a separate editable "
            "copy.\\n\\n'"
        ),
    )
    final = _replace_between(
        final,
        "'After downloading, review all masks with:\\n'",
        "'    ~/Downloads/t1_brain_extraction_rs2_refinement_results.zip\\n\\n'",
        (
            "'Download and extract the ITK-SNAP handoff archive on the Mac.\\n'\n"
            "    'Pair each pre-label with output/all_mice/<case>/pre_coronal.nii.gz, "
            "then save edits only to a separate manual-mask directory.\\n\\n'"
        ),
        label="local handoff instructions",
    )
    final = final.replace(
        "'purpose': 'Experimental T1-guided correction of superior skull in RS2-Net masks',",
        (
            "'purpose': 'Exact-TTA RS2 plus selected M-seam drafts for all "
            "converted pre-Gd T1 scans',"
        ),
    )
    final = final.replace(
        "'regularity_configuration': asdict(REGULARITY_CONFIG),",
        (
            "'cleanup_configuration': asdict(M_SEAM_CLEANUP_CONFIG),\n"
            "    'regularity_configuration': asdict(REGULARITY_CONFIG),"
        ),
    )
    final = _replace(
        final,
        "archive_base = Path('/content/t1_brain_extraction_rs2_refinement_results')",
        (
            "HANDOFF = BASE / 't1_brain_masks_all_mice_itksnap_handoff'\n"
            "if HANDOFF.exists():\n"
            "    shutil.rmtree(HANDOFF)\n"
            "shutil.copytree(selected_dir, HANDOFF / 'itksnap_prelabels')\n"
            "shutil.copytree(RESULTS / 'qc', HANDOFF / 'qc')\n"
            "shutil.copytree(\n"
            "    RESULTS / 'metadata' / 'rs2_m_seam',\n"
            "    HANDOFF / 'metadata' / 'rs2_m_seam',\n"
            ")\n"
            "for filename in (\n"
            "    'README.txt', 'itksnap_prelabels_manifest.csv',\n"
            "    'refinement_summary.csv', 'validation_summary.csv', "
            "'run_metadata.json',\n"
            "):\n"
            "    shutil.copy2(RESULTS / filename, HANDOFF / filename)\n\n"
            "archive_base = Path('/content/t1_brain_masks_all_mice_itksnap_handoff')"
        ),
        label="lightweight ITK-SNAP archive",
    )
    _set_source(notebook, "validate-download", final)

    notebook["metadata"]["colab"]["name"] = OUTPUT.name
    return notebook


def main() -> None:
    notebook = build_notebook()
    OUTPUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
