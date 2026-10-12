# Source-linked shop roof/plan edge review

The retained planning PDF is checksum-verified and its native shop candidate
`c631c9fa7adff4f77172e3d30eac1cf566847a40d391ddad7b18a596a7d7be52`
is reproduced from current extraction and linework recovery. The two native
survey envelopes are independently reconstructed from their original crop point
indices, eligible class-6 flags and membership hashes. No screenshot tracing,
rectangle substitution or point snapping is used.

## Paper-scale scope

The sheet explicitly lists both 1/250 at A1 and 1/500 at A3. Native PDF dimensions
are 841.02 × 594.08 mm, matching A1 within the two-millimetre paper-size tolerance.
The review therefore holds the 1/250 scale fixed at 0.08819444 m per PDF point.
Alternate paper labels and gradient ratios are not competing page scales.
Conflicting explicit scales for the same paper size, or a nonmatching page size,
are withheld by `page_scale`; paper-size matching is not physical verification.

## Boundary diagnostics

| Survey envelope | Free-fit scale difference from 1/250 | Fixed-scale overlap | Fixed-scale boundary Hausdorff difference | Equivalent orientations |
| --- | ---: | ---: | ---: | ---: |
| 505-return component | 0.27% | 93.16% | 0.827 m | 2 |
| 566-return expansion | 12.09% | 74.59% | 2.708 m | 4 |

Holding scale fixed prevents the larger envelope from absorbing its additional
returns through a 12% scale change. The smaller envelope remains a strong shape
comparison, but still has a near-180-degree orientation ambiguity. It also fails
the existing relative boundary-agreement diagnostic (5% of square-root area);
the threshold has not been weakened to turn it into an accepted fit.

For the best smaller-envelope hypothesis, the four source edges have these
distances to the observed convex envelope:

| Native source edge index | Length at printed scale | Median distance | Maximum sampled distance |
| --- | ---: | ---: | ---: |
| 0 | 16.85 m | 0.243 m | 0.525 m |
| 1 | 12.83 m | 0.163 m | 0.449 m |
| 2 | 16.84 m | 0.292 m | 0.827 m |
| 3 | 12.80 m | 0.461 m | 0.827 m |

Each edge is sampled at 33 locations. The queue retains native PDF endpoints,
transformed hypothesis endpoints, signed residual ranges and every equivalent
orientation. Edge numbers refer to the source ring, not identified physical
directions. Positive signed residuals mean inside the observed envelope.

These are **boundary self-fit residuals**, not independent survey-error estimates,
physical edge correspondences, measured eave offsets or validated checkpoints.
Neither physical planning line role nor as-built roof/wall identity is accepted.
The planning source is proposed work and the survey is dated January 2022.

## Remaining placement requirements

Identify the intended roof/eave/wall boundary and any offset; resolve orientation
using identified physical context; establish native edge uncertainty; and obtain
separately sourced physical checkpoints for checked registration. The current
review submits no point pairs to registration, accepts no controls/checkpoints,
and adds no world geometry. A good shape fit cannot independently verify itself.

## Replay

```sh
python scripts/review_wicker_roof_plan.py \
  --pdf 1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d.pdf \
  --cloud cloud-crop/ea-point-cloud.las \
  --roof-report evidence/wicker-roof-candidates.json \
  --crop-receipt evidence/wicker-point-cloud-crop.json \
  --output roof-plan-review.json
```

Full evidence: `evidence/wicker-roof-plan-review.json`.
Validation: `evidence/wicker-roof-plan-validation.json`.

Follow-up: [orientation context and independent imagery search](wicker-orientation-cues.md)
uses native northing labels to distinguish the north-consistent hypothesis,
without promoting the centred interior line or nonmatching lower cluster to
independent physical checkpoints.
