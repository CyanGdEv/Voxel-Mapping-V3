# Architectural component interpretation

The optional `architectural_interpretation` stage turns native linework and text into source-linked component review candidates. It does not certify a building, set world coordinates or export geometry.

Enable it in a park job or area-controller configuration with:

```json
{
  "architectural_interpretation": {"enabled": true}
}
```

For detailed native linework, combine this with the short-edge extraction settings documented in [short-native-boundary-edges.md](short-native-boundary-edges.md). Park jobs use `drawing_geometry.options`; area controllers use `drawing_geometry_options`. The interpretation stage reads the exact current drawing contract. Its sidecar output does not replace the source geometry feed or satisfy an area's required-family inventory.

## Wall bands

Two solid straight source components can suggest a wall band when their overlap exceeds 1.5 metres, their separation lies between 0.08 and 1.2 metres, and their directions agree within a cross-product tolerance of 0.00001. The quadrilateral endpoints are interpolated on the two original lines. No endpoint snapping, buffer-derived wall footprint or gap repair occurs.

Both components must have exactly one qualifying partner. Three parallel offsets, competing rails and hatch-like families remain ambiguous; the closest pair is not selected. Curves, dashed lines and truncated paint provenance are excluded. Source parent/component references and the observed width and overlap are retained. Such bands may still be rails, roof details or annotations. Interior versus exterior wall identity remains unresolved. Generic semantic export explicitly rejects these diagnostic records.

`options` can adjust bounded width, overlap and pair-comparison limits. A fixed one-million-neighbor budget also applies. Budget exhaustion discards partial band results. The stage never presents incomplete geometry recovery as a complete interpretation.

## Printed architectural claims

Standalone native labels identify wall/retaining-wall descriptions, flat or explicitly material-labelled roofs, eaves levels, ridge levels and ridge underside values. `brick paving`, `carpet tiles`, bare `tiles`, prose and rooflights do not become roof or wall claims.

Claims retain the exact native text and original-font glyph screen. Hidden or unsupported glyphs remain unbound. A visible roof-role label binds only when its entire glyph box lies inside one primitive recovered enclosure; overlapping alternatives cannot be resolved by selecting the smallest or nearest polygon. `roof_region_associations` retains the complete unchanged source candidate, including native geometry and boundary provenance, and indices into the supporting printed claims. The association supports a candidate roof region, not verified physical roof boundaries.

Version 2 adds an architectural-only fallback for original TrueType glyph IDs when the earlier per-character screen has too few nearly-black pixels. Each nonspace glyph is rendered separately from its original embedded font at its native position and transform. Its own antialiased ink (grayscale below 200) must have at least three pixels and match source ink at the same threshold, with the retained one-pixel position tolerance and one-percent unsupported-pixel limit. A blank glyph cannot borrow a neighboring glyph's reference ink. The original combined-span dark-ring check still rejects dark overpaint. Unsupported fonts, missing glyph ink and exceeded budgets remain withheld. The fallback retains the original failed screen and caps isolated rendering at 20 million pixels per label. Page rotation is restored on every path.

This corrects thin CAD strokes that have no nearly-black pixels at the fixed raster scale, and reference ink outside character trace boxes. The existing default glyph screen and its output schema remain unchanged for material, landmark and scale stages. Both glyph-screen versions are pinned by the architectural checkpoint. Raster agreement does not establish semantic or physical identity.

Printed heights retain their stated units, or `unspecified` when none are printed. `ridge u/s` is recorded as an underside value, not a roof apex. Drawing levels have no assumed ODN datum. Wall heights and eaves/ridge values are not assigned to geometry through proximity, and cannot set world heights. Roof pitch, roof-to-wall offset, exterior identity, openings and independent registration remain separate requirements.

## Source component links

Version 3 records a roof-to-band link only where a labelled roof enclosure and a paired-line band share the same native component ID and extraction contract, and the original component has a positive-length exact overlap with both boundaries. The output retains the full source component, shared geometry and length in metres. A point contact, nearby parallel offset or altered source contract cannot qualify. `exterior_ring` describes the roof polygon ring; it does not establish an exterior building wall. Hole boundaries remain distinct. A shared band can still be a roof detail or railing.

Visible wall and height claims can obtain a source endpoint connection candidate when exactly one solid, simple native line of at most eight vertices starts inside the complete label box and ends on an eligible target. Wall claims target paired bands; eaves/ridge claims target labelled roof-region boundaries. Roof approaches must remain outside the region until the endpoint. Curved/dashed lines, boundary components masquerading as leaders, missing endpoint contact and competing lines or targets are withheld. No nearest-object search or endpoint snapping occurs. These are drawn connection candidates: arrowhead/leader semantics, physical object identity, height units and datum remain unverified. The original printed claim is never modified or applied as a world height.

`component_links` includes exact roof-band links, endpoint connection candidates and a decision for each non-roof claim. A fixed 100,000-check budget discards all partial link results on exhaustion. Native source and output checkpoint checks cover these records through the version 3 stage contract.

## Elevation interpretation

Version 4 recognises supported native elevation captions and sheet titles before plan-style wall-band or roof interpretation. Exact cardinal captions and range/courtyard/gable captions retain their direction, printed existing/proposed state and any view-specific scale. Letter-spaced CAD captions are recognised without rewriting their native glyphs; the original-font screen still checks the original characters and positions. Unsupported or hidden captions cannot qualify material regions. A recognised mixed plan/elevation sheet requires separate view scopes and remains withheld.

On a supported elevation page, a brick, stone, timber, render, tile, slate, metal or concrete label associates only when its entire native glyph box lies inside one primitive enclosure. The complete unchanged source polygon, boundary provenance and material-label indices are retained. Multiple materials in one enclosure remain separate printed claims; this does not choose a physical palette or apply the horizontal paving precedence rule. The elevation sidecar does not turn those faces into plan footprints, roofs, walls or physical inventory entries.

`elevation_interpretation` retains page scale reviews separately from printed view scales. The retained AL 08 sheet prints 1:100 in the title block and 1:50 below its elevation. That conflict remains explicit. No scale is applied to a material region until a spatially verified view scope exists; no region height, vertical datum or terrain placement is inferred. Printed existing/proposed state also remains a source claim, not current as-built verification.

The existing `architectural_interpretation` option enables this path in park and area cycles. Complete native extraction and recovery are required. Unlike plan interpretation, retaining native elevation regions does not require an agreed whole-page scale, because they are not projected or measured in metres. The stage pins `elevation-interpretation-v1` alongside its other versions and rejects changed inputs, versions or sidecar outputs on resume.

## Resume and source checks

The stage replays each source PDF using the pinned native extraction options and compares it with retained extraction. Complete extraction, complete boundary recovery and a source-bound visible printed scale are required. Source/feed/output hashes and interpretation/recovery/glyph versions are pinned. Extraction run/resume counters are excluded from the semantic pin so a routine extraction resume does not invalidate interpretation.

Outputs are `architectural-pages.jsonl` and `architectural-report.json`. Source PDF edits, retained extraction differences, changed options and altered outputs are rejected. Both generic park jobs and area-cycle extraction expose the stage.

## Mutiny Bay replay

`scripts/audit_mutiny_architecture.py --input-root RETAINED_INPUT_ROOT --output AUDIT.json` replays the two pinned floor/roof PDFs with a 0.25-point short-edge cutoff and 10,000-candidate extraction budget.

The real floor plan yields 67 unique paired-line bands, with 88 competing pairs withheld. The roof sheet yields 11 bands, with five competing pairs withheld. These are unverified geometric hints, including bands on the roof sheet that cannot be called walls from their location alone.

There are 18 floor-plan and six roof-sheet architectural text claims. In the retained version 1 audit, ten floor-plan claims and no roof-sheet claims passed the glyph consistency screen. `evidence/mutiny-architectural-interpretation-audit.json` preserves that earlier result.

The version 2 replay passes 14 floor-plan claims and all six roof-sheet claims. Two of the four `flat roof` labels obtain unique complete enclosure associations. The other two have no qualifying complete enclosure and remain unbound; no larger outline is invented to accommodate them. `evidence/mutiny-roof-label-binding-audit.json` retains both associated source polygons, their boundary provenance and all per-glyph checks, alongside the unchanged band counts. Wall descriptions and eaves/ridge values remain unbound. No world geometry is generated: exterior wall identity, physical roof edges, vertical references and geographic registration still require evidence.

The version 3 replay retains those two roof associations and finds one exact shared source-edge link to a paired band on the roof sheet. Neither sheet supplies a qualifying unique source endpoint connection for the wall or level claims. Their printed heights remain unbound. `evidence/mutiny-architectural-component-links-audit.json` records the shared source component, its exact overlap and the unsuccessful label-connection checks. No park-world geometry is added.

The version 4 elevation audit replays ten pinned PDFs: four existing Smytheman elevation sheets, three existing CTD sheets and three proposed CTD sheets. The four Smytheman sheets supply 54 material-region associations supported by 81 completely contained material-label occurrences. The CTD audit retains elevation captions, existing/proposed claims and printed view scales; those sheets do not contain qualifying standalone material labels. Their source drawings also contain opening reference IDs, which are not yet bound to geometry. No explicit height datum or plan correspondence is established. The audit is retained in `evidence/mutiny-elevation-material-regions-audit.json` and reproduced with:

```bash
PYTHONPATH=. python scripts/audit_mutiny_elevations.py --input-root RETAINED_INPUT_ROOT --output AUDIT.json
```

These are native elevation candidates for later profile and plan correspondence work. No new park-world geometry is generated.

## Printed plan/elevation references

Version 5 adds a bounded source-reference index to the same optional architectural stage. It recognises exact native `archway N` and `w.range.instance` / `d.range.instance` labels, retaining their original glyphs, coordinates and complete-enclosure candidate IDs. Letter spacing is normalised only for the reference key. Visible printed project codes such as `0860 IC`, view captions and existing/proposed claims provide candidate grouping. Conflicting project codes, mixed views, unsupported caption state or missing glyph support cannot establish that grouping. A matching printed project code does not itself verify common project scope.

`architectural-reference-links.json` retains a shared-reference candidate only when visible occurrences exist on both plan and elevation pages with the same printed code and state. Existing and proposed sheets do not cross-link. All repeated and hidden occurrences remain in the candidate; no key-plan occurrence or nearest polygon is chosen as a coordinate control. Full native proofs remain in the hashed page stream, and the bounded cross-page index stores their occurrence locations. A 100,000-occurrence budget discards partial linking results on exhaustion. The separate links file and reference module version are pinned and checked on resume.

The real eight-sheet CTD replay yields eight printed-reference correspondence candidates: archways 1–4 in existing sheets and separately in proposed sheets. Forty-five reference-label occurrences have one completely enclosing source polygon. The plan archway labels have no qualifying complete enclosure, and the elevation sheets also repeat IDs in small key plans. These are source-reference links, not coordinate alignment or a plan-to-profile projection. The 54 earlier material regions are not projected through these links, and no heights or new park-world geometry are generated.

Source-linked evidence is retained in `evidence/mutiny-architectural-reference-links-audit.json` and reproduced with:

```bash
PYTHONPATH=. python scripts/audit_mutiny_architectural_references.py --input-root RETAINED_INPUT_ROOT --output AUDIT.json
```


Open archway boundary audit
--------------------------

`archway_boundaries.review` preserves every original solid axis-aligned line pair that spans and brackets an entire visible archway label. It retains component contracts and original parent references. It does not create a closed polygon, choose a nearest pair, infer passage width or promote a bracket to a coordinate control. Dashed lines, curves and rotated boundaries are excluded; comparison-budget exhaustion discards all partial results. This is a diagnostic helper, not an enabled reconstruction stage.

`audit_mutiny_archway_boundaries.py` replays the two checksum-pinned CTD courtyard plans. The existing plan retains 4 brackets for archway 1 and 10 for archway 2; the proposed plan retains 2 for archway 1. The other five occurrences have no qualifying pair. Multiple brackets can include distant walls and interior detail. None of the eight openings is physically resolved, and no world geometry is added. Evidence: `evidence/mutiny-archway-source-brackets-audit.json`. Resolving original passage-end linework and view scope remains necessary before plan/elevation alignment.


Exact dashed-end connections
----------------------------

Architectural interpretation v6 attaches `archway_ends.review` to recognised plan pages through the existing optional park/area interpretation stage. Its version is checkpoint-pinned and connection counts remain diagnostic. Original solid and dashed polyline segments retain complete component geometry, segment indices, contracts, paint styles and parents. Both dashed endpoints must lie exactly on different solid segments. The sides must be within a one-degree parallel policy and their convex hull must fully contain the visible archway label; the hull is only an internal test and is never exported as opening geometry. No lines are straightened, snapped or extended. All competing connections are retained, and budget exhaustion discards partial results.

The two pinned CTD plan replays each yield one exact dashed-end connection for archway 4: one existing and one proposed, kept separate. These were missed by the strictly axis-aligned bracket check because the original walls are slightly slanted. One dashed end does not establish the opposite end or physical archway identity, scale, height, registration or terrain placement. No world geometry is added. See `evidence/mutiny-archway-exact-source-ends-audit.json`; the earlier bracket audit is preserved. Reproduce with the existing `audit_mutiny_archway_boundaries.py`, supplying a distinct output path.


Opposite passage ends and elevation proof locations
-------------------------------------------------

Architectural interpretation v7 and source-end review v2 search all eligible original solid/dashed segments for a second end whose endpoints lie exactly on the two retained sides. The four-edge source cycle must be valid and contain the entire visible label. Original side portions retain their component/segment proofs; no opening polygon is exported, no endpoints are snapped, and a source cycle never certifies physical passage identity. Competing ends remain separate candidates. Exhaustion during either initial-end or opposite-end checks discards all partial results.

Reference links v2 carry plan-side connection indices and complete-source-cycle counts into the bounded correspondence index. Indices point into the full hashed page report rather than selecting an opening or transferring coordinates. Existing/proposed pages remain separate, hidden/key-plan repeats remain explicit, and elevation enclosure IDs retain their previous unverified physical status. Park/area checkpoint contracts pin both versions.

The real two-plan replay retains the existing/proposed Archway 4 first ends but finds zero complete source cycles. The eight-sheet reference replay links each of those partial plan candidates to its state-matched printed elevation reference, each of which has one visible unique source enclosure. An enclosure around an elevation label is not verified opening geometry or a source of plan coordinates/height. Missing opposite plan ends remain the blocker; no new world geometry is generated. The historical audits are preserved. Reproduce `evidence/mutiny-archway-opposite-ends-audit.json` with `audit_mutiny_archway_boundaries.py`, and `evidence/mutiny-archway-plan-elevation-end-links-audit.json` with `audit_mutiny_architectural_references.py`.


Shared source geometry graph
----------------------------

Architectural interpretation v8 adds `architectural_graph.build` after complete native extraction/recovery in the existing optional park/area stage. The graph version is pinned on resume and full graph records remain in the hashed architecture page stream. Graph budgets independently bound edges, nodes, intersection checks and overlaps. Any exceeded graph budget discards the partial graph without promoting it to physical geometry.

The source table preserves original component geometries, paint, extraction contracts, parents, polygon holes and curve approximation bounds. Segment edges retain component, ring and segment indices. Nodes retain exact extracted endpoints and straight-segment overlay intersections; edge incidence and drawing-direction valence are separate. Connected subgraphs, dangling ends, branches/crossings and overlaps are explicit. Original segments remain unchanged; no snap, gap closure, polygon fill, physical object, height or registration is inferred. Coincident geometry retains distinct edge identities and overlap proofs. Curved component chords are kept with approximation flags, but do not create asserted exact interior crossings.

This is a shared **drawing** graph: connected subgraphs can include annotation, overhead marks or geometry from unresolved views, so every node/subgraph retains unverified physical connectivity and view scope. It does not replace view separation or certify component inventories. It supplies the topology needed for later view-scoped wall/opening/roof traversal and dimension constraints.

`audit_mutiny_architectural_graph.py` replays two CTD courtyard plans and the Smytheman floor/roof plans, all checksum-pinned and fully extracted at the 0.25-point cutoff. All four graphs finish within budget: 16,474 edges, 22,088 nodes and 1,787 connected drawing subgraphs. The graph preserves 512 approximation-qualified curve-chord edges and 57 dashed-pattern edges. There are 5,966 open-end nodes; these include genuine open geometry and annotations, not solely missing building edges. No world geometry is added. `evidence/mutiny-architectural-source-graph-audit.json` retains per-page counts, complete graph hashes and original Archway 4 graph neighbourhood proofs plus bounded curve-component samples. Full graphs can be deterministically regenerated from the pinned sources; this audit is not a resolved opening reconstruction.


Caption-based view layout review
--------------------------------

Architectural interpretation v9 attaches `architectural_view_layout.review` to each complete source graph in the optional park/area stage. The layout version is checkpoint-pinned and the full source-graph hash binds every membership review to its original geometry. Native caption grammars distinguish plan, elevation, section, key-plan and sheet-title claims. Caption glyphs, geometry, reading direction, inline scale and state remain source-bound; standalone page scales and sheet titles never supply missing per-view scales or states. Page-versus-caption scale differences remain explicit. Hidden and duplicate captions are preserved. Unscaled captions remain inventory claims and do not create layout windows.

Visibly supported inline-scale captions can create review bands above their caption rows in the source reading frame. These are **layout hypotheses**, not native view frames or verified spatial scopes. Band boundaries may be influenced by other caption claims, and regions can still contain legends, notes or title-block artwork. Whole original components must be contained by one candidate band without crossing another to obtain a single layout candidate. Crossing or competing assignments remain explicit; no source geometry is cropped, snapped, reclassified or measured. Graph subgraphs retain a candidate only when all of their full source components share it. Assignment budget exhaustion discards all component/subgraph memberships.

The six-sheet CTD Mutiny replay retains ten caption claims and eight inline-scale layout windows: two scaled ground-floor views and six elevation views. The two unscaled first-floor labels on the courtyard sheets remain withheld as layout windows rather than overriding the scaled ground-floor captions. Six elevation captions retain 1:50 independently of standalone page claims; the AL08 existing/proposed 1:100-versus-1:50 distinction remains explicit. The review retains 6,779 single-window component candidates, 51 crossing/competing component reviews and 1,047 subgraph candidates. These are drawing-layout candidates, not verified view membership, physical structures or dimensions.

No world geometry or measurement is generated. Source-defined view frames or independently supported spatial scopes remain necessary before scale application. `scripts/audit_mutiny_view_layout.py` deterministically reproduces `evidence/mutiny-caption-view-layout-audit.json`, which retains full layout hashes, captions, candidate windows and original component/provenance samples.


Native source viewport boundary checks
-------------------------------------

Architectural interpretation v10 adds `architectural_view_boundaries.review` after the source graph and caption-layout review. It reads `/VP` declarations from the original checksum-pinned PDF using native, unrotated PDF coordinates. Source `/Type /Viewport`, finite ordered `/BBox`, crop containment and bounded metadata are checked. A viewport name must exactly match the caption identity after stripping only the recognised state/inline-scale suffixes; its rectangle must contain one entire visible caption and intersect no competing caption. Duplicate or overlapping declarations cannot select the same caption. Whole original components are retained as inside or crossing the declared rectangle. No component is cropped and no native measure dictionary is interpreted.

A supported source rectangle and named-caption correspondence remain distinct from verified drawing-view semantics, physical identity and scale application. Missing declarations do not cause caption bands, page borders or printed building rectangles to be treated as view frames. Source graph/layout hashes, source/output guards and the viewport module version are pinned. Late comparison exhaustion clears all component memberships and named-caption supports. Unsupported parser/encoding, nondefault user units and source metadata budgets are recorded as withheld reviews; changed source checksums still fail.

The six-sheet CTD replay finds **zero native viewport declarations**. All eight caption-layout regions therefore remain hypotheses, with no source-bound scope or measurement promoted. This explicitly records a missing evidence route rather than inventing frames. PDF viewport metadata is only one possible route to boundary evidence; these sheets still require another independently supported scope method. No world geometry is added. Reproduce `evidence/mutiny-source-view-boundaries-audit.json` with `scripts/audit_mutiny_view_layout.py`; the earlier caption-layout audit is preserved.

### Exact source linework frames

Architectural interpretation v11 includes `architectural-linework-frames-v1`.
It reviews original, closed, straight, axis-aligned four-corner source rings
around retained captions. It never joins separate paths, closes gaps, snaps
corners or substitutes a caption band. Complete label containment, glyph
visibility and competing nested frames remain explicit. Original components
are classified whole inside or crossing each candidate, without clipping.
Graph/layout hashes and the stage version are pinned; check-budget exhaustion
removes every partial frame record.

These are drawing-frame hypotheses, not verified drawing views: title blocks,
tables and other printed rectangles may contain captions. Source paint alone
does not establish visible frame semantics. No view-scoped measurement,
physical identity, registration or world geometry is authorized.

The six pinned CTD sheets yielded **zero closed caption-frame candidates**.
This records the absence of this specific evidence route; it does not imply
that the drawings lack recoverable views. Separate segment boundaries and
caption-free outlines are outside this first check.
Evidence: `evidence/mutiny-linework-view-frames-audit.json`.
Reproduce with `scripts/audit_mutiny_view_layout.py --input-root INPUT_ROOT
--output evidence/mutiny-linework-view-frames-audit.json` using the pinned
original PDF files under `INPUT_ROOT/mutiny-bay-sources`.

### Targeted Mutiny floor-plan provenance recovery

`linework-boundaries-v2` exposes `max_face_provenance` in recovery options.
The default remains **256** links/paint references per face; an explicit value
may raise it to **2048**. Values are bounded integers, contract-pinned, and
recomputed from retained original source geometry. Exceeding either limit
still withholds the whole face. Polygonization, source coverage checks,
protected holes and the prohibition on gap closure are unchanged.
The existing park stage accepts this through
`linework_boundaries.options.max_face_provenance`.

On the pinned Smytheman 3023-08 existing floor plan, the .25-point extraction
retains 8,454 straight source lines. Raising only the provenance allowance
recovers **724 rather than 723** faces. The additional face retains **414
source links, 431 paint references and 39 holes**; every previously recovered
geometry is unchanged. Source/native overlay inspection shows the added
face includes outdoor space as well as building edges. It is not an accepted
building outline, wall perimeter or footprint. A larger evidence budget
must not convert a closed drawing face into a physical building.

The expanded floor/roof replay screens **102/41** map candidates against
45 retained reference polygons and accepts **zero** map hypotheses. No
registration, dimensions, heights, material assignment or world geometry
is promoted. The current concrete blocker is separating the actual building
exterior from rooms, courtyards and surrounding survey linework.

Complete additional-face proof: `evidence/mutiny-dense-source-face-audit.json`.
Map replay: `evidence/mutiny-dense-face-alignment-audit.json`.
Reproduce the first with `scripts/audit_mutiny_dense_face.py --input-root
INPUT_ROOT --output evidence/mutiny-dense-source-face-audit.json`.
Reproduce the second with `scripts/audit_mutiny_map_alignment.py --input-root
INPUT_ROOT --output evidence/mutiny-dense-face-alignment-audit.json
--envelopes --landmark-context --min-line-length-points .25
--max-candidates 10000 --max-face-provenance 2048`.

### Wall-side region separation

Architectural interpretation v12 includes `wall-region-adjacency-v1` in the
optional area review. Each paired-line wall candidate is linked to complete
source faces through the intersection of its original source line and band
boundary. Fabricated end caps cannot provide side support. Faces overlapping
the strip between paired lines are excluded as adjacent room/outdoor regions.
Original-font screened room and courtyard/grass/tarmac claims require complete
label containment in exactly one source face; competing or hidden labels
remain explicit. Mixed claims cannot certify a side. An unlabelled region
is never assumed to be outdoors. Exact side intersections that collapse to
points due to derived coordinates are withheld as continuous support rather
than snapped into lines.

Whole original face geometry, holes, sourcece side geometry/contracts and label
proof indices are retained. Each candidate records missing support, missing
regions, multiple regions and missing/conflicting claims. No nearest label,
region crop, endpoint joining or exterior hull is introduced. Exhausted
check budgets discard all partial labels and adjacency assignments. The
stage version and source-record hashes are pinned; physical wall identity,
building footprint and registration remain unverified.

On the existing 3023-08 floor plan with expanded face provenance, the review
retains 67 wall-band candidates and 19 room/outdoor/surface label claims:
13 have one fully containing region, five are missing/competing and one fails
the glyph screen. Two bands retain room-to-unlabelled-side evidence; the
remaining 65 have unresolved region identity. No room-to-outdoor band or
verified exterior perimeter is established. This narrows the reconstruction
blocker to incomplete wall-side support and region identification.
Evidence: `evidence/mutiny-wall-region-adjacency-audit.json`, including complete
adjacent source-face and wall-band proofs.
Reproduce with `scripts/audit_mutiny_wall_regions.py --input-root INPUT_ROOT
--output evidence/mutiny-wall-region-adjacency-audit.json`.

### Original wall-side intervals

Architectural interpretation v13 records an explicit fractional interval on
each original straight source component when calculating paired-line overlap.
`wall-region-adjacency-v2` reconstructs support from that interval, rather than
intersecting the original line with rounded derived band coordinates. Intervals
must be finite ordered fractions in [0,1], bind the retained component contract
and agree with the band side within the existing 1e-7 PDF-point provenance
comparison tolerance. This tolerance only screens provenance agreement: it
never moves source lines, polygon vertices, face boundaries or gap endpoints.
Unsupported intervals and changed band geometry reject the review.

On the same Mutiny floor-plan replay, the legacy band intersection yields
99 line sides, 34 points and one multipoint. Original intervals retain **134
continuous source-side segments**, with **94 side-to-region links rather than
76**. The paired-band geometries and source endpoints are unchanged. Labels
and room/exterior classification remain conservative: two room-to-unlabelled
candidates, 65 unresolved, zero verified exterior walls or building footprint.
This resolves loss of source-side support due to derived polygon rounding;
missing region boundaries and semantic claims still need separate evidence.

Evidence: `evidence/mutiny-wall-source-interval-audit.json`, with the legacy
intersection comparison, current intervals, original sides and adjacent-face
proofs. Reproduce with `scripts/audit_mutiny_wall_regions.py --input-root
INPUT_ROOT --output evidence/mutiny-wall-source-interval-audit.json`.
The regression uses the real tilted-line coordinate pattern and checks that
continuous support survives without source mutation; nonfinite, reversed or
out-of-range intervals and changed band geometry reject.

### Disjoint wall-fragment spans

Architectural interpretation v14 screens wall-pair ambiguity on original
source intervals. A long line may pair with several opposite fragments when
their source intervals have no positive interior overlap. Touching interval
endpoints do not constitute competition. Overlapping alternatives still
withhold every conflicting pair; no nearest or longest pair is selected.
Source components are sorted by identity before pairing so input order cannot
change candidate identifiers. The existing pair budget also bounds interval comparisons, and exhaustion
discards the whole partial candidate set. Neither wall sides nor missing
opposite fragments are extended, joined or filled.

The pinned existing Mutiny floor plan retains **69 rather than 67** unique
paired bands from 155 eligible pairs; 86 overlapping alternatives remain
withheld. The review records 87 span comparisons. Its **138 original source
side segments** link to regions 99 times, compared with 134 sides/94 links
before this change. One newly retained band separates a uniquely labelled
**STOREROOM** from a uniquely labelled **COURTYARD**. Both glyph-screen proofs,
complete containing faces and original side intervals are retained. This is
the first room-to-outdoor wall-side evidence in this audit, not a verified
exterior wall, accepted footprint or geographic control. Two further bands
retain room-to-unlabelled evidence and 66 remain unresolved.

The next reconstruction step can follow this source-backed candidate while
keeping rooms, courtyard holes and missing spans explicit. This audit does
not identify a doorway merely because an opposite fragment is missing, apply
physical dimensions/height/material, or generate a world.
Evidence: `evidence/mutiny-wall-fragment-span-audit.json`.
Reproduce with `scripts/audit_mutiny_wall_regions.py --input-root INPUT_ROOT
--output evidence/mutiny-wall-fragment-span-audit.json`.
Tests cover disjoint fragments, touching spans, preservation of unsupported
gaps, overlapping alternatives, deterministic source ordering and exhaustion
of the interval-comparison budget.

### Perimeter coverage from the recovered wall candidate

Architectural interpretation v15 adds `wall-perimeter-coverage-v1` after a
complete wall-region review. It traces the original exterior and protected
hole rings of source regions beside room-to-outdoor wall candidates. Every
original boundary segment retains its ring/segment index, exact intersecting
source-wall intervals and unpaired remainder. Coverage unions avoid double
counting overlapping source evidence. There is no endpoint joining, doorway
closure, nearest-object selection, region crop or building hull.

The review binds the current adjacency version, complete source-record hash
and adjacency hash. Original side geometry, intervals and component contracts
are replayed from the current source records. Adjacent-face overlap and visible
uniquely contained seed claims are checked; altered sides, hidden claims and
incomplete adjacency reject. Changed source faces reject, and exhausted check budgets
discard every partial trace. Even complete paired coverage remains a source
candidate: region identity, building exterior identity and placement still
need independent support. `footprint_export_ready` remains false.

The pinned floor-plan candidate yields two source-region traces:
- The COURTYARD-labelled region retains 287 segments and 25 holes, with
  1.71% paired-wall support on its source boundary.
- The STOREROOM-labelled region retains 215 segments and no holes, with
  5.08% paired-wall support.

Across both traces, five original segments are wholly paired, two partially
paired and 495 have no paired-wall support. Neither has a complete paired
boundary. These are containing source-region rings, not verified room or
building perimeters. An unpaired piece means missing paired-wall evidence,
not a physical gap, door or absent wall. The explicit unpaired geometries
now identify what a subsequent reconstruction pass must investigate.
No footprint, dimensions, heights, registration or world geometry is
promoted by this trace.

Evidence: `evidence/mutiny-wall-perimeter-coverage-audit.json`.
Reproduce with `scripts/audit_mutiny_wall_regions.py --input-root INPUT_ROOT
--output evidence/mutiny-wall-perimeter-coverage-audit.json`.
Tests check exact paired/unpaired length, unchanged source geometry,
protected hole rings, wrong-source and altered-support rejection, forged seed
claims, overlapping support counted once and complete late-budget withholding.
