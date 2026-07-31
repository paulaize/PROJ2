# Native Windows 11 handoff

This is the canonical colleague distribution. It runs directly on 64-bit Windows 11
with CPython 3.11 and pinned `antspyx==0.6.3`; it requires neither Ubuntu, WSL2, nor
separate ANTs executables. The same ANTsPyx runtime and hashed scientific method
contracts are used during macOS development.

The complete application profile is enabled, including atlas mapping. ANTsPyx executes
only the reviewed compiled operations used by LYS IRM:

- `N4BiasFieldCorrection`;
- `antsRegistration`;
- `antsApplyTransforms`; and
- `CreateJacobianDeterminantImage`.

The adapter passes explicit argument arrays and records engine/version, arguments,
stdout/stderr, return code, runtime, and checksums. It does not substitute unrecorded
high-level library defaults. Registration candidates and propagated labels retain their
existing geometry validation and human-review gates.

## Build the native ZIP

Build only from a clean committed snapshot:

```bash
conda run -n lys-irm python scripts/packaging/build_windows_handoff.py \
  --target native \
  --t1-model-release "/path/to/rs2net-m-seam-v1"
```

The output is
`dist/LYS-IRM-Windows-Native-<version>-<commit>.zip`. Its manifest records the exact
source snapshot, complete feature profile, runtime, models, and payload checksums.
The default fold-1 nnU-Net, optional fold-0+1 ensemble, and legacy small T2 model are
always taken from `resources/models`; the build does not accept Downloads or Kaggle as
their implicit source.

Setup accepts only the CPython 3.11 Windows x86-64 ANTsPyx wheel named
`antspyx-0.6.3-cp311-cp311-win_amd64.whl` with its checked-in SHA-256. Both model
releases and all packaged T2 SHA-256 entries are validated before packaging and again
during installation.

## Colleague installation

The colleague:

1. downloads and fully extracts the ZIP;
2. double-clicks `Setup-LYS-IRM.cmd`;
3. leaves setup open while it downloads the native dependencies;
4. optionally accepts the administrator prompt for ITK-SNAP; and
5. launches `LYS IRM` from the Desktop icon.

The private runtime and application are installed under
`%LOCALAPPDATA%\LYS IRM`. Setup imports pinned ANTsPyx, starts the complete app
offscreen, confirms that atlas mapping is available, and only then creates shortcuts.
No WSL component is installed. Thread counts are capped for lower-memory colleague
machines.

Installing a later ZIP preserves the previous application source under a timestamped
`.previous` directory. Study data remains separate; never open the same study root from
multiple processes or computers simultaneously.

## Scientific acceptance

Software tests cover compiled N4, registration, transform application, label
interpolation, output geometry, operation provenance, and non-commuting transform order.
They do not replace real-animal anatomical validation. Continue to inspect predefined
landmarks, reflections, scale/shear/determinant, support coverage, every acquired T2
slice, and native-T2 composite labels before approval.
