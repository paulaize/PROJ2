# Deprecated Source

Retired source files and old one-off scripts can be moved here when they are no
longer part of the active LYS BBB pipeline.

Do not put generated MRI outputs, masks, reports, cache files, or raw Bruker
data here. Generated outputs belong under ignored `output/`, `derivatives/`, or
`reports/` folders and can be regenerated or removed when no longer useful.

Before moving code here, update active imports, documentation, and tests so the
current pipeline does not depend on deprecated files.

Current deprecated source:

- `deprecated/sherm/`: retired SHERM-inspired skull-stripping code and preview
  CLI. It is kept only for historical reference or controlled comparison; active
  quantification requires supplied corrected or predicted pre-space masks.
