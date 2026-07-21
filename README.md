# LYS BBB MRI

LYS BBB is a subject-centred desktop application and scientific backend for mouse MRI.
It owns two workflows:

```text
T1: pre/post import → brain-mask review → registration review → enhancement
T2: native T2 → frozen-model draft mask → human review → lesion volume
```

The repository is a working development checkpoint, not a finished scientific product.
The desktop application completes the reviewed T2 path through an approved native-space
lesion volume and CSV export. The selected T1 mask generator runs locally, but T1
artifacts, registration review, and enhancement are not yet connected to study state.

## Immediate goal

Development is frozen horizontally. The active milestone is the first persistent T1
vertical slice:

> Generate or import a pre-Gd brain-mask draft, review or correct it, record an immutable
> decision, approve the exact mask artifact, and recover the same state after reopening.

Do not add pages, modalities, models, atlas features, or general-purpose framework code
until this user story passes its tests.

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

Open the explicitly synthetic UI preview with:

```bash
conda run -n lys-bbb lys-bbb-desktop --demo
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
  checked-out code. Preserve manual masks and decisions and record provenance.
