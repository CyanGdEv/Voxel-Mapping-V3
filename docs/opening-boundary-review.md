# Aperture boundary review

Area local-wing reviews now automatically compare complete source outlines
against the existing reviewed opening polygons. This is a reconstruction
diagnostic and refinement worklist, not automatic physical aperture acceptance.
The original traced model remains a partial review hypothesis.

The stage retains original closed native polygons, including qualified native
curves, exact straight-line faces and the source-proved rectangle cycles from
the native opening inventory. A candidate must lie wholly in the reviewed
view; it is never cropped. Every nearby pane, frame band, competing outline and
protected hole remains in the audit. No largest or nearest outline is selected.
Source curve error propagates through the affine transform using its largest
singular value. The sum of that bound and symmetric boundary Hausdorff distance
must fit the seed's sampling allowance, with at least 85% polygon IoU, solid
paint and no holes, before a unique trace-refinement candidate is reported.
Even that result does not certify physical aperture identity or export geometry.

For incomplete outlines, the review retains original solid straight source
lines near each seed perimeter and the unsupported parts of the reviewed trace.
A two-pixel proximity buffer measures distance-to-trace evidence only: it never
joins native geometry, repairs gaps or establishes exact source coverage.
Endpoint discovery uses a separate 12-pixel search margin and records every
positive source endpoint separation within the sampling allowance. Original
coordinates and identities remain unchanged. These are competing gap candidates,
not chosen repair instructions. Exact endpoint joins are counted separately.

Source/extraction/comparison budgets withhold incomplete results. Acquired
original PDFs, the validated native inventory, recipe bytes and output bytes
are pinned. Unchanged replay reuses identical output; changed receipts reject.
Area sweeps expose `opening_boundary_reviews`, with zero park geometry additions.

## Mutiny north range

The corrected seed retains 16 opening shapes and replaces the legacy IDs
`w3.06-a` and `w3.06-b` with source-supported `w3.05` and `w3.06`. Its parent seed
and native label audit hashes are retained; all geometry points are unchanged.
The previous seed remains available to reproduce the earlier label-error audit.
Native `w.3.13` remains uncarved: the elevation labels it beside a boarded-window
note, which is insufficient evidence to add an open aperture.

The complete source-boundary pass recovers 235 exact straight faces from the
same existing elevation, retaining 1,922 open dangles and 302 cut edges. It also
reviews all 112 native source rectangle cycles. None of the 16 reviewed aperture
traces has a complete eligible outline within its original two-pixel bound.
For archway 3, 53.4% of the reviewed perimeter lies within two pixels of retained
straight source linework; four nearby unjoined endpoint alternatives remain.
Its head is drawn as native straight segments, not a native Bézier curve.
High proximity coverage elsewhere does not imply a complete closed aperture.

The corrected model has identical wall/roof vertices and triangles to the prior
study, with corrected opening IDs. The source-linework OBJ/PNG provides a
separate drawing layer projected onto the reviewed local facade plane at the
source nominal scale and drawn floor zero. It does not add wall holes, solids,
hidden walls, materials or geographic placement. Rendering offsets the cyan
overlay slightly toward the viewer solely for visibility; OBJ coordinates use
the facade plane itself. This is a local geometry review, not a new park world.

The real three-source area replay validates identical boundary bytes, extracts
zero new pages on its second pass, reports zero seed-label disagreements and
remains awaiting reconstruction. Altering the boundary receipt rejects reuse.
Compact evidence: `evidence/mutiny-opening-boundary-review-audit.json` and
`evidence/mutiny-opening-boundary-area-replay-audit.json`.

```sh
python scripts/review_opening_boundaries.py \
  --recipe evidence/mutiny-north-wing-source-label-corrected-seed.json \
  --source /path/to/original-elevation.pdf --output /path/to/fresh-review
```

Next geometry work must establish source-backed complete head/jamb/sill or
ground connections and distinguish physical opening edges from casing/panes.
Any gap-repair hypothesis needs explicit provenance and a separately reviewed
result; this stage does not silently repair it. Outer walls, end walls and roof
junctions still require their own source traces and correspondence checks.
