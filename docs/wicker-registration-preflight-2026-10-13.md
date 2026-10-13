# Wicker Man registration preflight — 13 October 2026

The recovered eleven Wicker Man PDFs contain 58 pages. Before this change, none
had a supported visible scale. One dense page also raised a text-budget error,
preventing the qualification audit from completing.

The Existing Site Plan now supplies a raster-supported `1/250 @ A1` caption.
Its original PDF SHA256 is
`bfca0863216de7d3fe5667190286c7c639cd084730965c3f89984504bd3dd953`,
page 1. The sheet measures approximately 594.078 × 841.022 mm, selecting A1;
`1/500 @ A3` remains visible but does not apply to this sheet. The resulting scale
is approximately 0.0881944 metres per native PDF point. This establishes a usable
printed scale, not geographic location, survey accuracy or permission to reuse
geometry.

## Changes

The scale caption is split into several multi-character native runs. The new
adapter joins only tightly adjacent horizontal runs with the same font,
baseline and rendering properties, within two percent size variation. It adds
no characters. Each original run is screened at its own recorded size and glyph
origins. Coincident duplicate runs retain all original references and must all
pass. Gaps, differing baselines/fonts, hidden text, unsupported sheet dimensions
and changed crop/UserUnit remain withheld. At most sixteen composite captions
and sixty-four source parts per caption are accepted for screening.

The title block uses a CID-keyed embedded CFF font without a usable Unicode
re-encoding path. Native CIDs are now validated against the original CFF charset
and emitted directly through Identity-H in the comparison renderer. They are
never interpreted as charset ordinal positions. Only standard-matrix, bounded
CID-keyed fonts with known native CIDs are supported. Original font bytes and
positions remain unchanged; no replacement font is used. Existing raster
thresholds, alternative-font ambiguity checks, overpaint rejection and rotation
restoration remain unchanged. Glyph and scale contract versions are advanced to
invalidate dependent observations.

A page-level scale-review error is now retained as `withheld_scale_review_error`,
including its reason. Other pages continue. Original checksum failures remain
fatal, including an original changed while a failing scale review runs. The
qualification version is advanced to prevent old observations from being reused.

## Real result and remaining work

- Geometry inspection inventories 15,360 unplaced candidates: 2,245 polygons and
  13,115 lines. One page reaches a candidate budget; these counts are not physical
  components or accepted building specifications.
- Qualification completes all 58 pages. One has a supported visible scale;
  56 remain missing, ambiguous or unsupported, and one has a retained scale-budget
  error. The proposed Woodland Path and Landscape sheets expose their title-block
  scales but still contain other unresolved ratio labels and remain withheld.
- All 58 pages lack a unique checksum-bound verified source policy and an
  independent survey reference bundle. No source policy or reuse permission was
  invented. **Zero real horizontal frames qualify.**
- Station discovery emits zero supported native station candidates or references.
  Ten pages require unsupported visibility handling, one has unsupported native
  coordinate text and one raster page yields no supported OCR coordinate lead.
  This is not proof that the original drawings contain no possible controls.
- Qualification and station discovery both reuse all 58 observations on unchanged
  resume and in a fresh output directory. No components, training labels or park
  blocks are accepted.

The next registration input is a verified source policy with permitted geometry
reuse, plus at least three non-collinear physical controls and two independent
checkpoints in a projected metre CRS. Their identities, uncertainty and source
hashes must be bound to the drawing; survey sources for checkpoints must remain
independent. Application location mentions and map shape agreement cannot replace
these requirements. View scope, existing/proposed state, physical component
identity, terrain and vertical datum remain separate reconstruction checks.

## Reproduction

Replay the retained source bundle into a corpus using
[source-bundles.md](source-bundles.md), then use fresh audit directories:

```bash
python -m voxel_mapper.drawing_geometry \
  --corpus /retained/corpus --output /work/wicker-geometry --max-pages 100
python scripts/audit_registration_qualification.py \
  --corpus /retained/corpus --geometry /work/wicker-geometry \
  --work-directory /work/wicker-qualification --output /work/qualification.json
python scripts/audit_survey_landmark_discovery.py \
  --corpus /retained/corpus --geometry /work/wicker-geometry \
  --work-directory /work/wicker-stations --output /work/stations.json
```

These evidence-only commands omit the unavailable verified manifest and survey
registry. Supply `--manifest` and `--references` to the qualification audit only
when those verified inputs exist; station discovery also accepts `--manifest`.
The retained original bytes and detailed working outputs remain outside Git.
The summary, original pins, native scale references and replay checks are in
[evidence/wicker-registration-preflight-2026-10-13.json](evidence/wicker-registration-preflight-2026-10-13.json).
