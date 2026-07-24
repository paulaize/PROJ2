# LYS BBB independent functionality demonstration commands

This cookbook contains paste-ready examples for the most useful independent parts of
LYS BBB. It uses the existing `lys-bbb` conda environment and real files already present
on this Mac. Commands that produce outputs write only below a new directory in
`/private/tmp`; they do not modify raw MRI data, the mounted study, approved masks, or
immutable artifacts.

The external test study is expected at:

```text
/Volumes/Untitled/test_study/mouse-mri-study
```

On 2026-07-23, `Untitled` was not mounted. Sections that use the persistent study begin
with an explicit mount check and must wait until the disk is connected. They query the
study database for managed paths instead of guessing a T2 file or subject pairing.

## Safety and workload labels

| Label | Meaning |
|---|---|
| **READ-ONLY** | Inspects existing files or state and creates nothing. |
| **TEMP OUTPUT** | Writes only under the unique `/private/tmp` demo directory. |
| **GUI** | Opens the real application or ITK-SNAP; approval remains a human action. |
| **COMPUTE** | Runs inference or registration and may temporarily make the Mac busy. |

Automatic T1 and T2 masks are drafts. Command completion is not approval. Transitional
T1 quantification below is demonstration output, not a scientifically approved study
result.

## 0. Start one demonstration terminal

Run this block once in a fresh Terminal window. Keep that terminal open so the variables
remain available to later sections.

```bash
export LYS_PROJ2="/Users/paul-andreaslaize/Documents/LYS_PROJ2"
export LYS_TEST_STUDY="/Volumes/Untitled/test_study/mouse-mri-study"
export LYS_T1_RELEASE="$HOME/Library/Application Support/LYS BBB/models/rs2net-m-seam-v1"
export LYS_T2_RELEASE="$HOME/Downloads/LYS_v1_RatLesNetV2_mac_inference"
export LYS_DEMO_ROOT="/private/tmp/lys_bbb_demo_$(date +%Y%m%d_%H%M%S)"

cd "$LYS_PROJ2"
mkdir -p "$LYS_DEMO_ROOT"
printf 'Demo outputs: %s\n' "$LYS_DEMO_ROOT"
```

All repository-relative commands below assume the terminal is still in `LYS_PROJ2`.

## 1. Verify the installed runtime

**READ-ONLY.** Show the Python/scientific runtime and whether MPS is available from the
normal Terminal session:

```bash
conda run -n lys-bbb python -c "import sys, torch, PySide6, nibabel, numpy; print('python', sys.version.split()[0]); print('torch', torch.__version__); print('MPS available', torch.backends.mps.is_available()); print('PySide6', PySide6.__version__); print('nibabel', nibabel.__version__); print('numpy', numpy.__version__)"
```

Show the installed native ANTs version:

```bash
conda run -n lys-bbb antsRegistration --version
```

Show the three installed LYS BBB interfaces:

```bash
conda run -n lys-bbb lys-bbb-desktop --help
conda run -n lys-bbb lys-bbb-t1-mask --help
conda run -n lys-bbb lys-bbb-t2-infer --help
```

Expected ANTs version for the current method contracts: `2.6.5`.

## 2. Validate the immutable model releases

### 2.1 T1 RS2-Net/M-seam release

**READ-ONLY.** This checks the manifest, reviewed source commit, clean source checkout,
and exact model-weight checksum:

```bash
conda run -n lys-bbb python -c "from pathlib import Path; from lys_bbb.t1_brain_mask_release import validate_t1_brain_mask_release; r=validate_t1_brain_mask_release(Path.home()/'Library/Application Support/LYS BBB/models/rs2net-m-seam-v1'); print('release:', r.id); print('source commit:', r.source_commit); print('weights SHA-256:', r.weights_sha256); print('release TTA declaration:', r.test_time_augmentation)"
```

The release declares the reviewed exact-TTA source contract. The desktop's interactive
execution is separately recorded as `explicit_no_tta_local_draft`.

### 2.2 T2 RatLesNetV2 release

**READ-ONLY.** This verifies the frozen specifications, threshold record, runtime source,
and all five model checksums:

```bash
conda run -n lys-bbb python -c "from pathlib import Path; from lys_bbb.t2_model_release import validate_frozen_t2_model_release; r=validate_frozen_t2_model_release(Path.home()/'Downloads/LYS_v1_RatLesNetV2_mac_inference'); print('release:', r.id); print('models:', len(r.model_paths)); print('threshold:', r.threshold); print('spacing:', r.expected_spacing_mm); print('ensemble:', r.metadata['ensemble'])"
```

## 3. Open and inspect the persistent test study

### 3.1 Confirm that the external study is mounted

**READ-ONLY.** Do not continue with mounted-study commands if this fails:

```bash
test -f "$LYS_TEST_STUDY/project.sqlite" && printf 'Study available: %s\n' "$LYS_TEST_STUDY"
```

If it prints nothing and returns an error, reconnect or mount the `Untitled` disk first.

### 3.2 Launch the existing PySide6 application

**GUI.** This opens the actual study; it does not create a second application:

```bash
conda run --no-capture-output -n lys-bbb lys-bbb-desktop "$LYS_TEST_STUDY"
```

The application is the authoritative demonstration for persistent import, draft jobs,
review, immutable approval, invalidation, T1 registration/enhancement, T2 lesion volume,
and atlas mapping. Close and reopen with the same command to demonstrate persistence.

### 3.3 Inspect subjects and active inputs directly

**READ-ONLY.** Run this from a second Terminal while the app is closed or idle:

```bash
sqlite3 -header -column "$LYS_TEST_STUDY/project.sqlite" \
  "SELECT s.subject_code, i.role, i.state, i.validation_state, i.version, i.output_path
   FROM scan_inputs AS i
   JOIN subjects AS s ON s.id = i.subject_id
   WHERE i.active = 1
   ORDER BY s.subject_code, i.role;"
```

Summarize durable T2 and T1-mask job states:

```bash
sqlite3 -header -column "$LYS_TEST_STUDY/project.sqlite" \
  "SELECT 'T2' AS workflow, state, COUNT(*) AS jobs FROM jobs GROUP BY state
   UNION ALL
   SELECT 'T1_MASK', state, COUNT(*) FROM t1_brain_mask_jobs GROUP BY state
   ORDER BY workflow, state;"
```

These SQL calls are diagnostic only. Never update the SQLite database manually.

## 4. Inspect real local NIfTI geometry

The primary local example is the real converted pre-Gd T1 used during the earlier
`C23S3_D1_bis` smoke work:

[C23S3_D1_bis pre-Gd T1](../output/all_mice/C23S3_D1_bis/pre_coronal.nii.gz)

**READ-ONLY.** Report shape, spacing, orientation, qform/sform codes, physical extent,
determinant, and handedness using the production atlas geometry validator:

```bash
conda run --no-capture-output -n lys-bbb python - <<'PY'
from pathlib import Path
from lys_bbb.atlas_release import inspect_nifti_geometry

path = Path("/Users/paul-andreaslaize/Documents/LYS_PROJ2/output/all_mice/C23S3_D1_bis/pre_coronal.nii.gz")
geometry = inspect_nifti_geometry(path)
print("path:", path)
print("shape:", geometry.shape)
print("spacing mm:", geometry.spacing_mm)
print("orientation:", geometry.orientation)
print("qform/sform:", geometry.qform_code, geometry.sform_code)
print("physical extent mm:", geometry.physical_extent_mm)
print("determinant:", geometry.determinant)
print("handedness:", geometry.handedness)
PY
```

Compute an input checksum without changing the file:

```bash
shasum -a 256 "$LYS_PROJ2/output/all_mice/C23S3_D1_bis/pre_coronal.nii.gz"
```

## 5. Generate one low-impact T1 brain-mask draft

**TEMP OUTPUT + COMPUTE.** This is the same explicit no-TTA variant selected for the
desktop. It uses one model pass, limits CPU helper threads, lowers CPU scheduling
priority, and writes a new disposable output directory. MPS itself cannot be capped to a
fixed percentage, so the Mac may still become busy for roughly one to two minutes.

```bash
env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2 \
  nice -n 10 \
  conda run --no-capture-output -n lys-bbb lys-bbb-t1-mask \
    --release "$LYS_T1_RELEASE" \
    --input "$LYS_PROJ2/output/all_mice/C23S3_D1_bis/pre_coronal.nii.gz" \
    --output "$LYS_DEMO_ROOT/t1_mask_C23S3_D1_bis" \
    --case-id C23S3_D1_bis \
    --device auto \
    --disable-tta
```

Inspect the generated provenance and files:

```bash
conda run -n lys-bbb python -m json.tool \
  "$LYS_DEMO_ROOT/t1_mask_C23S3_D1_bis/metadata.json"

find "$LYS_DEMO_ROOT/t1_mask_C23S3_D1_bis" -maxdepth 3 -type f -print

open "$LYS_DEMO_ROOT/t1_mask_C23S3_D1_bis/qc/draft_mask_qc.png"
```

The metadata must report:

```text
test_time_augmentation: false
generation_variant: explicit_no_tta_local_draft
human_review_required: true
```

Do not run several animals concurrently on this 8 GB Mac. Exact eight-way TTA is
intentionally omitted from the normal demonstration because it previously made this Mac
unusable and took approximately seven minutes for one case.

## 6. Demonstrate safe manual mask review in ITK-SNAP

This uses a real local testing mask but copies it before opening the editor:

- [C23S5_D1 pre-Gd T1](../output/all_mice/C23S5_D1/pre_coronal.nii.gz)
- [C23S5_D1 testing mask](../derivatives/brain_seg/manual_test_cleaned/C23S5_D1.nii.gz)

**TEMP OUTPUT + GUI.** The original mask remains unchanged:

```bash
mkdir -p "$LYS_DEMO_ROOT/manual_review_C23S5_D1"
cp "$LYS_PROJ2/derivatives/brain_seg/manual_test_cleaned/C23S5_D1.nii.gz" \
  "$LYS_DEMO_ROOT/manual_review_C23S5_D1/editable_mask.nii.gz"

/Applications/ITK-SNAP.app/Contents/bin/itksnap \
  -g "$LYS_PROJ2/output/all_mice/C23S5_D1/pre_coronal.nii.gz" \
  -s "$LYS_DEMO_ROOT/manual_review_C23S5_D1/editable_mask.nii.gz"
```

Saving in ITK-SNAP changes only the disposable copy. This command demonstrates editing,
not application approval; use the app Reviews queue for a managed approval.

## 7. Validate existing candidate T1 masks and create QC

**TEMP OUTPUT.** This scans the real converted cohort, finds the available
`manual_test_cleaned` masks, validates their native grids and binary labels, and writes a
new manifest/QC bundle under the demo directory:

```bash
conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --input-root "$LYS_PROJ2/output/all_mice" \
  --mask-dir "$LYS_PROJ2/derivatives/brain_seg/manual_test_cleaned" \
  --mask-pattern '{case_id}.nii.gz' \
  --mask-source manual_test_cleaned_demo \
  --registration-summary "$LYS_PROJ2/reports/qc/registration_all_mice/registration_qc_summary.csv" \
  --out-dir "$LYS_DEMO_ROOT/brain_mask_validation"
```

Inspect the summary and manifest:

```bash
conda run -n lys-bbb python -m json.tool \
  "$LYS_DEMO_ROOT/brain_mask_validation/brain_mask_manifest_summary.json"

open "$LYS_DEMO_ROOT/brain_mask_validation/brain_mask_manifest.csv"
```

These masks are explicitly testing/non-final inputs. Passing technical validation does
not approve them.

## 8. Generate post-to-pre registration QC for one real T1 pair

This builds a disposable one-case input view with symbolic links; the converted source
images remain unchanged.

**TEMP OUTPUT + COMPUTE.** Registration is CPU-heavy but much lighter than model
training:

```bash
mkdir -p "$LYS_DEMO_ROOT/registration_input/C23S5_D1"
ln -s "$LYS_PROJ2/output/all_mice/C23S5_D1/pre_coronal.nii.gz" \
  "$LYS_DEMO_ROOT/registration_input/C23S5_D1/pre_coronal.nii.gz"
ln -s "$LYS_PROJ2/output/all_mice/C23S5_D1/post_coronal.nii.gz" \
  "$LYS_DEMO_ROOT/registration_input/C23S5_D1/post_coronal.nii.gz"

env OMP_NUM_THREADS=2 ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=2 \
  nice -n 10 \
  conda run -n lys-bbb python scripts/qc/qc_pre_post_registration.py \
    --input-root "$LYS_DEMO_ROOT/registration_input" \
    --out-dir "$LYS_DEMO_ROOT/registration_qc" \
    --n-slices 9
```

Open the generated montage and summary:

```bash
open "$LYS_DEMO_ROOT/registration_qc/C23S5_D1/C23S5_D1_registration_qc.png"
open "$LYS_DEMO_ROOT/registration_qc/registration_qc_summary.csv"
```

This transitional QC script is useful for method diagnostics. It is not a substitute
for the durable app registration artifact and explicit app review.

## 9. Run one real-pair provisional T1 enhancement demonstration

Inputs:

- [C23S5_D1 pre-Gd T1](../output/all_mice/C23S5_D1/pre_coronal.nii.gz)
- [C23S5_D1 post-Gd T1](../output/all_mice/C23S5_D1/post_coronal.nii.gz)
- [C23S5_D1 testing brain mask](../derivatives/brain_seg/manual_test_cleaned/C23S5_D1.nii.gz)

**TEMP OUTPUT + COMPUTE.** This transitional backend performs its own post-to-pre rigid
registration and writes semi-quantitative T1-weighted gadolinium-enhancement outputs:

```bash
env OMP_NUM_THREADS=2 ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=2 \
  nice -n 10 \
  conda run -n lys-bbb python scripts/quantification/quantify_flash_pair.py \
    --pre "$LYS_PROJ2/output/all_mice/C23S5_D1/pre_coronal.nii.gz" \
    --post "$LYS_PROJ2/output/all_mice/C23S5_D1/post_coronal.nii.gz" \
    --mask "$LYS_PROJ2/derivatives/brain_seg/manual_test_cleaned/C23S5_D1.nii.gz" \
    --session-id C23S5_D1_demo \
    --out-dir "$LYS_DEMO_ROOT/t1_enhancement_C23S5_D1"
```

Inspect its summary and QC:

```bash
find "$LYS_DEMO_ROOT/t1_enhancement_C23S5_D1" -maxdepth 2 -type f -print
open "$LYS_DEMO_ROOT/t1_enhancement_C23S5_D1/C23S5_D1_demo_summary.csv"
```

Do not describe this as permeability, absolute T1, `Ktrans`, `Ki`, or DCE. The testing
mask is not an app-approved dependency, so this is not an approved result.

## 10. Demonstrate cohort discovery without quantification

**TEMP OUTPUT.** This is a fast dry run: it discovers real converted pre/post sessions
but does not register or quantify them.

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_cohort.py \
  "$LYS_PROJ2/output/all_mice" \
  --out-dir "$LYS_DEMO_ROOT/t1_cohort_dry_run" \
  --dry-run
```

Inspect the discovered sessions:

```bash
open "$LYS_DEMO_ROOT/t1_cohort_dry_run/cohort_sessions.csv"
conda run -n lys-bbb python -m json.tool \
  "$LYS_DEMO_ROOT/t1_cohort_dry_run/cohort_metadata.json"
```

## 11. Run one T2 draft from the mounted test study

The repository currently has no standalone local T2 NIfTI suitable for this command.
The following block uses the real persistent study after `Untitled` is mounted. It reads
the first active, validated native T2 path from SQLite and copies it to the CLI's required
`<input>/<case>/scan.nii.gz` layout. It does not infer T1/T2 atlas pairing.

### 11.1 Select and copy a real validated T2

**TEMP OUTPUT.** First repeat the mount check:

```bash
test -f "$LYS_TEST_STUDY/project.sqlite"
```

Then prepare one disposable input:

```bash
T2_ROW="$(sqlite3 -separator '|' "$LYS_TEST_STUDY/project.sqlite" \
  "SELECT s.subject_code, i.output_path
   FROM scan_inputs AS i
   JOIN subjects AS s ON s.id = i.subject_id
   WHERE i.active = 1
     AND i.role = 'T2'
     AND i.state = 'CONVERTED'
     AND i.validation_state = 'VALID'
   ORDER BY s.subject_code
   LIMIT 1;")"

if [[ -z "$T2_ROW" ]]; then
  printf 'No active validated T2 was found.\n' >&2
  false
fi

T2_CASE="${T2_ROW%%|*}"
T2_RECORDED_PATH="${T2_ROW#*|}"
if [[ "$T2_RECORDED_PATH" = /* ]]; then
  T2_SOURCE="$T2_RECORDED_PATH"
else
  T2_SOURCE="$LYS_TEST_STUDY/$T2_RECORDED_PATH"
fi

test -f "$T2_SOURCE"
mkdir -p "$LYS_DEMO_ROOT/t2_input/$T2_CASE"
cp "$T2_SOURCE" "$LYS_DEMO_ROOT/t2_input/$T2_CASE/scan.nii.gz"
printf 'T2 case: %s\nCopied from: %s\n' "$T2_CASE" "$T2_SOURCE"
```

### 11.2 Run the immutable five-fold T2 ensemble

**TEMP OUTPUT + COMPUTE.** This is a real five-model inference and may be heavy. Run only
one case at a time:

```bash
env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2 \
  nice -n 10 \
  conda run --no-capture-output -n lys-bbb lys-bbb-t2-infer \
    --release "$LYS_T2_RELEASE" \
    --input "$LYS_DEMO_ROOT/t2_input" \
    --work "$LYS_DEMO_ROOT/t2_work" \
    --output "$LYS_DEMO_ROOT/t2_output" \
    --device auto
```

Inspect the produced draft bundle:

```bash
find "$LYS_DEMO_ROOT/t2_output" -maxdepth 4 -type f -print
```

The native lesion mask in the study is not altered or approved by this standalone run.
Use the application for managed T2 review, correction, approval, volume, and CSV export.

## 12. Validate the real AIDAmri/Allen resources and draft major-region scheme

Source resources:

```text
/Users/paul-andreaslaize/Documents/LYS_PROJ1/work/external/AIDAmri/lib/NP_template_sc0.nii.gz
/Users/paul-andreaslaize/Documents/LYS_PROJ1/work/external/AIDAmri/lib/annoVolume+2000_rsfMRI.nii.gz
/Users/paul-andreaslaize/Documents/LYS_PROJ1/work/t2w_allen_first/aidamri_split_parental_structures.csv
```

LYS_PROJ1 is read only here. The production code is imported only from LYS_PROJ2.

### 12.1 Recheck the published source checksums

**READ-ONLY:**

```bash
shasum -a 256 \
  "/Users/paul-andreaslaize/Documents/LYS_PROJ1/work/external/AIDAmri/lib/NP_template_sc0.nii.gz" \
  "/Users/paul-andreaslaize/Documents/LYS_PROJ1/work/external/AIDAmri/lib/annoVolume+2000_rsfMRI.nii.gz" \
  "/Users/paul-andreaslaize/Documents/LYS_PROJ1/work/t2w_allen_first/aidamri_split_parental_structures.csv"
```

Expected SHA-256 values, in the same order:

```text
f1bc07b507fe260c3f48c3bc48a58ec1492aa45b0e24133665fbe77bab01b65a
9b7951f4bc61838ed6cbd2611ab4542d3acf11e849856d9a5aaf5552ceafeec4
8d62af8b9f961fbc3bd9b276b22898d936d72f856a4e340aff2683d1012b9279
```

### 12.2 Validate atlas geometry, label lookup, mask, and major-region completeness

**TEMP OUTPUT.** This creates only a disposable annotation-support template mask. The
major-region scheme is loaded as unapproved; this command does not approve it.

```bash
conda run --no-capture-output -n lys-bbb python - <<'PY'
import os
from pathlib import Path

from lys_bbb.atlas_release import (
    AtlasReleaseSpec,
    create_annotation_support_template_mask,
    load_major_region_scheme,
    validate_atlas_release,
)

project = Path("/Users/paul-andreaslaize/Documents/LYS_PROJ2")
source = Path("/Users/paul-andreaslaize/Documents/LYS_PROJ1/work")
mask_path = Path(os.environ["LYS_DEMO_ROOT"]) / "atlas_template_support_mask.nii.gz"
template = source / "external/AIDAmri/lib/NP_template_sc0.nii.gz"
labels = source / "external/AIDAmri/lib/annoVolume+2000_rsfMRI.nii.gz"
lookup = source / "t2w_allen_first/aidamri_split_parental_structures.csv"

create_annotation_support_template_mask(labels, mask_path)
release = validate_atlas_release(
    AtlasReleaseSpec(
        template_path=template,
        labels_path=labels,
        source_lookup_path=lookup,
        template_mask_path=mask_path,
    )
)
scheme = load_major_region_scheme(
    project / "config/atlas/major_regions_v1.csv",
    source_label_ids=release.label_ids,
    approved=False,
)

print("release:", release.spec.release_version)
print("template shape:", release.template_geometry.shape)
print("template orientation:", release.template_geometry.orientation)
print("source labels:", len(release.label_ids))
print("mapping version:", scheme.mapping_version)
print("mapping rows:", len(scheme.rows))
print("approved:", scheme.approved)
print("template-mask SHA-256:", release.template_mask_sha256)
PY
```

The draft mapping contract is [major_regions_v1.csv](../config/atlas/major_regions_v1.csv).
Approved regional exports remain blocked until Paul explicitly approves that scheme in
the app.

### 12.3 Inspect the exact installed ANTs interfaces

**READ-ONLY:**

```bash
conda run -n lys-bbb antsRegistration --version
conda run -n lys-bbb antsRegistration --help
conda run -n lys-bbb antsApplyTransforms --help
conda run -n lys-bbb N4BiasFieldCorrection --help
conda run -n lys-bbb CreateJacobianDeterminantImage --help
```

Atlas registration itself is intentionally application-managed because resource import,
candidate selection, QC, approval, composition, and invalidation must be durable. Do not
run a real atlas registration until the exact T1/T2 subject and timepoint identity is
confirmed.

## 13. Demonstrate software correctness without real processing

### 13.1 Focused synthetic atlas and persistence tests

**TEMP TEST OUTPUT ONLY.** These do not download data or run full ANTs registration:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 QT_QPA_PLATFORM=offscreen \
  conda run -n lys-bbb python -m pytest \
    tests/test_atlas_mapping_vertical.py \
    tests/test_atlas_mapping_persistence.py \
    tests/test_t1_brain_mask_integration.py \
    -q
```

### 13.2 Complete repository verification

```bash
make lint
make test
```

The current expected result is `182 passed`; warnings from wrapped ANTs/SWIG types may
still be printed.

## 14. Inspect all disposable outputs

```bash
printf 'Demo root: %s\n' "$LYS_DEMO_ROOT"
du -sh "$LYS_DEMO_ROOT"
find "$LYS_DEMO_ROOT" -maxdepth 3 -type f -print
```

Because every generated example is isolated under `/private/tmp`, deleting that demo
directory later cannot remove raw data, the persistent study, or approved application
artifacts. Inspect anything needed before cleanup.

## Recommended live demonstration order

For a short demonstration that keeps the Mac responsive:

1. Verify the environment and both model releases.
2. Mount `Untitled` and open the persistent test study.
3. Show active inputs and durable jobs with the read-only SQLite queries.
4. Run the one-case no-TTA T1 mask example.
5. Inspect its metadata and QC, then demonstrate editing only a copied mask.
6. Run the cohort dry-run and technical mask validator.
7. Validate the AIDAmri resources and run the focused synthetic atlas tests.
8. Run real T2 inference or registration only if the extra compute time is useful to the
   audience.

Never run multiple model jobs concurrently on this Mac. Do not present any automatic
mask, provisional enhancement, draft major-region scheme, or successful registration as
human approval or scientific validation.
