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
