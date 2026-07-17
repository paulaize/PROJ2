# T1 brain extraction

## Current decision

Create the brain mask on native pre-Gd T1, review it, then apply the same approved mask
to pre-Gd T1 and the registered post-Gd T1. Do not independently extract the post-Gd
brain unless a documented exception is being investigated.

Automatic model output is an immutable pre-label. Quantification requires either an
accepted automatic mask or a manually corrected and accepted mask.

The next project milestone is model selection—not nnU-Net training and not bulk cohort
quantification.

## Runnable Colab benchmark

The exact notebook is
[`notebooks/brain_extraction_colab_benchmark.ipynb`](../notebooks/brain_extraction_colab_benchmark.ipynb).
The runnable set was verified against the official project resources in July 2026:

| Prediction | Why test it | Main uncertainty |
|---|---|---|
| [MouseBrainExtractor](https://github.com/MouseSuite/MouseBrainExtractor) `invivo_iso` | Mouse-specific, supports T1 and released in-vivo weights | Existing masks show boundary/component failures on this cohort |
| MouseBrainExtractor `invivo_aniso` | Tests whether the 2D thick-slice model behaves better on these coronal images | It violates the authors' >3 anisotropy rule for this cohort and is a sensitivity run only |
| [RS2-Net](https://github.com/VitoLin21/Rodent-Skull-Stripping) | Rodent multi-centre model with released pretrained weights | Training distribution includes rats and may not match this T1 protocol |

[BEN](https://github.com/yu02019/BEN) is deliberately excluded from the exact notebook.
Its official release requires TensorFlow 1.15/Keras 2.2.4, and the repository's modern
nnBEN successor still has no released code or weights. Do not add an improvised BEN
environment and call it a reproducible comparison.

Human models such as BET, SynthStrip, or HD-BET are not primary candidates. They may be
added only as clearly labelled negative/control comparisons if the rodent models are
insufficient.

### Optional companion controls

The primary three-model notebook has now completed successfully on the frozen 10-case
package. Do not modify that known-working environment just to add exploratory models.
The separate notebook
[`notebooks/brain_extraction_colab_extra_baselines.ipynb`](../notebooks/brain_extraction_colab_extra_baselines.ipynb)
reuses the same upload package and adds two diagnostic controls:

| Prediction | Why it can still be informative | Why it is not a primary mouse-T1 candidate |
|---|---|---|
| [CAMRI RodentMRISkullStripping](https://github.com/CAMRIatUNC/RodentMRISkullStripping) | Open rodent weights and a reproducible 2D U-Net inference contract | Released training data are mouse/rat T2-weighted RARE and T2*-weighted EPI, not T1 |
| [deepbet](https://github.com/wwu-mmll/deepbet) 1.0.2 | Modern released T1 model with bundled weights and a Colab-compatible PyTorch runtime | It was developed for healthy adult human T1 MRI, not mouse anatomy |

The CAMRI adapter preserves its official 0.1-mm resampling, global min-max
normalization, 128 × 128 bidirectional patch voting, 0.5 threshold, and nearest-neighbour
return to the native grid. It uses Keras 3 with the PyTorch backend solely to load the
authors' legacy HDF5 checkpoint on current Colab; model weights and scientific
preprocessing are unchanged. The implementation batches patches to avoid thousands of
one-patch GPU calls.

SynthStrip was considered but not added. Its human-scale 1-mm conformation/minimum
field-of-view contract makes an approximately 10–30 mm mouse head a poor diagnostic
comparison. ANTsX mouse extraction and several other released rodent networks currently
provide T2/T2* rather than T1 weights, duplicate the CAMRI cross-contrast question, or
require a legacy runtime with substantially more friction.

MouseBrainExtractor provides `invivo_iso`, `invivo_aniso`, and `exvivo` weights. Its
published rule uses `invivo_aniso` when the anisotropy ratio is greater than 3. The
current T1 voxel sizes are approximately 0.150 × 0.078 × 0.078 mm, giving a ratio near
1.9, so `invivo_iso` is the rule-based starting point. Do not select the anisotropic
weights merely because the display is coronal; it can be included as a sensitivity run.

## Benchmark cohort

Use 10–20 pre-Gd images that span the actual failure distribution:

- D1 and D7;
- low and high bias field;
- different head positions and anterior/posterior coverage;
- normal-looking and pathological brains;
- the worst existing MouseBrainExtractor cases;
- at least one longitudinal pair from the same animal.

Model comparison must use identical cases and native input files. Do not resample or
normalize one candidate differently unless that operation is part of its official,
versioned inference contract.

Quantitative model ranking requires reviewed reference masks. A practical sequence is:

1. Run all candidates on the representative images.
2. Review blinded QC montages to identify failure modes.
3. Correct a balanced subset in ITK-SNAP.
4. Freeze those masks as references with reviewer and checksum metadata.
5. Score every candidate against the same references.

## Colab package and output contract

The frozen first benchmark cohort is listed in
`config/brain_extraction_benchmark_10.txt`. Rebuild its upload archive with:

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py \
  --input-root output/all_mice \
  --case-file config/brain_extraction_benchmark_10.txt \
  --out-dir derivatives/brain_extraction/colab \
  --package-name t1_brain_extraction_benchmark_10 \
  --overwrite
```

The ready local archive is
`derivatives/brain_extraction/colab/t1_brain_extraction_benchmark_10.zip`. In Colab,
upload the notebook, select a T4 GPU, run all cells, and upload this archive when the
notebook prompts. The final cell downloads `t1_brain_extraction_results.zip`.

To run the optional controls, start a fresh T4 Colab runtime, upload
`notebooks/brain_extraction_colab_extra_baselines.ipynb`, run all cells, and upload the
same 10-image archive. Its final cell downloads
`t1_brain_extraction_extra_results.zip`. A separate runtime keeps the successful primary
benchmark reproducible and avoids dependency changes underneath MBE/RS2-Net.

Colab currently uses Python 3.12. The notebook therefore pins MONAI 1.4.0, the first
MONAI release that resolves the removed Python 3.12 `find_module`/`load_module` API,
rather than MouseBrainExtractor's older MONAI 1.3.0 requirement. A runtime import check
and both model constructors run before weight downloads and case inference.

If an older uploaded notebook fails with `FileFinder ... find_module`, do not re-upload
the images or weights. In the same live Colab runtime, upgrade MONAI without changing
PyTorch, verify the import, then rerun the two MBE cells, RS2-Net cell, QC cell, and final
download cell:

```python
import subprocess, sys
subprocess.check_call([
    sys.executable, "-m", "pip", "install", "-q", "--upgrade", "--no-deps",
    "monai==1.4.0",
])
subprocess.check_call([
    sys.executable, "-c",
    "import monai; from monai.inferers import SliceInferer; "
    "assert monai.__version__.startswith('1.4.'); print(monai.__version__)",
])
```

PyTorch 2.6 also changed `torch.load` to use `weights_only=True` by default. The official
RS2 legacy checkpoint contains NumPy metadata and cannot be opened by that restricted
loader. Because the checkpoint is downloaded from the RS2 authors' official link and
its SHA-256 is recorded, the notebook patches RS2's one checkpoint callsite to specify
`weights_only=False`. A checkpoint preflight verifies that it contains `state_dict`
before case inference. Never apply this compatibility mode to an untrusted checkpoint.

To include available candidate/reference masks:

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py \
  --input-root output/all_mice \
  --reference-dir derivatives/brain_seg/manual \
  --require-reference
```

The archive contains `benchmark_manifest.csv`, native pre-Gd images, and optional
reference candidates. File presence does not prove approval; confirm review status before
using a mask for quantitative ranking. Model weights and third-party repositories are
downloaded in Colab and pinned to a commit/version; they are not committed here.

Every model adapter must produce:

```text
predictions/<model>/<case_id>_brain_mask.nii.gz
metadata/<model>/<case_id>.json
logs/<model>/<case_id>.log
```

The binary prediction must match the input shape and affine. Metadata must record model
name, source URL, code revision, weight identity/checksum, preprocessing, runtime,
hardware, threshold, postprocessing, and success/failure. Resampling back to the input
grid must use nearest-neighbour interpolation and be explicit in metadata.

The existing `scripts/brain_extraction/mbe/` adapter is model-specific support code. It
does not define the benchmark or make MouseBrainExtractor the default winner.

## ITK-SNAP comparison after Colab

Move the downloaded result archive into `~/Downloads`, then run from the repository:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip
```

The command safely extracts the archive, validates each mask against its T1 grid, and
opens one ITK-SNAP window per model for one case at a time. Close all three windows after
comparison, select the preferred mask in the terminal, and continue to the next case.
It writes `model_review.csv`, displays case-level vote counts, and can write a provisional
`benchmark_decision.json` for the overall choice.

After running the optional companion notebook, compare all five outputs per case by
passing both archives in the same command:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip \
  ~/Downloads/t1_brain_extraction_extra_results.zip
```

Combined decisions are written to
`~/Downloads/t1_brain_extraction_combined_review/` by default. Use `--review-dir` to
choose a different location. The two control labels remain visible in the terminal so
their training-domain mismatch is not lost during visual review.

Useful checks and filters:

```bash
# Validate and print every ITK-SNAP command without opening the application.
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip --dry-run

# Review one case only.
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip --case C23S5_D1
```

The viewer is detected from `PATH` or the normal macOS application location. Use
`--viewer /path/to/ITK-SNAP` only if automatic detection fails.

## Evaluation

For each reviewed case and model, calculate:

- Dice and Jaccard;
- precision and recall;
- volume error in mm³ and percent;
- mean surface distance and 95th-percentile Hausdorff distance;
- connected-component count and boundary contact;
- inference failures and manual correction time;
- qualitative errors at olfactory bulbs, cortex, cerebellum, inferior brain, and
  brainstem.

Use `scripts/qc/benchmark_brain_masks.py` for per-case geometric metrics. The Colab
benchmark should later add a cohort aggregator and blinded QC dashboard.

The winning model is not simply the highest mean Dice. Prefer the model with few hard
failures, acceptable boundary behavior near enhancing tissue, stable volumes, low manual
correction burden, and a reproducible license/runtime suitable for the future desktop
application.

## RS2-Net probability calibration

The primary notebook contains an optional cell named **RS2-Net probability threshold
sweep**, immediately after the standard RS2-Net cell. It reruns only RS2-Net with the
official `--save_probabilities` option, validates the exported probability orientation
against the official 0.50 mask, and generates native-grid masks at 0.50, 0.60, 0.70,
0.80, 0.90, and 0.95. It also creates an interactive case/slice viewer and saved QC
montages inside Colab.

RS2 exports two sigmoid channels, but the pinned release's label manager defines its
discrete mask specifically as channel 0 greater than 0.5 rather than applying argmax or
softmax. The calibration cell tests the exported channels against the official mask and
then thresholds the matching raw sigmoid channel. The reconstructed 0.50 mask must reach
Dice ≥0.99 against the official output or the cell stops rather than writing misoriented
candidates.

The cell downloads `rs2_threshold_sweep_results.zip`. These are calibration candidates,
not approved masks. A threshold must be selected across the complete reviewed calibration
set, not from the single most obvious skull false-positive. Compare the sweep with the
primary archive locally when needed:

```bash
conda run -n lys-bbb python scripts/brain_extraction/review_colab_results.py \
  ~/Downloads/t1_brain_extraction_results.zip \
  ~/Downloads/rs2_threshold_sweep_results.zip
```

## Human review

The review workflow must preserve three products:

```text
automatic prediction       immutable
editable review mask       working copy
accepted reviewed mask     immutable after approval
```

ITK-SNAP remains the editor. The current worklist and HTML dashboard are development
tools; the future desktop application will expose Accept, Edit, Reject, and Exclude
actions without asking users to edit CSV filenames manually.

## Custom nnU-Net

A custom nnU-Net brain-mask model is deferred until enough representative masks have
been reviewed. Split data by mouse, never by slice. It becomes worthwhile only if the
open-weight benchmark shows recurring cohort-specific errors or if manual correction
remains too expensive. Its predictions must pass the same output and review contract as
the open-weight models.
