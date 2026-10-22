# Original roof junctions and relative positions

This downstream review connects whole native roof-plan strokes before checking
their relative position in the elevation. It does not classify a physical roof,
assign a building name, or create a new mesh. It stacks on the
[grayscale source review](source-gradient-gables.md); all preceding source holds
and the provisional main roof remain unchanged.

## Source recipe

The complete preceding grayscale chain is rebuilt and compared with its saved
digest. Original PDF/crop contracts are verified, and parent inputs are pinned
again before use and after processing. Only unclipped, original, two-point
straight roof strokes at least one nominal metre long enter the junction index.
Curves, flattened polyline approximations and shorter strokes are excluded.

Every eligible original stroke at least two nominal metres long is considered
as a possible ridge. For each original endpoint, perpendicular original cap
segments must pass within 0.25 PDF point. A cap's original outer endpoint must
meet an original parallel rail within the same tolerance. Both ridge ends must
have such cap support to the same two rails. Whole crossbars and two separate
half crossbars are supported. Each rail must meet at least one cap at an original
rail endpoint; the other cap can meet its interior. Segment directions allow
five degrees, with total nominal cross-span 2–40 m and at least 1 m on either side.

This pass explicitly assumes a **near-balanced gable template**: the two native
cross-runs must differ by at most 0.25 nominal metre. The runs remain individual
source measurements; no points are averaged, snapped, trimmed or made symmetric.
These constraints limit discovery; asymmetric, curved, short or disconnected
roof designs remain outside this recipe. Connected hatching can still satisfy
it. Every competing template remains, with unverified physical line roles.
Original rail tails beyond the ridge stations remain measured and visible.

The fixed non-target source-artwork relation supplies the existing elevation
axis. Relative-position checks require agreement within 0.1 degree of the main
roof's original plan axis. Each conditional local gable intersection is compared
with both original endpoints of every candidate ridge, using all three original
main-roof plan lines as separate anchors. Both raster end anchors and both signs
are retained. An agreement requires at most 0.25 nominal metre of position error.
No translation is fitted to the secondary gable. Identical spans at two profile
thresholds share one calculation with both original threshold receipts retained.
All failures survive; there is no residual-ranked winner or physical acceptance.
Held local source pairs never become accepted because of a position match.

## Same three original drawings

The Wicker Man case retains 2,492 native roof lines, 28 connected templates and
30,912 position checks; 276 agree, all against the same native ridge in the
forward orientation. This is one candidate **within this bounded recipe**, not
proof of unique physical correspondence. The candidate's original ridge is
8.01792 nominal m, while each original rail is 8.52168 nominal m: both rails
retain a 0.50376 m source tail. No depth is chosen between them. Eave heights,
physical roof roles/building identity, independent second-view edge support,
full geometry and park/vertical registration remain unresolved. No new roof
model, accepted physical component, world block or training label is produced.
The semantic ranker remains untrained.

The known application page was retried on 22 October 2026 and returned HTTP 503;
the transport receipt is in `evidence/roof-source-topology/`. No new drawing or
guessed attachment ID entered this increment. Exploratory southwest position
checks do not override the preceding southwest local-source hold and are not
published as independent validation.

## Reproduce and review

```bash
python -m scripts.build_roof_source_topology \
  --source-gradient GRADIENT --source-partial PARTIAL --gable GABLE \
  --profile PROFILE --preview PREVIEW --components COMPONENTS \
  --views VIEWS --corpus ORIGINALS --output OUTPUT
python -m scripts.audit_roof_source_topology \
  --topology TOPOLOGY --source-gradient GRADIENT --source-partial PARTIAL \
  --gable GABLE --profile PROFILE --preview PREVIEW --components COMPONENTS \
  --views VIEWS --corpus ORIGINALS --output audit.json
python -m scripts.render_roof_source_topology \
  --topology TOPOLOGY --source-gradient GRADIENT --gable GABLE \
  --views VIEWS --output roof-source-review.html
python -m unittest tests.test_roof_source_topology -q
```

The offline HTML embeds two untouched source crops and the complete evidence as
lossless gzip, decoded locally by the browser. Candidate/pair/alignment controls
retain the source geometry, all failed alignments and native junction receipts.
Full-drawing and all-candidate overlays preserve exact source coordinates. JSON
export returns the original evidence bytes and checksum. No remote web service
is needed. A browser supporting `DecompressionStream` is required.

Bounds: 4,096 source components, 256 candidate templates, 100,000 charged index
contacts/comparisons by default (the case uses 77,865), and a 32 MB compact JSON
serialization budget. An overflow discards **all** topology and position results;
there is no first-subset success. Pretty-printed JSON can exceed the compact
serialization size. Source identity and extraction order precede target checks.

The separate auditor freshly rebuilds the chain, decodes original PDF strokes,
and checks junction distances, original rail fractions/tails and every relative
position using separate arithmetic. Receipts and the compressed full test log
are under `docs/evidence/roof-source-topology/`.

Validation: **1,722 full-suite tests pass** in 360.655s,
including eleven focused regressions. The independent audit checks all 2,492
original PDF strokes, 112 junction contacts, 56 untrimmed rails and 30,912 relative
positions. Browser verification covers 101 interaction states, all 28 candidates,
46 conditional pairs and 24 alignment options, two original image hashes and
exact-byte export, with zero JavaScript errors.
