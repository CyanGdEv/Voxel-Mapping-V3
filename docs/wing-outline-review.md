# Window cycle and plan junction review

Area local-wing reviews now prepare `wing_outline_reviews`. This stage combines
two drawing diagnostics and never promotes physical geometry automatically.

The elevation pass uses the opt-in open-subpath recovery and uniform render
transform to find complete original rectangle cycles. Unlike atomic enclosed
faces, complete cycles can retain a full window perimeter despite its internal
mullions, transoms and panes. Nearby cycles with at least 15% IoU are retained
in a 24-pixel discovery neighbourhood, with source interval proofs and parent
trace comparisons. Panes, casing and full silhouettes remain competing;
largest, nearest and highest-IoU candidates are never selected automatically.
These discovery thresholds are not a relaxed physical or trace-fidelity gate.

The plan pass examines the two cross-sections implied by the reviewed facade
and rear datum. Original solid straight source segments and their native
endpoints remain unchanged. A two-pixel proximity allowance records supported
parts of these review cross-sections; it never repairs or joins source linework.
Unsupported portions remain explicit. Even full proximity coverage does not
prove an exterior end wall, an opening-free closure or a vertical profile.

Original PDFs, source state, rendered samples, page captions, recipe bytes and
receipt bytes are checked. Incomplete extraction, bounded comparison exhaustion
and modified receipts withhold the corresponding complete review. Area sweeps
retain the summaries, and missing acquired sources are reported without an
external fallback. The stage adds zero accepted park geometry.

## Mutiny north range

Recovered elevation linework yields 199 complete rectangle cycles. Fourteen
opening traces have competing nearby cycles, one has a single nearby cycle and
one has none. This is drawing topology, not a physical opening inventory.
Explicit visual review identifies complete drawn window silhouettes w3.01–w3.07
for a separate provisional seed derivative. The w3.02–w3.04 revisions correct
substantial width and sill errors; some older traces extended around casing or
below the sill into the label region. Each selected cycle retains all four
original side interval proofs and uses no added window connector.

The derivative `evidence/mutiny-north-wing-window-cycle-review-seed.json`
retains the earlier arch gap hypothesis and all unchanged roof geometry.
Three doors and five upper windows retain manual traces. Boarded w3.13 stays
uncarved. Source-cycle selection is an explicit drawing-silhouette review,
not autonomous physical aperture acceptance; physical extents remain unresolved.
The parent seed and every before/after polygon remain available.

The local mesh has 142 courtyard-wall triangles, four roof triangles and 16
clear aperture polygons. Opening area changes from 31.186 to 32.203 square metres;
all triangles are checked against every aperture and their area matches the
subtracted wall. Model replay reuses identical bytes. The isolated Bedrock
display study contains 280 surface cells and 5,680 composed blocks in eight
chunks. All written blocks and unwritten air pass native readback. Its one-metre
sampling cannot represent fine window details faithfully.

The acquired plan yields 1,761 complete source components. The two reviewed
cross-sections have 88.91% and 36.10% source proximity coverage, retaining ten
and four original segment proofs. Visual source review shows adjacent wing
junctions rather than two independent exposed gable ends. No end-wall solids
are added: exterior/partition identity, apertures and matching vertical profiles
remain required. These fractions do not measure physical wall completeness.

Real three-source area replay reuses identical outline bytes and extracts zero
new pages. Edited outline receipts reject reuse. Evidence is retained in
`evidence/mutiny-wing-outline-review-audit.json` and
`evidence/mutiny-wing-outline-area-replay-audit.json`.

```sh
python scripts/review_wing_outlines.py \
  --recipe evidence/mutiny-north-wing-arch-proposal-review-seed.json \
  --sources /path/to/three-original-pdfs --output /path/to/fresh-review
python scripts/build_local_wing_review.py \
  --recipe evidence/mutiny-north-wing-window-cycle-review-seed.json \
  --sources /path/to/three-original-pdfs --output /path/to/fresh-model \
  --isolated-world
```

Next: complete the upper-window boundaries across mullions without assuming a
bounding box; reconcile rear-wall openings and both adjoining wing junctions
with matching elevations; review the corresponding roof connections. Verified
physical identity, geographic controls and absolute datum remain required for
production park placement.
