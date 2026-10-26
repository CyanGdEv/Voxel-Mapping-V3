# Original hatch regions and paving legends

The [current existing/proposed paving stage](planning-existing-paving.md) expands this initial hatch-only coverage to solid and compound fills. The replay counts below describe the initial v1 stage.

Planning area pilots now inspect direct PDF pattern fills and produce a separate
source hatch review. This recovers source-authored closed paving shapes even
when individual boundary strokes cross the label search windows. It does not
join open curves or infer their widths.

The reader preserves original operation indices, transformed cubic controls,
fill rules, nested clipping witnesses, pattern phase and fill opacity. Curves
use the existing bounded 0.05 PDF-point subdivision algorithm. Supported
intersections apply the actual page and clipping masks. Original fill geometry
is retained separately from the displayed clipped region. This display bound
is not a claim of physical reconstruction accuracy or exact curved topology.

Hatch identity resolves the complete pattern resources, including decoded image
bytes, colour palettes, image masks and graphics states. Compression and object
numbers do not define appearance. Pattern translation is retained as phase;
linear transforms remain part of the repeated texture identity. Matching
texture alone supplies no material or physical role.

A proposed/existing paving association requires an exact complete printed
`New Paving with levels` or `Existing Paving with levels` key, original glyph
visibility proofs for every connected text fragment, an unambiguous adjacent
swatch, and matching texture and opacity. Duplicate/contradictory keys, hidden
fragments and additional connected words cannot authorize transfer. Existing
annotation guards in ordinary surface extraction remain unchanged. The new
explicit legend interpretation remains a source claim for review.

The pilot links a separate original-page SVG overlay and retains the complete
source evidence in each page JSON. Blue regions have a visible paving-key
association; brown regions have no paving classification. These records do
not enter area-layout candidates, world export, training labels or weights.
Later overpaint, actual physical boundaries, heights, registration, conflicts
with buildings and traversability remain unresolved.

## Bounds and verification

Lower-only limits cover 16 MB of decoded page content, 500,000 operations,
256 pattern resources, 512 records, 20,000 operators per source path, 200,000
flattened points, 4 MB of resolved resource data, 2,000,000 overlay work units,
16 clipping scopes and 8 MB of evidence. Point work is charged before extending
path buffers. Unknown compositing, optional content and invalid topology are
withheld. A quota failure clears the whole new page review; cancellation
propagates. Direct form descendants are not interpreted, and their invocations
are counted. This is a supported-source inventory, not complete page visibility.

The Wicker development replay retains 32 supported hatch regions. Eighteen match
the visible proposed-paving key, including three curved regions. Five invalid
hatch rings are withheld. The three curved regions are independently compared
with MuPDF's original clipping masks 61, 62 and 63. The original PDF is included
in the review pack. This previously inspected document is not an unseen accuracy
benchmark. The replay runs the new hatch stage; it does not claim a fresh full
real-source building/section pipeline or a generated Wicker path network.

Synthetic tests cover transforms, cubic shorthand, overshoot, original clip
controls, holes, graphics-state restoration, hidden/continued/duplicate legends,
resource identities, quotas, cancellation and pilot integration without world
promotion. The frozen Windows smoke separately checks a curved source region
and visible paving key while retaining the existing layout/world counts.
