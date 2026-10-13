# Numbered views and source-bound raster review

The next stage, [facade region discovery](raster-facade-source-feed.md), now
connects material-anchor contrast regions and numbered references to separate
local view studies and unseeded opening review candidates. Those studies do
not yet assemble a complete shop.

The raw PDF discovery feed now recognizes the Wicker revised shop's numbered
Revit elevation captions and numbered overall floor plan. Unnumbered `Overall`
titles are retained as sheet titles, not additional views. Caption numbers and
diagonal directions are printed claims; they do not verify a plan reference,
building identity, revision correspondence or geographic orientation.

The caption layout contract is `architectural-caption-layout-v2`. A separately
printed scale directly below an aligned visible caption is retained under
`adjacent_scale_candidates`. Duplicate scales remain ambiguous. This does not
change the inline scale or authorize measurement in `assemble-views`. Page
scales, catalogue source states and `PLANNING` titles are not inherited as
per-view state or scale.

## Original font handling

The glyph screen now supports embedded name-keyed Type1 CFF with explicit
`/WinAnsiEncoding`, a standard font matrix and ASCII glyph IDs matching the
original charset. It copies the original PDF font resource, encoding, widths
and embedded font stream into the comparison page. It does not substitute a
system font. Encoding dictionaries with Differences, unknown glyphs,
nonstandard matrices and ambiguous resources remain withheld. Existing
per-glyph and surrounding ink thresholds are unchanged. White and dark
overpaint tests remain required. Raster consistency is not semantic validation.
The printed-scale/alignment contract advances to `held-out-map-alignment-v10`
so registration qualification cannot reuse scale screens from the older glyph
adapter.

## Raster evidence

Each discovery page retains `source_image_placements`: occurrence IDs bound to
the original document SHA256, one-based page, original image number, pixel
dimensions, placement polygon and `pixel_edge_to_pdf_native_matrix`.
Coordinates use native PDF points with Y up. Repeated and inline images are
retained separately; no original image decoding is required for this inventory.
Image coordinates describe placement, not verified clipping, visibility or
facade geometry. Masks, textures, material photographs and neighbouring
buildings can all occur on an elevation sheet.

The inventory is limited to 512 placements per page. Exceeding that limit
withholds the whole placement list and makes the source inventory incomplete.
Image occurrences count against the discovery record budget. Raster-only
pages retain native text captions but cannot provide native faces to assembly.

Use `voxel-building-data render-view --config request.json --output fresh-dir`
to render a composited source region for review:

```json
{
  "version": "building-raster-view-v1",
  "path": "original.pdf",
  "sha256": "<64 lowercase hex characters>",
  "page": 1,
  "bounds_pdf_native": [250, 1100, 650, 2000],
  "width_pixels": 1600
}
```

The bounds are declared review inputs, not authenticated view scopes. The
original page rotation is preserved by default; optional `rotation_degrees`
supports 0/90/180/270. Rendering uses a uniform scale, preserves compositing,
and records the rounded pixmap origin in a reversible pixel-to-native matrix.
The output `view.png` and `receipt.json` are bound to the original checksum,
request hash and PNG hash. Original bytes are checked again before publication.
Width is limited to 200–3000 pixels, rendering to 9 million pixels, and original
PDFs to 32 MB. Existing output directories are never overwritten.

## Real Wicker result, 13 October 2026

The three checksum-pinned revised shop originals produce three discovered pages,
12,235 records including 87 image occurrences, and six visible view captions:
one floor plan, one roof plan and four numbered diagonal elevations. Each has
one visible adjacent 1:100 scale candidate. Four separate review crops were
generated from the original elevation sheet; they are outside Git. Their bounds
were selected for inspection and remain unverified as complete building scopes.

The source-backed assembly trial still generates **zero specs, models, training
labels or park blocks**. No raster outline or opening is yet interpreted as a
physical facade. Drawing state, plan-reference/revision correspondence, view
scope and cross-view dimensions remain unresolved. The existing native adapter
also requires a rectangular footprint; these additions do not generalize its
geometry acceptance. Next work must isolate the shop's facade and openings from
the ground, context buildings and material fills, with source-bound review of
the resulting geometry and dimension conflicts.

The machine-readable original-source receipt is
[`evidence/wicker-numbered-raster-views-2026-10-13.json`](evidence/wicker-numbered-raster-views-2026-10-13.json).
