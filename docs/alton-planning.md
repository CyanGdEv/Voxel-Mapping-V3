# Alton Towers planning integration

The Actions location default is now Alton Towers. Location-only generation automatically selects the Staffordshire Moorlands adapter and fetches official HTTPS PDF URLs from the recovered historical catalogue. Other locations retain their existing acquisition behavior.

## Recovered data

The original August 7 corpus contains 154 document entries across 44 applications: 153 PDF entries (141 distinct PDF hashes) and one non-PDF document. This is a historical subset, not complete/current discovery. The catalogue keeps application references, document titles, roles, states, official attachment URLs and original SHA-256 hashes. Original PDFs are not bundled in this repository.

For repeatable offline inspection of the previously downloaded corpus:

```bash
python -m voxel_mapper.alton --cache /path/to/planning-prefetch-selected --output alton-planning
```

The same cache may be supplied to world generation with `--planning-cache`. Without it, the adapter downloads the catalogue URLs automatically. Downloads require HTTPS on the official host, reject redirects, enforce a 10 MB budget and verify the recovered hash. Changed or missing documents are reported rather than silently substituted. Acquisition stops after a 15-minute planning budget and reports omitted entries. The existing world build area limit remains 4 km²; this is not a whole-resort coverage guarantee.

## Registration and extraction

The adapter inspects up to two pages per PDF for embedded geographic registration, native survey labels, grids, elevations and material evidence. Scale-only PDF viewports are not geographic registration. Existing plan/landscape/terrain sheets with full six-digit E/N labels also receive an automatic BNG alignment hypothesis. A bounded majority fit identifies shifted border-label origins, explicitly records exclusions and checks withheld labels. Ambiguous fits, insufficient controls and fits outside the requested area are rejected. Insets, rotated pages, raster-only registration and unlabelled drawing origins are not solved by this method.

The retained alignment includes PDF-to-coordinate axis coefficients, finite control extents, nominal residuals and a hypothesised WGS84 extent. It is not verified registration: label origins can differ from grid lines and EPSG:27700 is not independently established. No extrapolation or automatic promotion to world polygons is performed.

## Actual corpus result

148 of 153 PDF entries were inspected; five exceeded the decompressed-page content budget. Three application entries share one surveyed sheet (SHA-256 `82cac12a14cd3d9d4232f409e681bd977f6c7f4f03be7b9049a6f845375543a9`) and yield the same alignment hypothesis: SMD/2022/0230, SMD/2021/0636 and SMD/2021/0211. These are one distinct survey, not three independently verified alignments. Its retained E/N label fits have maximum withheld residuals below 0.006 nominal metres. That does not measure absolute geographic accuracy.

Zero planning physical features entered a new world. The older 722-feature authority export is not accepted: all features are LineStrings, some are small report-text outlines, and approval/confidence flags do not establish physical semantics or as-built state. Remaining work is to verify survey/grid attachment and CRS, recover clipped drawing geometry with holes, classify actual paths/plazas/structures, reconcile dates and as-built evidence, and confirm reuse provenance before physical world insertion.
