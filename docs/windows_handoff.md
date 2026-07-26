# Windows 11 colleague handoff

The supported Windows handoff is a verified source-bootstrap ZIP. It presents a normal
Desktop and Start-menu shortcut, while running the scientific application in Ubuntu on
WSL2/WSLg.

WSL2 is required because the exact registration contract invokes native
`antsRegistration` and `antsApplyTransforms` from ANTs 2.6.5. Conda-forge publishes
that version for Linux and macOS, but not for `win-64`. Replacing it with another engine
would change the registered scientific method rather than merely package the app.

## Build the handoff ZIP

Build only from the clean release snapshot:

```bash
conda run -n lys-bbb python scripts/packaging/build_windows_handoff.py
```

The command writes `dist/LYS-BBB-Windows-<version>-<commit>.zip` and prints its SHA-256.
The builder refuses a dirty tree so the archive always identifies one exact commit.

## Colleague installation

The colleague:

1. downloads and fully extracts the ZIP;
2. double-clicks `Setup-LYS-BBB.cmd`;
3. accepts the Windows administrator prompt if WSL2 is not installed;
4. restarts Windows and double-clicks the setup file again if requested; and
5. launches the app from the new `LYS BBB` Desktop icon.

The first setup needs Internet access, at least 12 GiB free on the Windows system drive,
and typically 20–45 minutes. It installs:

- Ubuntu under WSL2 and uses Windows 11 WSLg for the GUI;
- checksum-pinned Miniforge 26.1.1-3;
- the exact ANTs 2.6.5 contract;
- pinned PySide6 and scientific Python packages available for Linux;
- CPU-only PyTorch for the Intel Iris Xe laptop;
- checksum-pinned ITK-SNAP 4.4.0; and
- the reviewed, checksummed T1 brain-mask source/model when its upstream download is
  available.

The launcher caps ANTs/OpenMP/MKL work at two threads to leave usable memory on the
8 GiB ZenBook. CPU inference remains slower than on a dedicated ML workstation.

## Data and external scientific releases

Windows `Downloads` is linked to `/home/lysbbb/Downloads`; all Windows drives remain
available as `/mnt/c`, `/mnt/d`, and so on. Study SQLite files should be opened by only
one machine/process at a time.

The private/external frozen T2 release and AIDAmri atlas resources are not in this
repository and are deliberately not copied from a developer machine. Transfer those
releases separately, verify them through the app's existing registration flow, and keep
raw MRI data read-only.

## Rebuild after a release update

Make changes on the development branch, test them, and then deliberately update the
release branch snapshot. Re-run the builder and hand over the newly named commit ZIP.
Installing a newer bundle preserves the previous application source under
`/opt/lys-bbb/app.previous.<UTC timestamp>` before switching the dedicated environment
to the new version.
