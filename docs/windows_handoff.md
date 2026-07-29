# Optional Windows 11 WSL handoff

The native ANTsPyx package in [windows_native_handoff.md](windows_native_handoff.md) is
the canonical colleague distribution. This WSL2/WSLg target is retained only as an
alternative deployment shell for machines already managed through WSL.

It uses the same pinned `antspyx==0.6.3` registration runtime and the same complete
feature profile as macOS and native Windows. It does not install or invoke a separate
ANTs command-line package.

Build it explicitly:

```bash
conda run -n lys-irm python scripts/packaging/build_windows_handoff.py \
  --target wsl
```

The colleague fully extracts the ZIP, double-clicks `Setup-LYS-IRM.cmd`, completes any
requested WSL2 restart, and launches the Desktop shortcut. The installer verifies
ANTsPyx 0.6.3 by importing the package before running the offscreen application smoke
test.

Windows drives remain available under `/mnt/c`, `/mnt/d`, and similar mount points.
Study SQLite files must be opened by only one process or machine at a time.
