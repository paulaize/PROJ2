# Native Windows 11 handoff without ANTs

This first colleague-test package runs directly on 64-bit Windows 11. It installs no
Ubuntu, WSL2, ANTs command-line tools, or `antspyx`.

The package activates the `windows_native_no_ants_v1` feature profile. The profile
removes the Atlas Mapping tab, atlas review queues, and every connected atlas action.
It retains:

- study creation, import, validation, persistence, and audit history;
- reviewed T1 brain-mask generation and optional ITK-SNAP editing;
- post-Gd to pre-Gd T1 registration, which already uses SimpleITK rather than ANTs;
- provisional T1 enhancement calculation;
- native-space T2 inference, review, correction, and lesion volume; and
- result display and approved T2 CSV export.

The omitted atlas→pre-T1, pre-T1→T2, and label-propagation stages currently invoke ANTs.
They must not be presented as available in this release.

## Build the native ZIP

Build only from a clean release snapshot:

```bash
conda run -n lys-irm python scripts/packaging/build_windows_handoff.py \
  --target native-no-ants \
  --t1-model-release "/path/to/rs2net-m-seam-v1" \
  --t2-model-release "/path/to/LYS_v1_RatLesNetV2_inference"
```

The command writes
`dist/LYS-IRM-Windows-Native-No-ANTs-<version>-<commit>.zip`, prints its SHA-256,
and records the exact branch, commit, target, feature profile, and file checksums in the
archive manifest. The builder refuses a dirty tree unless `--allow-dirty` is explicitly
used for local packaging tests.

## Colleague installation

The colleague:

1. downloads and fully extracts the ZIP;
2. double-clicks `Setup-LYS-IRM.cmd`;
3. leaves the setup window open while it downloads the native dependencies;
4. optionally accepts the administrator prompt for ITK-SNAP; and
5. launches `LYS IRM` from the new Desktop icon.

The Python application and scientific environment are installed per user under
`%LOCALAPPDATA%\LYS IRM`. Only the optional official ITK-SNAP installer requests
administrator elevation. Setup requires Internet access, at least 8 GiB free, and
typically 15–40 minutes.

The installer verifies the bundle, checksum-pins Miniforge and ITK-SNAP downloads,
creates a native `win-64` CPU-only environment, stages and validates both frozen model
releases, runs an offscreen no-ANTs startup smoke test, and creates Desktop and
Start-menu shortcuts. It caps ITK/OpenMP/MKL processing at two threads for the 8 GiB
ZenBook.

## Model releases and updates

The frozen T1 and T2 releases are included and installed under
`%LOCALAPPDATA%\LYS IRM\models`. The app detects them automatically. Model files are
covered by the archive checksums and by their scientific release validators. Atlas
resources are not included or needed because atlas mapping is disabled.

Installing a later ZIP preserves the previous application source as
`%LOCALAPPDATA%\LYS IRM\app.previous.<UTC timestamp>`. Study data is separate from the
application install; never open the same study directory from two processes or machines
at once.

Moving to `antspyx` is a second scientific and packaging phase. It should re-enable the
atlas feature only after its transforms, interpolation, output geometry, provenance,
failure behavior, and real-case results have been validated against the current ANTs
contract.
