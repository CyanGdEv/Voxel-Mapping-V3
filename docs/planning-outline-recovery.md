# Source outlines and bounded view geometry

The planning pilot now retains unclassified closed outlines even when no path,
plaza or material label binds to them. The existing coarse straight-line pass
already discovers these enclosures; previously they disappeared from the review
output when no label matched. Retention does not classify a shape as a building,
path or plaza. Existing label containment and surface promotion stay unchanged.

The second pass extracts complete native paint primitives inside automatically
inferred caption/view regions. It can operate when the whole-sheet architectural
graph reaches a budget. Regions stay layout hypotheses. Crossing primitives are
withheld without clipping, snapping endpoints or repairing gaps. Partial extraction
never supplies closed faces. A failed/partial boundary recovery can retain valid
original closed polygons, with its incompleteness recorded separately.

Each source outline retains original geometry, holes, paint references, PDF/page
identity, source-record hashes and native area/perimeter/bounds. Region outlines
also bind the exact view receipt. A single visible view-specific scale claim can
supply **nominal** local metres, area and perimeter. Conflicting or absent scales
leave native PDF points only. Nondefault PDF UserUnit also withholds nominal metres. Sheet-wide ratios are never inherited across views.
The local origin is the inferred region corner, not a physical or geographic datum.

## Use the desktop

Run **Web research → Collect & analyse PDFs** with the application reference and
source URL, or run the existing advanced planning-source pilot. Open `review.html`
in Results. Each eligible page offers **Inspect extracted source outlines**:
cyan shows the coarse closed-outline inventory and orange shows view-region
outlines. The inventories can overlap. SVG previews embed the original-page raster
and retain the native-to-pixel transform; they can be opened as standalone files.
Full candidate geometry, measurement basis and gaps remain in linked page JSON.

Collection implementation pins create a new analysis scope after this upgrade.
Previously acquired original PDFs remain available through the shared verified
cache, so an offline replay can analyse them with the new code. Starting the same
upgraded request again reuses completed batches without repeating analysis.

## Bounds and remaining gaps

The coarse inventory retains at most 500 outlines per page. Partial extraction,
partial recovery or exceeded candidate count withholds the entire coarse inventory.
The view pass inspects at most 16 regions with 2,000 candidates and 100,000 points
per region, 12,000 parents/200,000 points per page, 500 output outlines, 2,048 source provenance references per face and 16 MB
of output. All optional view limits are lower-only. Output/quota and crossing
primitive gaps are explicit. Existing document/page/output/memory/cancellation
bounds remain. Native PDF parsing materializes raw paint before count checks;
these are not whole-parser memory guarantees or a physical 6 GB PC benchmark.

Supported enclosures can be rooms, symbols, annotations or context. Regional paint
visibility remains unverified. Source outlines do not create reviewed training
labels, model weights, accepted building specifications or park blocks. Next work
must resolve actual component identity and view scope, missing architectural
boundaries, height/facade correspondence, source state, geographic registration
and finished levels. Geometry accuracy remains unassessed without independent
checked evidence.

## Woodcutters development check

On the previously inspected SMD/2024/0136 originals, the coarse pass retains 143
existing-site, 76 proposed-site and 99 proposed-floor-plan outlines: **318** source
shapes. The label-bound surface candidate count remains zero. The existing
section/elevation sheet supplies 255 nominal section-view outlines through
regional extraction using the existing backend's bounded 2,048-reference provenance limit. Its second section still reaches the local candidate budget;
four inferred elevation regions contain embedded raster artwork and return no
native vector primitives. They require raster interpretation. Missing or rejected
source linework stays explicit; it is not filled with guessed shapes.

See the retained [development validation](evidence/planning-outlines/woodcutters-development-validation.json)
for the final complete collection/restart counts and source/implementation hashes.
This is a cached replay of previously acquired development sources, not an
unseen-area or full-park reconstruction benchmark.

[Visible source-label associations](planning-outline-semantics.md) now distinguish supported enclosure hints from unclassified outlines while retaining ambiguous, hidden and unbound labels.
