# Retained source recovery and anchor audit

A park job can now import a retained planning archive before attempting downloads. The importer checks a supplied archive SHA256, bounded catalogue/member sizes, unique member names, declared official HTTPS hosts and each content-addressed PDF checksum/header. It preserves application links, titles and declared construction states as source metadata, never as current-state authority. It copies missing blobs atomically, repairs corrupt retained copies from verified archive bytes, and resumes unchanged files. No archive paths are extracted into arbitrary directories. Recovery makes no live-download claim.

```bash
python -m voxel_mapper.planning_archive \
  --corpus park-build/corpus --archive planning-data.zip \
  --sha256 YOUR_ARCHIVE_SHA256 \
  --official-host publicaccess.staffsmoorlands.gov.uk

python -m voxel_mapper.anchor_audit \
  --corpus park-build/corpus --output park-build/anchors \
  --bounds -1.902 52.982 -1.877 53.004
```

The anchor audit separates three kinds of evidence:

| Evidence | Treatment |
| --- | --- |
| Explicit GeoPDF viewport metadata | Existing bounded internal-consistency checks; independent accuracy remains unverified |
| Explicit CRS plus leader-connected crosshairs or endpoint-labelled grids | Conservative geometry/coordinate checks; no nearest-mark fallback |
| Repeated six-digit E/N axis labels | Bounded axis-consistency hypothesis, with BNG explicitly hypothetical and label centres unverified |
| Easting/Northing in application forms | Application-location hints with no drawing-point attachment and no accepted CRS |

Native text lacking an explicit EPSG declaration and coordinate labels skips expensive mark/grid interpretation. Axis labels are considered separately. This preflight does not claim absence of raster, custom-font or hidden coordinates. Every exported page is bound to a checksum-checked original PDF and application context. Nearby applications can enter a broad search/archive: `park_membership_verified` remains false, and neither a broad park bounding box nor an approved application proves that a drawing belongs in the park or was built.

Resumable `anchor_pages` rows are keyed by PDF, page and version/bounds contract. Corrupt original blobs are excluded from exported cached results. Outputs are `anchor-candidates.jsonl` and `anchor-report.json`, with SHA256 receipts. The audit never provides accepted registration or world geometry.

## Native coordinate origin correction

Delayed PDF text callbacks sometimes returned a coordinate label at `[0, 0]` rather than its text-show position. Coordinate labels now bind to the actual positioned `Tj`/`TJ` operator matrices. Supported standard Type1 ASCII encodings remain deliberately narrow. Unpositioned text advances, leading kerning, quote operators, custom encodings, form/XObject text, clipped text and raised text receive no guessed origin. Content, text, fragment and graphics-state budgets remain bounded.

This repairs the existing controls, grid, crosshair and external-check tests. Grid anchors still require a unique labelled line endpoint, and crosshair anchors still require an explicit leader; a correct text origin does not turn the label itself into a surveyed corner. Drawing triage version v5 invalidates cached analyses from the previous origin policy.

## Park-job settings

Within `acquisition`, an optional retained archive entry is:

```json
"retained_archives": [{
  "file": "planning-data.zip",
  "sha256": "YOUR_ARCHIVE_SHA256",
  "catalogue_member": "metadata/alton-planning-catalogue.json"
}]
```

Set the existing `official_hosts` allowlist. Archive import occurs before download/inspection. Enable the separate audit stage with:

```json
"anchor_audit": {
  "enabled": true,
  "bounds_wgs84": [-1.902, 52.982, -1.877, 53.004],
  "max_pages": 10000
}
```

The example park job enables this audit. As with other job changes, use a fresh work directory when changing job configuration. The retained archive file must be available at the configured path.

## Actual retained-source result

The expanded V4 archive contains 275 catalogue links and 237 unique checksum-valid PDFs covering 602 pages. Twelve files were already in the bulk corpus; recovery copied 225, increasing available source coverage to 309 PDFs and 818 pages. Repeat import resumed all 237 files. All 818 pages were audited and resumed without document errors.

Three application-form location hints were retained. No usable embedded or explicit mark/grid candidate was found. One 19-label topographical sheet produced an internally consistent axis hypothesis. It belongs to Wildwood/Farley Eco House applications SMD/2021/0211, SMD/2021/0636 and SMD/2022/0230, not established ride/park anchors. Label-centre consensus excludes one displaced origin per axis; CRS, physical grid attachment, independent checkpoints and park membership remain unverified. No world geometry was accepted.

All 89 focused tests and the full 513-test suite pass. Seven new tests cover reliable operator origins, unsupported advances/encodings, archive hashes/paths/hosts, recovery/resume/repair, location-hint separation, corrupt source exclusion and park-job integration. The four previously failing drawing controls/grid/marks/checks tests now pass through the origin correction. See `evidence/anchor-audit-validation.json` for source hashes, measured reports and the retained axis hypothesis.
