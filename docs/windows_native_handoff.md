# Offline Windows T2 handoff

The native colleague edition is a Windows x86-64 offline package. It includes
Python, the complete resolved Windows runtime, and the three validated T2 choices
from `resources/models`: default nnU-Net fold 1, fold 0+1 ensemble, and the legacy
small RatLesNetV2 release. T1 weights are neither bundled nor downloaded.

The `t2-only` application profile disables T1 model selection and generation in
both the UI and the study service, including already registered models in old
studies. New-study dialogs default to T2. Existing study data and conventional
T1 analysis code are retained; the macOS development `full` profile is unchanged.
Atlas mapping stays hidden in both profiles.

## Build the runtime on Windows

Run `.github/workflows/windows-runtime.yml`, or on a Windows build machine with
Conda, `conda-pack==0.8.1`, and `setuptools==80.9.0` available to its build Python
(conda-pack still requires `pkg_resources`):

```powershell
python scripts/packaging/build_windows_runtime.py --conda C:\Miniforge3\Scripts\conda.exe
```

The Windows-specific `environment-win64.yml` is a build input, never a colleague
installation step. Conda supplies Python and the Visual C runtime; pip owns the
scientific/Qt packages, avoiding two package managers replacing the same stack.
Torch and torchvision are pinned together. T1-only MONAI and gdown requirements
are absent. Transitive versions are recorded in `pip-freeze.txt` and
`conda-explicit.txt` alongside the packed runtime.

The build runs `pip check`, CPU Torch and nnU-Net import checks, and the actual
T2 desktop startup check. It then relocates the packed runtime to a different
path containing spaces, runs `conda-unpack`, and repeats those checks. A runtime
manifest is written only after success. Scientific accuracy is not established
by these software checks.

## Assemble the colleague ZIP

Download the `windows-t2-runtime` artifact into `dist/runtime`. On the machine
holding the validated local T2 releases, run:

```bash
python scripts/packaging/build_windows_handoff.py \
  --target native --runtime-directory dist/runtime
```

Normal builds require a clean committed snapshot. `--allow-dirty` explicitly
creates a development snapshot and records that fact in the manifest. The builder
rejects T1 model arguments and rejects missing, changed, or unverified runtimes.
Dependency and startup-check hashes must match the Windows runtime build. Model
releases and payload files are checksummed. Large runtime/model files are streamed
into the ZIP rather than all being held in memory.

`--without-bundled-models` creates a **validation-only** archive for packaging
tests; its installer refuses to treat it as a colleague release.

## Colleague installation

The colleague downloads one ZIP, fully extracts it, and double-clicks
`Setup-LYS-IRM.cmd`. Setup performs no network requests, dependency solving, pip
installation, Git clone, or model downloads. ITK-SNAP is an optional separate
installation; its availability cannot fail the LYS setup.

Setup verifies the payload, extracts a fresh runtime to its final prefix beneath
`%LOCALAPPDATA%\LYS-IRM\releases`, relocates it, validates every included T2 choice,
and executes `python -m lys_bbb_app.windows_smoke`. Only then does it update
`active-install.json` and create the Desktop and Start-menu shortcuts. Old
installations and study data are preserved. A failed installation leaves its
diagnostics in `logs/setup-*.log`. Launcher stdout/stderr are also retained.

Runtime/model paths come from the selected installed release; no user-wide Python
or Conda activation is needed. Thread counts are capped at two for CPU inference.
The installer needs 8 GiB free in addition to the downloaded/extracted package.
Never open the same study directory concurrently from multiple machines/processes.

## Regression behind the previous failure

The e1c72904 ZIP deliberately set `atlas_mapping=False` but asserted it was true
in setup, preventing shortcut creation. Startup checks now live in a named Python
module, check the intended T2 profile, and report descriptive failures. The same
module runs on the build machine, after relocation, and on the colleague's PC.
