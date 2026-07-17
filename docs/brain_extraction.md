# T1 brain extraction

## Current decision

Create the brain mask on native pre-Gd T1, review it, then apply the same approved mask
to pre-Gd T1 and the registered post-Gd T1. Do not independently extract the post-Gd
brain unless a documented exception is being investigated.

Automatic model output is an immutable pre-label. Quantification requires either an
accepted automatic mask or a manually corrected and accepted mask.

The next project milestone is model selection—not nnU-Net training and not bulk cohort
quantification.

## Colab benchmark shortlist

The initial shortlist was verified against the public project or paper resources in
July 2026:

| Candidate | Why test it | Main uncertainty |
|---|---|---|
| [MouseBrainExtractor](https://github.com/MouseSuite/MouseBrainExtractor) | Mouse-specific, supports T1 and released in-vivo weights | Existing masks show boundary/component failures on this cohort |
| [RS2-Net](https://github.com/VitoLin21/Rodent-Skull-Stripping) | Rodent multi-centre model with released pretrained weights | Training distribution includes rats and may not match this T1 protocol |
| [BEN](https://github.com/yu02019/BEN) | Multi-species, multimodal model with public code/weights | Older environment and broad training target may reduce precision or complicate Colab setup |

Human models such as BET, SynthStrip, or HD-BET are not primary candidates. They may be
added only as clearly labelled negative/control comparisons if the rodent models are
insufficient.

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

Prepare inputs locally with:

```bash
conda run -n lys-bbb python scripts/brain_extraction/prepare_colab_package.py \
  --input-root output/all_mice \
  --random-count 12
```

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
