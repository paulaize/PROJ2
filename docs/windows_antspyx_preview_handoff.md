# Native Windows 11 ANTsPyx preview

This package is a separate migration preview. The colleague demonstration version stays
frozen on branch `release/windows-native-no-ants-v1` at commit `1a1fa96`. Development
continues on `feat/antspyx-registration-backend`.

The preview runs in native 64-bit Windows CPython. It installs no Ubuntu, WSL2, or
standalone ANTs executables. Its private Miniforge environment includes pinned
`antspyx==0.6.3`, the Microsoft-compatible Conda runtime libraries, and the existing app
dependencies. Setup verifies the bundle, installs dependencies, imports ANTsPyx, opens
the app offscreen, and checks that the atlas workflow is present before creating the
Desktop icon.

## Scientific scope

ANTsPyx is a new, separately hashed runtime method. Its restricted adapter calls only
the compiled `N4BiasFieldCorrection`, `antsRegistration`, `antsApplyTransforms`, and
`CreateJacobianDeterminantImage` entry points. It passes the existing fixed argument
arrays, so masks, seeds, pyramids, transforms, interpolation, and output domains are not
replaced by library defaults.

The preview retains:

- atlas→native pre-T1 rigid and rigid→affine candidates;
- native pre-T1→native T2 rigid registration;
- `GenericLabel` interpolation for masks and labels;
- direct one-resample atlas-label propagation into original native T2;
- untouched native T2 lesion artifacts; and
- exact candidate, all-slice, and composite human approvals.

Synthetic native-library tests cover N4, rigid registration, transform output,
intensity and label application, output geometry, runtime provenance, and a
non-commuting direct-transform order proof. This is software parity evidence, not
real-mouse accuracy evidence.

## Build and install

Build from a clean committed snapshot:

```bash
conda run -n lys-bbb python scripts/packaging/build_windows_handoff.py \
  --target native-antspyx-preview \
  --t1-model-release "/path/to/rs2net-m-seam-v1" \
  --t2-model-release "/path/to/LYS_v1_RatLesNetV2_inference"
```

The output is
`dist/LYS-BBB-Windows-Native-ANTsPyx-Preview-<version>-<commit>.zip`. The manifest
records the exact commit and activates `windows_native_antspyx_preview_v1`.
Setup accepts only the CPython 3.11 Windows x64 wheel named
`antspyx-0.6.3-cp311-cp311-win_amd64.whl` with SHA-256
`39a29ba5abbf3475dea70cf0d0a2472e34a5c854f99d2f08204a288f1f5aeac4`.

The two model arguments are validated before packaging. The archive includes the exact
frozen T1 RS2-Net/M-seam release and five-fold T2 RatLesNetV2 release. Setup stages and
validates them again before installing them at:

- `%LOCALAPPDATA%\LYS BBB\models\rs2net-m-seam-v1`
- `%LOCALAPPDATA%\LYS BBB\models\ratlesnetv2-lys-v1`

The application automatically registers the installed T1 release when brain extraction
is first run and the installed T2 release when lesion inference is first run. A differing
previous release is preserved under a timestamped `.previous` directory.

The colleague fully extracts the ZIP, double-clicks `Setup-LYS-BBB.cmd`, leaves the
terminal open for dependency downloads, and then uses the
`LYS BBB - apercu ANTsPyx` Desktop icon. The installer and launcher cap ITK, OpenMP,
and MKL at two threads for the 8 GiB ZenBook.

## Accuracy gate before scientific use

Do not approve the migration from optimizer completion or support Dice alone. On the
same explicitly paired mice, compare CLI and ANTsPyx outputs with identical approved
inputs:

1. review atlas→pre-T1 rigid and affine independently using predefined bilateral
   landmarks and physical target-registration error in millimetres;
2. reject reflections and inspect determinant, scale, shear, atlas-support coverage,
   and failures;
3. review transformed-T1 edges and brain/support boundaries on every acquired T2 slice;
4. verify direct major labels on every native T2 slice, especially partial-FOV edges;
5. compare mapped lesion results only after both registrations and the composite pass;
6. reopen the study and verify unchanged hashes and approvals.

Use corrected T1 masks as immutable, versioned inputs. Continuing to correct masks for
the future nnU-Net T1 segmentation model is independent of this migration. Replacing an
approved mask must create a new version and invalidate downstream registrations; it must
never overwrite the mask used by an earlier comparison.

The preview can be handed to a colleague for installation and workflow testing after
the Windows wheel/install smoke test passes. It must remain labelled provisional until
the matched real-mouse parity set passes the accuracy gate.
