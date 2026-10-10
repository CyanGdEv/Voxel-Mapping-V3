# Floor PDF reduction identified

The floor/elevation dimension conflict is explained substantially by a reduction
of the floor PDF's page content. Floor and roof PDFs have the same A1-sized
native media box and no explicit PDF UserUnit. Matching native text origins in
their common title block and drawing notes reveal that the floor's content is
approximately 90.9% of the corresponding roof-sheet content, with a page offset.
This is a source-layout correction hypothesis supported independently of the
shop outline, rather than a scale fitted to make the shop dimensions agree.

The review fits an affine roof-to-floor page transform using 13 shared furniture
anchors. Four other shared labels are held out: revision date, NS, Checker and
the full park address. Maximum held-out origin residual is 0.118 PDF points.
Building outlines, GIA labels and elevation wall lengths are excluded from the
transform fit. The scripts reject a deliberately displaced held-out label.
These holdouts are same-document-layout validation, not independently surveyed
geographic checkpoints.

| Check | Raw floor trace | Layout-normalized floor | Elevation trace |
| --- | ---: | ---: | ---: |
| Long wall dimension | 14.38 m | 15.82 m | 15.90 m |
| Short wall dimension | 10.76 m | 11.83 m | 11.81 m |
| Outer area | 154.63 m² | approximately 187 m² | wall-span rectangle approximately 188 m² |

After applying the inverse page-layout linear transform, the floor dimensions
agree with the elevation trace within 0.09 m. The external-area/GIA contradiction
also clears: the normalized outer area exceeds the proposed 170 m² internal-area
label. The three openings and seven solid wall segments are normalized with the
same transform, preserving the full perimeter lengths. No independent scale
adjustment is made for individual walls or openings.

This supports a provisional scale-normalized architectural model. It does not
prove that every view in the floor PDF underwent exactly the same reduction or
that the proposed geometry is as built. The printed instruction gives figured
dimensions priority over scaling. Raw traces are retained unchanged, and the
normalized trace is a separate review result. No park registration, wall/opening
heights, verified ODN floor level or accepted world placement is assigned.

## Reproduce

```sh
python scripts/normalize_wicker_floor_scale.py \
  --floor-pdf revised-floor-plan.pdf --roof-pdf revised-roof-plan.pdf \
  --floor-review evidence/wicker-shop-local-floor.json \
  --roof-review evidence/wicker-shop-local-roof.json \
  --output floor-scale-review.json
```

Evidence retains all anchor texts, original native origins, fit/holdout roles,
residuals, the affine transform, corrected wall/opening coordinates and input
review hashes. The result is `evidence/wicker-shop-floor-scale-review.json`;
validation is `evidence/wicker-shop-floor-scale-validation.json`. Both PDFs are
checksum-verified before anchor extraction. Replay, topology conservation,
source integrity and holdout rejection checks passed.

Next: assemble a provisional local architectural preview using normalized wall
locations and the roof, with unresolved opening heights kept explicit; compare
its roof envelope with dated LiDAR. Geographic placement still needs independent
physical registration evidence.
