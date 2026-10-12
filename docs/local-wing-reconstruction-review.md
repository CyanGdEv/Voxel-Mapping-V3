# Local wing reconstruction review

Reviewed, checksum-pinned drawing traces can now produce a local vertical surface
study without accepted geographic registration. This reuses the Wicker shop
approach without its shop-specific dimensions or opening assignments. It is a
partial review model, not accepted autonomous reconstruction or a complete wing.

`voxel_mapper.local_wing_review` validates each original PDF, full-page rendered
pixel hash, page, reviewed caption and source state before measuring the pinned
trace points. The seed explicitly declares each view's printed scale. Widths are
compared using endpoint sampling bounds; conflicting sheets withhold both meshes.
The code never stretches a plan to fit an elevation. Sampling bounds describe
the reviewed endpoints, not physical accuracy or as-built confidence.

The elevation supplies the courtyard facade and openings. Polygon subtraction
keeps every opening empty, including polygonal archway traces. Constrained
triangulation preserves their area. The plan supplies frontage and range depth.
The roof plan supplies a relative ridge-position hypothesis. Two main roof slopes
use the traced elevation eaves and ridge; equal opposite eaves are an explicit
display hypothesis. Wall thickness, roof end junctions, overhangs, the outer
facade, end walls and interiors remain omitted. Colours/materials are display
proxies. No geometry is eligible for accepted park placement.

## Mutiny north courtyard range

The seed is `evidence/mutiny-north-wing-review-seed.json`. The 2017 CTD AL05
ground-floor view and AL06 existing north courtyard elevation are used together.
AL05 also has an unscaled first-floor/title claim: its page title does not select
the measured ground-floor view. The 2012 Smytheman 3023-10 existing roof plan is
used only for a relative ridge fraction; cross-date correspondence is unresolved.

| Drawing-derived quantity | Value |
| --- | ---: |
| Plan frontage | 32.052 m |
| Elevation frontage | 32.076 m |
| Plan minus elevation | -0.023 m |
| Combined endpoint sampling interval | ±0.280 m |
| Traced range depth | 5.840 m |
| Eaves above drawn floor | 3.971 m |
| Ridge above drawn floor | 7.009 m |
| Two-endpoint vertical sampling interval | ±0.093 m |

The reviewed seed retains 16 aperture traces (12 windows, three doors and archway
3). Their IDs reflect drawing labels; the repeated w3.06 label is represented as
two separate traces, not automatically resolved physical identities. The arch is
a polygonal inner-opening review, not exact masonry or a fabricated full arch
structure. The wall contains 97 triangles; the main roof candidate contains four.

## Run and automate replay

```sh
python scripts/build_local_wing_review.py \
  --recipe evidence/mutiny-north-wing-review-seed.json \
  --sources /path/to/pinned/pdfs --output /new/review/directory \
  --isolated-world
python scripts/render_local_wing_review.py \
  --model /new/review/directory/local-wing-model.json --output preview.png
```

Original PDFs in `--sources` use `<sha256>.pdf` names. The optional isolated world
uses the existing dominant-axis surface rasterizer at one block per nominal
source metre. Thin display surfaces and apertures alias at this resolution.
All written blocks and unwritten air are checked by the native writer before
packaging. This is a new local study world, never a cumulative park update.

Each area's optional `local_wing_review_seeds` list contains up to eight recipe
paths relative to the area configuration. The controller pins the seed files,
requires their original PDFs in that area's acquired corpus, replays unchanged
models, and exposes reports in the sweep. Missing sources remain explicit.
Changed seed/source/output receipts reject. These reviews cannot satisfy required
families, complete the area or bypass production reconstruction/registration gates.

The seed points were visually reviewed for this study. Their discovery is **not
automatic**. General automatic view isolation, facade/opening boundary recovery,
cross-view correspondence and roof-junction solving remain the next work. An area
cycle can replay a reviewed seed automatically; that is a narrower capability.
