# Nominal component plans and printed-size diagnostics

The planning pilot now measures retained component boundaries under visible
floor-plan scale claims and compares them with linked, explicitly dimensioned
container notes. The automatic collection combines evidence across saved batches
and recomputes the same diagnostic on restart. It creates measured 2D plan
previews; it does not create an accepted building or invent a missing height.

## Evidence and scope

The stage preserves each original polygon. A nominal affine converts native PDF
points using the printed denominator and a local bounding-box origin. That origin
is not a physical datum. Oriented bounding-rectangle spans and polygon area are
diagnostics; the rectangle never replaces the source polygon. Every trial binds
the original component hash, source geometry hash, exact caption evidence, PDF
frame, printed denominator and affine. Multiple different scale claims remain
separate trials and cannot be selected by their best dimension residual.

Original native glyphs screen drawing codes, sheet references and explicit size
notes. Current literal notes support two lengths with explicit `ft`, `feet`, `m`
or `mm` on each value, followed by Container/Shipping Container wording. Feet
convert using exactly 0.3048 metres. Missing units are not inherited from the
other value or inferred from standard container sizes. Two printed lengths never
supply a height or verified dimension axes.

Note context requires one visible structured drawing code per page, the same
printed drawing series, a literal reference to the other sheet, and matching
unambiguous printed existing/proposed state. Different sheets in the same PDF
can supply that context; one page cannot validate itself. This establishes a
**literal source-context hypothesis**, not a verified reference bubble, component
correspondence or physical identity. Repeated identical notes retain every source
receipt. Conflicting pairs, counts, states, codes and scale claims remain withheld;
the stage never chooses a note or scale by its residual.

The diagnostic tolerance is **0.25 m per oriented span** and may only be lowered.
It is a declared comparison policy, not independent physical accuracy. A positive
result is labelled `printed_size_pair_consistent_diagnostic`. Exterior-wall role,
scale application to the artwork, source-to-component scope, current construction
state, height, park alignment and finished ground levels remain unverified.
Nondefault PDF UserUnit, cropped pages and mismatching explicit paper sizes
withhold nominal geometry. Printed scale alone does not certify actual dimensions.

## Review and bounds

Open Results → `review.html` → **Nominal component plans and printed-size
diagnostics**. The review shows the unchanged source polygons under each nominal
scale, lengths, source notes, span differences and unresolved cases. Exact
coordinates, hashes and glyph evidence are in `component-measurements.json`.
Desktop summaries distinguish nominal plans, size-consistent hypotheses and
mismatches from reconstructed buildings.

Per-page limits cap 32 components, 128 text evidence records, eight scale contexts,
200,000 nominal polygon points and 4 MB of evidence. Overrides are lower-only.
Collection review allows 512 unique page receipts, 4,096 charged page/note checks
and 8 MB of diagnostic output. Incomplete relevant pages and exhausted limits
publish zero successful comparisons. SVG preview point/byte budgets withhold the
complete graphical preview while retaining complete bounded JSON diagnostics.
Cancellation is checked between source runs, components, pages and comparisons.
Analysis and collection contracts pin the implementation bytes.

## Woodcutters development result

On the previously inspected SMD/2024/0136 originals, the proposed floor plan
prints 1:100 next to its ground-floor caption. The proposed section sheet prints
`6 No. 8ft x 40ft Shipping containers.` The plan and section carry the same
structured drawing series, and the plan includes visible literal `0301` references.

The printed pair converts to **2.4384 × 12.192 m**. The three recovered source
boundaries have these nominal oriented spans:

| Nominal short span | Nominal long span | Maximum pair difference | Diagnostic |
| ---: | ---: | ---: | --- |
| 2.502 m | 12.001 m | 0.191 m | Size-consistent at 0.25 m |
| 2.501 m | 12.004 m | 0.188 m | Size-consistent at 0.25 m |
| 2.501 m | 11.392 m | 0.800 m | Mismatch |

The shortened boundary stays visible as a source candidate and fails the size
comparison. It is not stretched to fit the note. The two size-consistent cases
remain hypotheses; none is promoted to an accepted physical footprint.

The section contains a labelled enclosure, but its physical view scope and
correspondence to a floor-plan component remain unresolved. Height stays `null`,
the 3D preview is explicitly withheld, and building/world additions remain zero.
Paths/plazas and park alignment are also unfinished. See the retained
[development collection and restart proof](evidence/component-measurements/woodcutters-development-validation.json).
Previously inspected cached sources are not an unseen-source or independently
checked real-building benchmark.
