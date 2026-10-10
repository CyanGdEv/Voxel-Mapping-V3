# Shop orientation context and checkpoint-source search

This pass reproduces three exact planning records: the main shop outline,
its adjacent projection, and the solid interior line. The source PDF, point crop,
roof report and preceding edge review are checksum-bound. The smaller roof
envelope is reconstructed from eligible class-6 crop returns before inspection.
Source line roles remain unclassified; no physical ridge, doorway or wall is
accepted merely from geometry or proximity.

## Direction evidence

The PDF contains three native northing labels: 1550N, 1600N and 1650N. Their
centres have identical native X and increasing native Y. The interval implies
0.08820209 m per PDF point, consistent with the paper-labelled 1/250 scale
(0.08819444 m per PDF point). These text centres are context, not survey controls.

| Boundary hypothesis rotation | Mapped increasing-local-north vector | North half-plane consistent |
| --- | --- | --- |
| 1.36045° | (-0.02374, +0.99972) | Yes |
| -178.63938° | (+0.02375, -0.99972) | No |

Only the near-1.36° hypothesis is direction-consistent if the labelled local
northing axis points generally north in BNG. This is a useful orientation
constraint, not absolute registration acceptance. The exact bearing relationship
between the local site grid and BNG/true north remains unverified. The reversed
hypothesis and its failure are retained; no registration points are manufactured.

## Geometry cues that do not establish correspondence

The interior line midpoint is only 0.0587 PDF points from the source outline
centroid (about 5 mm at printed scale). A nearly centred, unoriented line cannot
identify the two ends of the building under a 180-degree reversal.

Native return bands are compared with that line at the 80th, 90th and 95th
height percentiles. At the 95th percentile, 26 returns have median line distances
0.154 m and 0.145 m for the two hypotheses. This small difference does not
establish roof-ridge identity, positional uncertainty or independent verification.

The planned adjacent projection is about 5.97 m² at printed scale. Under the two
hypotheses its centroid is 8.54 m or 18.05 m from the 61-return lower cluster;
neither transformed projection overlaps that cluster's native convex envelope.
The lower cluster therefore cannot be identified as that planned projection from
these comparisons. The nearer result is not promoted to a physical match.

## Independent imagery search

The official Environment Agency vertical-photography index was queried using
EPSG:27700 envelope intersection, first for the native crop and then for its
containing 1 km tile (407000–408000 E, 343000–344000 N). Both responses contained
zero features, with no API error or transfer-limit indication. The tile query,
parameters and full response are retained in
`evidence/wicker-aerial-catalogue-query.json`.

Catalogue: https://environment.data.gov.uk/KB6uNVj5ZcJr7jUP/ArcGIS/rest/services/Vertical_Aerial_Photography_Catalogues/FeatureServer/0

This rules out coverage returned by that particular catalogue/query. It does not
rule out other providers, unpublished photography, a newer index, or independent
survey evidence. No imagery or checkpoints are claimed to have been acquired.

## Placement status and replay

The north-consistent hypothesis is now distinguishable as a direction candidate.
Physical roof/wall identity, overhang offsets, native edge uncertainty and
separately sourced checkpoints remain unresolved. Zero controls/checkpoints are
accepted and no world geometry is generated. The next evidence target is an
approved shop roof/elevation or as-built survey with identifiable boundaries and
a documented independent coordinate reference; repeated boundary fits alone
cannot supply that verification.

```sh
python scripts/review_wicker_orientation.py \
  --pdf 1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d.pdf \
  --cloud cloud-crop/ea-point-cloud.las \
  --roof-report evidence/wicker-roof-candidates.json \
  --plan-review evidence/wicker-roof-plan-review.json \
  --aerial-query evidence/wicker-aerial-catalogue-query.json \
  --output orientation-cues.json
```

The replay consumes the retained catalogue response, not a mutable live query.
Full queue: `evidence/wicker-orientation-cues.json`.
Validation: `evidence/wicker-orientation-validation.json`.
