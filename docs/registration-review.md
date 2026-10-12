# Independent registration review and Prospect Tower levels

`reconstruction.registration.review_registration` fits a planar, orientation-
preserving similarity between local metric points and projected target points.
It requires at least three controls spanning an area. At least two independently
identified checkpoints must then agree within the declared metre tolerance.
Missing checks, excessive residuals or unexpected scale withhold the fit.
Repeated point identities/coordinates, reused control checkpoints, collinear
controls and non-finite inputs are rejected. Raw point pairs and residuals remain
in the output for reproduction. `apply_registration` refuses a withheld result and coordinates outside the convex
hull of the verified target controls/checkpoints. Sources attaching a review also
withhold feature geometry outside that domain, avoiding unchecked extrapolation.

Controls/checkpoints are lists of `{"id":"landmark","local":[x,y],"target":[E,N]}`.
The default horizontal tolerance is 1 m, with expected scale 1 and a 2% relative
scale tolerance. These are configurable review thresholds, not guaranteed source
accuracy. Landmark identity, survey dates, projected metre CRS and vertical datum
must be checked separately. A passed fit does not establish surveyed elevation.

A Source can attach the result as `metadata.horizontal_registration_review`.
Feature validation then withholds failed or incomplete reviews even if a caller
has separately set `registration_status: accepted`. Legacy sources without this
metadata retain their existing explicit registration requirements; this update
does not retrospectively declare park-wide source alignment verified.

## Prospect Tower: measured progress

The original AL3.06 Rev B existing west elevation was downloaded again and matches
its retained SHA256. The page was visually checked, and six reviewed vector edges
were verified against their source path indices. The printed scale is 1:20.

| Relative reference | Height above reviewed column-base edge |
| --- | ---: |
| First balcony underside | 3.16 m |
| First balcony top | 3.44 m |
| Second balcony top | 6.48 m |
| Roof column top | 8.81 m |
| Roof cap upper edge | 10.75 m |

These are printed-scale conversions, **not annotated surveyed dimensions or ODN
levels**. The cap upper edge is not the decorative finial top. Column-base zero
is a selected drawing edge, not an assumed terrain height. Independent dimensional
verification and the absolute base level remain outstanding.

Retained values and source paths are in
`voxel_mapper/data/prospect-elevation-review.json`. Verify against the PDF:

```sh
python scripts/review_prospect_levels.py \
  --pdf /absolute/path/89797.pdf
```

The architect's restoration account confirms that balcony railings were
reinstated. Existing-condition December 2014 drawings therefore cannot alone
represent the restored tower. The account supplies construction-state context,
not geographic geometry or surveyed dimensions:
https://www.ctdarchitects.co.uk/portfolio/alton-towers-gothic-prospect-tower/

The retained OSM inventory contains no named Prospect Tower match. Public heritage
location searches and the inaccessible direct listing page did not yield an
independently verified control network in this pass. No listing pin was promoted
to a precise tower centre. Absolute placement remains withheld and no new park
world was exported. The recovered V17 world/evidence are intact; this source
review does not modify those existing world cells.
