# LYS BBB MRI

LYS BBB is a subject-centred desktop application and scientific backend for mouse MRI.
It owns three connected workflows:

```text
T1: pre/post import → brain-mask review → registration review → enhancement
T2: native T2 → frozen-model draft mask → human review → lesion volume
Atlas: AIDAmri MRI/Allen → pre-T1 → native T2 → major-region lesion overlap
```

The repository is a working development checkpoint, not a finished scientific product.
The desktop application completes the reviewed T2 path through an approved native-space
lesion volume and CSV export. T1 mask review is connected to the desktop study. T1
registration and provisional enhancement now have typed backends, persistent jobs,
exact dependency records, approval/invalidation state, connected desktop controls, and
subject-result presentation. A provisional atlas-mapping vertical slice now adds native
ANTs registration, staged review, direct major-label propagation, native-lesion overlap,
and restart-safe state. Real-case T1/atlas smoke testing and scientific validation remain.

## Immediate goal

Atlas scope was explicitly authorized for this milestone. The next goal is to smoke-test
the connected atlas path on one explicitly matched real case:

> Confirm the exact app subject/session pairing, approve the exact native pre-Gd brain
> mask and T2 support mask, review atlas→pre and pre→T2 independently, approve the
> native-T2 composite, calculate only major-region overlap, and reopen unchanged.

Do not add unrelated pages, modalities, models, detailed atlas outputs, Waxholm
comparators, SyN tuning, or general-purpose framework code before that smoke test passes.

## Repository ownership

```text
LYS_PROJ1
  T2 model training, validation, checkpoint selection, and frozen releases

LYS_PROJ2
  Scientific execution backend and desktop application
  Import, review, approval, results, provenance, and exports
```

Within this repository:

```text
src/lys_bbb/       Qt-free scientific backend
src/lys_bbb_app/   desktop domain, services, persistence, and PySide6 UI
```

Production code never imports the live `~/Documents/LYS_PROJ1` checkout. It accepts only
an immutable checksummed release. The current T2 release remains external at
`~/Downloads/LYS_v1_RatLesNetV2_mac_inference`.

See [current state](docs/current_state.md) for the implemented behavior, remaining
blockers, and acceptance criteria. This README intentionally does not duplicate that
changing inventory.

## Run locally

```bash
conda env create -f environment.yml
conda run -n lys-bbb python -m pip install --no-deps -e .
conda run -n lys-bbb lys-bbb-desktop
```

Run the complete test suite with:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  conda run -n lys-bbb python -m pytest tests -q
```

Raw MRI data may live on mounted hard drives. Study creation records source references
and writes derived files under the chosen study root; it does not overwrite source data.

## Documentation map

| Need | Authoritative document |
|---|---|
| Current facts, blockers, and next milestone | [Current state](docs/current_state.md) |
| Stable scientific and package boundaries | [Pipeline architecture](docs/pipeline_architecture.md) |
| Stable desktop product contract | [Desktop application](docs/desktop_application.md) |
| Frozen T2 release and review handoff | [T2 lesion integration](docs/t2_lesion_integration.md) |
| Current T1 mask decision and review rules | [T1 brain extraction](docs/brain_extraction.md) |
| Meaning and limitations of T1 measurements | [Enhancement quantification](docs/enhancement_quantification.md) |
| AIDAmri atlas mapping, approvals, and remaining validation | [Atlas mapping](docs/atlas_mapping.md) |
| Commands and developer workflow | [Development guide](docs/development.md) |

`AGENT.md` is the compact operating brief for coding agents. It should point to these
documents rather than duplicate them.

## Scientific and data-safety rules

- Never modify raw Bruker data.
- Automatic masks are drafts, never ground truth.
- Job success, artifact approval, method approval, and result approval are distinct.
- Native pre-Gd T1 is the T1 reference space; native T2 is the lesion-volume space.
- Static pre/post scans support semi-quantitative T1-weighted gadolinium enhancement,
  not absolute T1, `Ktrans`, `Ki`, DCE, or absolute permeability.
- Generated files in `output/`, `derivatives/`, and `reports/` may be older than the
  checked-out code. Preserve manual masks and approvals and record provenance.
