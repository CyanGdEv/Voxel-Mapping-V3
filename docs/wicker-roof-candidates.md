# Wicker shop observed-return roof-envelope candidates

This follow-up uses the checksum-bound January 2022 point-cloud crop from
[the classification audit](wicker-point-cloud.md). All eligible class-6 returns
in the native BNG crop participate in connectivity. The shop's retained mapped
outline only seeds component ranking; it does not clip, rotate or reshape the
observed geometry. Withheld, synthetic and nonfinite returns are excluded.

`voxel_mapper/roof_candidates.py` tests nine combinations of XY connection radius
(1, 1.5, 2 m) and maximum height difference between neighbouring returns
(0.5, 1, 2 m). Connections are transitive; these parameters are not absolute
height bands. Spatial bins bound the neighbour search, with a 20,000-return and
two-million-comparison budget. Exceeding a budget fails without partial output.

## Results

| Component | Parameter combinations | Returns | Outline seed returns | Convex envelope | Native observed Z range |
| --- | ---: | ---: | ---: | ---: | --- |
| Smaller component | 6 | 505 | 441 | 223.19 m² | 186.10–189.85 m ODN |
| Expanded component | 3 | 566 | 442 | 280.84 m² | 183.13–189.85 m ODN |

All six combinations using a 0.5 or 1 m height step reproduce identical smaller
component membership and geometry. All three using a 2 m step reproduce the
same expanded component. Neither reaches within its connection radius of the
crop boundary. The expansion adds 61 lower returns, with median Z 183.33 m ODN;
their physical identity remains unverified. The smaller component median is
187.97 m ODN. These are observed surface elevations, not floors or rail heights.

Maximum boundary Hausdorff spread between the envelopes is 4.55 m. This measures
connectivity sensitivity, **not positional error**. The smaller envelope has
83.59% intersection-over-union with the mapped comparison outline; the expanded
one has 67.67%. Neither overlap score constitutes physical identity verification.

The smaller component is now a repeatable, survey-supported inspection candidate
that can be studied separately from the connected lower returns. Its convex hull
can bridge concavities, and its minimum rectangle corners are only estimates.
No snapping, interior filling, planning-outline fit or wall extrusion is applied.
Raw crop point indices and membership hashes preserve the origin of each envelope.

Physical roof identity, concave edge shape, eave-to-wall offsets and native edge
uncertainty still need verification. Six identical segmentations do not supply
independent checkpoints. Zero controls, checkpoints or world geometry additions
are accepted. The next step is to inspect the candidate's roof surfaces and match
the intended physical boundary to the planning drawing, retaining a separate
checkpoint source for registration.

## Replay

```sh
python scripts/review_wicker_roof.py \
  --cloud cloud-crop/ea-point-cloud.las \
  --crop-receipt evidence/wicker-point-cloud-crop.json \
  --survey-receipt evidence/wicker-dated-landmark-audit.json \
  --osm park-osm.json --grid uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output roof-candidates.json
```

The cloud, OSM and datum-grid bytes must match the retained receipts. Survey
identity, native bounds, header CRS and point count are checked before analysis.
The full candidate queue is `evidence/wicker-roof-candidates.json`; validation is
`evidence/wicker-roof-validation.json`. Both parameter outcomes remain recorded.

Follow-up: [source-linked roof/plan edge review](wicker-roof-plan-review.md)
reproduces the planning candidate, scopes scale to the native A1 page, and retains
both orientation ambiguity and per-edge self-fit residuals.
