# Deprecated SHERM-Inspired Masking

This folder contains the retired SHERM-inspired rodent skull-stripping code and
its preview CLI.

These files are not part of the active LYS BBB pipeline anymore. They are kept
only for historical reference and, if needed, a controlled comparison against
the current MouseBrainExtractor correction and nnU-Net mask-development path.

Active quantification now requires a supplied pre-space brain mask from manual
correction or a QC-approved prediction. The smooth bias correction,
post-to-pre registration, intensity normalization, enhancement maps, and cohort
metrics remain in `src/lys_bbb/flash_pair.py` and `src/lys_bbb/flash_cohort.py`.

Do not use raw SHERM outputs as final masks or nnU-Net labels. If any mask from
this folder is used for a one-off comparison, it must be manually checked and
corrected before quantification.
