# Small roof projection dimensions recovered

The revised roof plan and dedicated shop elevations now have retained manual
projection traces, pinned to PDF checksums and fixed rendered pixel hashes.
The plan indicates a projection approximately 5.92 m wide and 1.01 m beyond the
main roof edge. The northeast elevation gives a front width approximately 5.97 m.
The southeast side gives approximately 0.98 m beyond the main roof edge. Width
and comparable depth therefore agree within approximately 5 cm and 3 cm.

The side view also shows approximately 1.47 m from the wall to the projection
front. That is a different measurement: it includes the roughly half-metre
main-roof overhang. Comparing this span directly with the plan's beyond-roof
extension creates a false 0.46 m discrepancy. Both side reference points are
retained explicitly, so downstream reconstruction does not confuse wall and
roof boundaries. No scale adjustment or averaging is needed to explain it.

Each endpoint has ±2 rendered pixel manual sampling bounds. Two-view depth
comparisons have approximately 0.36 m combined worst-case sampling bounds;
these do not include source or physical accuracy. Projection slope, fascia
thickness and exact roof-plane attachment still need vertical edge interpretation
before a three-dimensional projection is added to the main roof model.

`scripts/review_wicker_roof_projection.py` reopens checksum-pinned sources and
reproduces native point traces and dimension checks. Evidence is retained in
`evidence/wicker-shop-roof-projection.json`. Raw wall-to-front and like-for-like
roof-to-front measurements remain separate. The main roof/wall model remains
unchanged and zero world geometry is placed.

Next: resolve the projection's upper/lower roof and fascia edges in the side and
front views, then attach its surface to the local model. Independent geographic
registration remains necessary for verified park placement.
