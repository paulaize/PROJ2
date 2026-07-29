# Pre-Gd T1 brain-mask nnU-Net: grouped Kaggle protocol

The executable notebook is
`notebooks/t1_brain_mask_standard3d_nnunet_kaggle.ipynb`.

## Scientific purpose

The model creates a draft brain mask on native pre-Gd T1-weighted mouse MRI.
After native-grid human correction and explicit approval, that exact pre-space
mask can define the brain support for registered pre/post enhancement
quantification.

Static pre/post T1-weighted MRI supports relative or semi-quantitative
enhancement only. This workflow does not estimate gadolinium concentration,
absolute T1, Ktrans, Ki, DCE pharmacokinetics, or a direct BBB permeability
constant.

## Local data audit on 2026-07-27

- 34 pre-Gd T1-weighted scans;
- 17 animal identifiers;
- every image is 96×185×256;
- spacing is approximately 0.15×0.07784×0.078125 mm;
- 34 automatic RS2/M-seam prelabels in the Desktop handoff;
- those Desktop prelabels are byte-identical to the frozen automatic outputs;
- 34 editable masks under `derivatives/brain_seg/manual`;
- 13 of those editable masks currently differ from their automatic start;
- one filename is marked `_done`;
- zero masks have a complete explicit approval record in the current project
  state.

Automatic prelabels and unfinished working masks are not training labels.

`C23S3_D1` and `C23S3_D1_bis` may both remain useful brain-mask training
images if Paul confirms that both acquisitions are scientifically usable and
reviews both masks. Their manifest rows must carry the same explicit
`animal_id`. Only the correct acquisition should later enter longitudinal
enhancement quantification.

## Approved Kaggle input contract

Upload one directory (or `LYS_T1_brainmask_manual_v1.zip`) with:

```text
LYS_T1_brainmask_manual_v1/
├── training_manifest.csv
├── images/
│   └── <case>_pre_t1.nii.gz
└── labels/
    └── <case>_brain_mask.nii.gz
```

The manifest requires:

```text
case_id
animal_id
modality
acquisition_role
image
mask
include_for_nnunet
mask_review
reviewer
reviewed_at
image_sha256
mask_sha256
```

Use `modality=T1w`, `acquisition_role=pre_gd`,
`include_for_nnunet=yes`, and `mask_review=approved`. `image` and `mask` are
paths relative to the manifest. `reviewed_at` must contain a timezone-aware
timestamp. The notebook validates hashes, 3-D shape, affine, finite image
values, binary labels, nonempty masks, counts, and animal groups.

Do not derive `animal_id`, approval, or inclusion from a filename. Build the
package only after all native slices have been reviewed and the reviewer and
approval time have been recorded.

## Fixed candidate and why

- nnU-Net v2.8.1, source commit
  `468cf803df9b267150ae2b6c0c59b8ac84f16227`;
- official `ExperimentPlanner`;
- `nnUNetPlans`;
- `3d_fullres`;
- official standard `PlainConvUNet`;
- 250 epochs;
- no external training images;
- postprocessing none;
- one final all-data model for deployment.

Planning the audited geometry produced:

- patch size 80×192×160;
- global batch size 2;
- 30,785,994 trainable parameters;
- 117.4 MiB of float32 network tensors.

The standard 2-D plan would be smaller (20,619,082 parameters; 78.7 MiB) and
probably faster, but it discards through-plane context. It is not silently
substituted for the quality-oriented 3-D candidate. A future 2-D comparator
requires an explicit protocol version and paired grouped OOF evidence.

Training duration does not change released parameter count or CPU inference
cost. Removing optimizer and training state cuts a full checkpoint to the
single 117-MiB inference network without changing prediction tensors.

## Making a trained model inference-only

Do this only after training is complete. Preserve the original full checkpoint
and its SHA-256 in the frozen training archive because the stripped checkpoint
cannot resume training.

An nnU-Net inference model folder needs:

```text
<model-folder>/
├── dataset.json
├── plans.json
└── fold_<fold>/
    └── checkpoint_final.pth
```

Use `checkpoint_best.pth` instead when that is the checkpoint selected on a
proper validation fold. The final `fold_all` release in this protocol uses
`checkpoint_final.pth`.

For nnU-Net v2.8.1, retain these checkpoint entries:

```text
network_weights
trainer_name
init_args
inference_allowed_mirroring_axes
```

For example:

```python
from pathlib import Path

import torch

source = Path("/path/to/full/checkpoint_final.pth")
destination = Path("/path/to/inference-only/checkpoint_final.pth")

checkpoint = torch.load(source, map_location="cpu", weights_only=False)
required = {
    "network_weights",
    "trainer_name",
    "init_args",
    "inference_allowed_mirroring_axes",
}
missing = required - set(checkpoint)
if missing:
    raise KeyError(f"Checkpoint is missing inference entries: {sorted(missing)}")

inference_only = {key: checkpoint[key] for key in required}
if destination.exists():
    raise FileExistsError(destination)
destination.parent.mkdir(parents=True, exist_ok=True)
torch.save(inference_only, destination)
```

If training used a custom trainer that changed only save frequency, replace
`trainer_name` in the inference copy with its equivalent installed upstream
trainer name. In this protocol,
`nnUNetTrainer_250epochs_SaveEveryEpoch` becomes
`nnUNetTrainer_250epochs`. Do not make that replacement when a custom trainer
changed architecture or inference behavior.

Copy `plans.json` and `dataset.json` from the original model folder. Record
SHA-256 hashes and sizes for the original checkpoint, inference checkpoint,
plans, and dataset metadata. Before release, run both folders on the same
prepared image with the same folds, checkpoint selection, device, TTA policy,
and nnU-Net version. Require identical output masks and investigate any
difference.

This removes optimizer, scheduler, gradient-scaler, epoch, and logger state. It
does not prune, quantize, or alter `network_weights`, so it should not change
the prediction. Float32 tensors compress poorly in ZIP archives; the expected
one-model floor is therefore approximately the 117-MiB network size. Every
additional ensemble fold adds another copy of the weights and another model
evaluation. Pruning, float16 conversion, or integer quantization can change
predictions and requires separate validation rather than being treated as
lossless packaging.

## Run order

1. Finish and explicitly approve the native-grid manual masks.
2. Upload the approved package to Kaggle.
3. Enable T4×2 and Internet.
4. Leave only `RUN_BENCHMARK_5E=True`; run all and download
   `LYS_T1_standard3d_5epoch_inference_only.zip`.
5. Test the benchmark on the ZenBook with CPU, one preprocessing/export
   worker, and `--disable_tta`. Confirm runtime and peak RAM before spending
   the full training budget.
6. In new resumable sessions set `RUN_BENCHMARK_5E=False`,
   `RUN_CV_250=True`, and choose incomplete folds with `FOLDS_TO_RUN`.
7. Download a new resume archive at the end of every session.
8. After all five folds finish, review paired default-TTA/no-TTA pooled OOF
   metrics. Do not use overall voxel accuracy.
9. Set `RUN_FINAL_ALL_250=True` and train one final model on all approved
   labels.
10. Download `LYS_T1_brainmask_standard3d_final_inference.zip`.

The custom trainer changes only `save_every` from 50 to 1, overwriting
`checkpoint_latest.pth` each epoch. A stopped run therefore resumes from the
last completed epoch. It does not change architecture, loss, or learning-rate
schedule.

## Evidence and deployment

Five grouped folds estimate performance across the 17 development animals.
They are not intended as a five-model ZenBook ensemble. The final `fold_all`
model sees every approved label and is released as one inference-only model.
Its performance expectation comes from pooled OOF evidence; it has no unbiased
validation score of its own.

Required review includes full-case Dice, precision, recall, failures, volume
error, HD95, 0.15-mm surface Dice, fold consistency, animal consistency, and
manual correction burden. Overall voxel accuracy is background dominated.

On the i5-1135G7/8-GB ZenBook, one no-TTA model is plausible but not guaranteed
until benchmarked. The T1 volume requires multiple large sliding windows and is
substantially heavier than the shallow T2 example. A cautious expectation is
roughly 2–5 minutes per case with peak process memory potentially around
4–7 GB. Close other applications and keep `-npp 1 -nps 1`; paging may make it
slower. TTA is several times slower. Five-fold deployment would multiply
network work by approximately five and is not the release strategy.

Every released prediction remains a draft mask requiring human review and
explicit approval before enhancement quantification.
