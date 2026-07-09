# nnU-Net Active Learning Plan

This is the medium-term route for brain-mask production after corrected
pre-contrast masks exist. The local pipeline now has the manifest and nnU-Net
raw-dataset preparation helpers; model training itself is still expected to run
on a cloud GPU.

The goal is not to create unchecked automatic segmentation. The goal is to use
nnU-Net as a mask-production accelerator, then visually QC and correct masks
before final BBB leakage quantification.

Operational split:

```text
MacBook   prepare NIfTI data, correct masks in ITK-SNAP, run QC
Cloud GPU train nnU-Net and predict masks
MacBook   QC predicted masks, correct failures, run quantification
```

## Current Decision

The current pre-label source is cloud MouseBrainExtractor. Those outputs are
not final masks and not training labels until corrected.

Preferred next path:

1. Correct 8-12 representative MouseBrainExtractor pre-labels in ITK-SNAP.
2. Save corrected binary masks on the exact pre-contrast image grid.
3. Train a first nnU-Net v2 model on corrected pre masks only.
4. Predict masks for the remaining pre scans.
5. Correct failures and retrain with about 10-20 corrected masks.
6. Visually QC every final mask before quantification.
7. Use each final pre-space mask for registered post-Gd quantification only
   after registration QC passes.

Raw automatic masks must not be used as labels. They can only be used as
pre-labels that are manually corrected.

The retired SHERM-inspired code is in `deprecated/sherm/` and is not part of
the active mask-production plan.

## Training Data

Use native 3D NIfTI pre-contrast images:

```text
image: output/all_mice/C25S1_D1/pre_coronal.nii.gz
label: derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask.nii.gz
```

The label must be a binary NIfTI on the exact same grid as the image:

```text
0 background / non-brain
1 brain
```

Do not train on PNG QC montages. Do not train the first model on
post-gadolinium images, because post intensity changes are the biological BBB
leakage signal. Segment or predict in pre-contrast space, register post to pre,
and use the final pre mask for post only after registration QC passes.

## Manual Mask Source

Cloud MouseBrainExtractor pre-labels are expected under:

```text
derivatives/brain_seg/mousebrainextractor/{case_id}_mousebrainextractor_mask.nii.gz
```

Open them for correction with:

```bash
conda run -n lys-bbb python scripts/masks/open_manual_mask_editor.py \
  --input-root output/all_mice \
  --prelabel-dir derivatives/brain_seg/mousebrainextractor \
  --prelabel-glob "*_mousebrainextractor_mask.nii.gz" \
  --prelabel-suffix "_mousebrainextractor_mask.nii.gz" \
  --manual-dir derivatives/brain_seg/manual \
  --skip-existing
```

Corrected masks should be saved as:

```text
derivatives/brain_seg/manual/{case_id}_pre_manual_mask.nii.gz
```

Start with cases that cover:

- bright skull/scalp or surface-signal failures
- rostral and caudal coverage variation
- noisy or low-SNR scans
- D1 and D7
- different animals
- different positioning or coverage

## Brain-Mask Dataset Layout

nnU-Net v2 expects datasets under `nnUNet_raw/DatasetXXX_Name`, with
`imagesTr`, `labelsTr`, optional `imagesTs`, and `dataset.json`.

Planned first dataset:

```text
nnUNet_raw/
└── Dataset501_MouseBrainMask/
    ├── dataset.json
    ├── imagesTr/
    ├── labelsTr/
    └── imagesTs/
```

Case naming:

```text
imagesTr/C25S1_D1_0000.nii.gz
labelsTr/C25S1_D1.nii.gz
imagesTs/C25S4_D1_0000.nii.gz
```

Minimal `dataset.json`:

```json
{
  "channel_names": {
    "0": "T1"
  },
  "labels": {
    "background": 0,
    "brain": 1
  },
  "numTraining": 10,
  "file_ending": ".nii.gz"
}
```

## Manifest

Use a local manifest to build the nnU-Net dataset folder reproducibly:

```text
derivatives/brain_seg/nnunet_manifest.csv
```

Example:

```csv
case_id,image,mask,split
C25S1_D1,output/all_mice/C25S1_D1/pre_coronal.nii.gz,derivatives/brain_seg/manual/C25S1_D1_pre_manual_mask.nii.gz,train
C25S1_D7,output/all_mice/C25S1_D7/pre_coronal.nii.gz,derivatives/brain_seg/manual/C25S1_D7_pre_manual_mask.nii.gz,train
C25S3_D1,output/all_mice/C25S3_D1/pre_coronal.nii.gz,,test
```

Rows with `split=train` require a corrected mask. Rows with `split=test` are
unlabeled prediction images.

Build or refresh the manifest from the current QC state:

```bash
conda run -n lys-bbb python scripts/qc/build_qc_manifest.py \
  --input-root output/all_mice \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv

conda run -n lys-bbb python scripts/masks/build_manual_mask_workflow.py \
  --qc-manifest reports/qc/qc_manifest.csv \
  --manual-dir derivatives/brain_seg/manual \
  --nnunet-manifest derivatives/brain_seg/nnunet_manifest.csv
```

By default, only corrected masks marked with the `_pre_manual_mask_done.nii.gz`
suffix and passing basic grid checks become `split=train`. Existing masks that
are not marked done stay as unlabeled `split=test` rows unless
`--include-review-labels` is explicitly used for a controlled experiment.

The helper script converts this manifest into `nnUNet_raw/` by:

- copying training images to `imagesTr/{case_id}_0000.nii.gz`
- binarizing labels to `labelsTr/{case_id}.nii.gz`
- copying prediction images to `imagesTs/{case_id}_0000.nii.gz`
- checking that image and mask shape/affine match
- writing `dataset.json`

Dry-run the conversion first:

```bash
conda run -n lys-bbb python scripts/masks/prepare_nnunet_brain_extraction.py \
  --manifest derivatives/brain_seg/nnunet_manifest.csv \
  --nnunet-raw derivatives/brain_seg/nnUNet_raw \
  --dry-run
```

When the dry run reports the expected train/test counts and no failures, remove
`--dry-run` to create:

```text
derivatives/brain_seg/nnUNet_raw/Dataset501_MouseBrainMask/
```

## Cloud GPU Training

Use free GPU first. Kaggle Free GPU is the first choice for a 2D fold-0
prototype; Colab Free can be a backup but has less predictable availability.
Do not pay for GPU until a free 2D experiment shows that learning works on
these scans.

Recommended first cloud run:

```bash
pip install -q nnunetv2
export nnUNet_raw=/content/nnUNet_raw
export nnUNet_preprocessed=/content/nnUNet_preprocessed
export nnUNet_results=/content/nnUNet_results
nnUNetv2_plan_and_preprocess -d 501 --verify_dataset_integrity
nnUNetv2_train 501 2d 0 -device cuda
```

If the 2D model works and GPU memory/time allows, test:

```bash
nnUNetv2_train 501 3d_fullres 0 -device cuda
```

## Prediction

For unlabeled pre scans in `imagesTs`:

```bash
nnUNetv2_predict \
  -i /content/nnUNet_raw/Dataset501_MouseBrainMask/imagesTs \
  -o /content/predicted_brain_masks \
  -d 501 \
  -c 2d \
  -f 0
```

Copy predicted masks back to the Mac and QC them in ITK-SNAP.

Before using predictions for quantification, validate them as candidate brain
masks. Post-process predictions first:

```bash
conda run -n lys-bbb python scripts/masks/postprocess_brain_masks.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/nnunet_preds \
  -o derivatives/brain_seg/nnunet_preds_cleaned \
  --summary-csv reports/qc/brain_mask_postprocess_nnunet.csv \
  --summary-json reports/qc/brain_mask_postprocess_nnunet_summary.json
```

Then validate the cleaned predictions:

```bash
conda run -n lys-bbb python scripts/masks/build_brain_mask_manifest.py \
  --input-root output/all_mice \
  --mask-dir derivatives/brain_seg/nnunet_preds_cleaned \
  --mask-source nnunet_cleaned \
  --registration-summary reports/qc/registration_all_mice/registration_qc_summary.csv
```

Then build the analysis manifest from the candidate-mask manifest:

```bash
conda run -n lys-bbb python scripts/qc/build_analysis_manifest.py \
  --qc-manifest reports/qc/brain_mask_manifest.csv \
  -o derivatives/manifests/analysis_manifest.csv
```

This keeps model predictions on the same QC-gated path as manually corrected
masks.

## Use In Quantification

After QC/correction, pass the predicted or corrected pre-space mask to the
quantification pipeline:

```bash
conda run -n lys-bbb python scripts/quantification/quantify_flash_pair.py \
  --pre output/all_mice/C25S4_D1/pre_coronal.nii.gz \
  --post output/all_mice/C25S4_D1/post_coronal.nii.gz \
  --mask derivatives/brain_seg/nnunet_preds/C25S4_D1.nii.gz \
  -o derivatives/flash_quant/C25S4_D1
```

The mask must match the pre image shape and affine. During quantification, the
post-Gd image is registered to the pre-Gd image and the same pre-space brain
mask is used for both images. This is coherent only after registration QC
passes.

## Active-Learning Loop

Use this loop:

```text
1. Correct 8-12 manual pre masks from MouseBrainExtractor pre-labels.
2. Train nnU-Net fold 0.
3. Predict all remaining pre scans.
4. QC predictions in ITK-SNAP.
5. Correct the worst 5-10 predictions.
6. Add corrected masks to the manifest.
7. Retrain.
8. Repeat until predictions are mostly acceptable.
```

Split training/validation by animal, not by image. Do not put D1 from an
animal in training and D7 from the same animal in validation.

For final BBB analysis, visually inspect every predicted mask. The model is
only useful if it reduces manual work while preserving anatomical QC.

## Future Lesion-Segmentation Datasets

Brain masking and lesion segmentation should be trained and validated as
separate tasks before considering any combined model.

Future dataset plan:

```text
Dataset501_MouseBrainMask
  input: pre-Gd T1 FLASH
  label: brain mask

Dataset502_MouseLesionT2
  input: T2w high-resolution image
  label: stroke lesion mask

Dataset503_MouseBrainLesionMultichannel
  optional later dataset only after the brain-mask and T2w lesion tasks work independently
```

The T2w lesion model should be a second-stage project after reliable brain
masks exist. T2w images should define the stroke lesion, then the T2w lesion
mask should be registered or transformed into pre-Gd T1 space for BBB leakage
quantification. Do not use post-Gd enhancement to define the lesion ROI for the
primary analysis, because that would make lesion-specific leakage metrics
circular.

Future quantification should then measure T1 pre/post enhancement in:

- whole brain
- ipsilateral hemisphere
- contralateral hemisphere
- T2w-defined lesion ROI
- mirrored contralateral lesion ROI

Core concept:

```text
T2w = lesion definition
T1 pre/post = BBB leakage measurement
mirrored contralateral ROI = internal control
```

## References

- nnU-Net dataset format:
  `https://github.com/MIC-DKFZ/nnUNet/blob/master/documentation/reference/dataset-format.md`
- nnU-Net usage guide:
  `https://github.com/MIC-DKFZ/nnUNet/blob/master/documentation/how_to_use_nnunet.md`
- nnU-Net installation:
  `https://github.com/MIC-DKFZ/nnUNet/blob/master/documentation/installation_instructions.md`
- Kaggle notebooks:
  `https://www.kaggle.com/docs/notebooks`
