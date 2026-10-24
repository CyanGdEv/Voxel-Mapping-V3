# Visible source labels and outline associations

Planning analysis now associates standalone printed role labels with the retained
closed-outline inventory. It screens native glyphs against the original rendered
page, then requires the whole label box to lie inside exactly one source polygon.
It does not choose a nearest, smallest or most convenient enclosure.

Supported literal nouns include containers, buildings, facilities buildings,
restaurants, shops, kiosks, toilets, ride stations, paths, walkways, plazas,
courtyards, paving and tree canopies. Prose, dimensions, floor-plan captions and
unsupported names supply no role. Existing/proposed/new prefixes remain printed
claims. Mixed existing/proposed claims, conflicting roles, known legend context,
competing enclosures and failed glyph comparisons remain withheld.

Several container labels inside one polygon produce one **shared component
label enclosure hint**. They do not become several component footprints. A visible
path noun can be supported by a paving noun without inventing material or width.
A tree noun remains vegetation context. All associations are source-text evidence;
legend samples, context, drawing-view scope and physical identity still need
interpretation. No association authorizes geographic placement or world generation.

## Review the result

Use **Collect & analyse PDFs**, then open `review.html` from Results. Green
outlines mark supported visible-label associations; cyan and orange retain the
existing source/view geometry inventories. A new source-label section lists exact
words, candidate IDs and shared-enclosure status. Page JSON retains glyph screens,
label geometry, trace/character identities, original candidate hashes, conflicting
claims and unbound labels. The desktop reports building-related and path/plaza-
related **hints**, separately from reconstructed feature counts.

The automatic collection scope pins the semantic parser, glyph screen and
PyMuPDF/Shapely/fontTools versions. The upgrade analyses verified cached original
PDFs under a fresh scope. Repeating the same upgraded request reuses saved batches
and retains exact source/output checksums. Stored source observations and saved
analysis remain separate from independently reviewed neural training examples.

## Bounds

Defaults allow 500 source outlines, 200,000 polygon points, 128 role labels,
64,000 containment checks and 4 MB of semantic output per page. Overrides are
lower-only. Cancellation is checked between labels and comparisons. Incomplete
upstream inventories are not interpreted; semantic budget stops publish an
explicit withheld result with zero completed outline hints. Source geometry,
original PDF bytes and existing material-label behavior remain unchanged.

The parser is deterministic. This change does not train or promote a neural
model, create reviewed labels or add park blocks. Physical component footprints,
source state, height/facade interpretation and geographic registration remain
required before park reconstruction can accept these hints.

## Woodcutters development evidence

The proposed floor plan has three `Container` labels geometrically inside one
retained enclosure. Two pass the existing original-glyph comparison; one remains
withheld. The two visible labels support one building-related shared enclosure
hint. Three other container labels and the title-block `Facilities Building`
label have no supported enclosure. They are not assigned by proximity.

The enclosure is not verified as a separate shipping-container footprint or as
current as-built geometry. Closed path/plaza boundaries remain unresolved; the
four raster elevation views and the other section's extraction gap remain.

See [final collection/restart development receipts](evidence/planning-semantics/woodcutters-development-validation.json).
The source PDFs were previously inspected. The run is a cached development replay,
not an unseen-area benchmark or a physical 6 GB Windows-PC acceptance test.

The subsequent [fine component boundary pass](planning-component-footprints.md)
retains short source segments in a bounded automatic search around visible
component labels. It recovers separate boundary hypotheses without changing
these coarse enclosure hints or accepting physical building geometry.
