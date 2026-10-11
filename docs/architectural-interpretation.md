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

## Resume and source checks

The stage replays each source PDF using the pinned native extraction options and compares it with retained extraction. Complete extraction, complete boundary recovery and a source-bound visible printed scale are required. Source/feed/output hashes and interpretation/recovery/glyph versions are pinned. Extraction run/resume counters are excluded from the semantic pin so a routine extraction resume does not invalidate interpretation.

Outputs are `architectural-pages.jsonl` and `architectural-report.json`. Source PDF edits, retained extraction differences, changed options and altered outputs are rejected. Both generic park jobs and area-cycle extraction expose the stage.

## Mutiny Bay replay

`scripts/audit_mutiny_architecture.py --input-root RETAINED_INPUT_ROOT --output AUDIT.json` replays the two pinned floor/roof PDFs with a 0.25-point short-edge cutoff and 10,000-candidate extraction budget.

The real floor plan yields 67 unique paired-line bands, with 88 competing pairs withheld. The roof sheet yields 11 bands, with five competing pairs withheld. These are unverified geometric hints, including bands on the roof sheet that cannot be called walls from their location alone.

There are 18 floor-plan and six roof-sheet architectural text claims. In the retained version 1 audit, ten floor-plan claims and no roof-sheet claims passed the glyph consistency screen. `evidence/mutiny-architectural-interpretation-audit.json` preserves that earlier result.

The version 2 replay passes 14 floor-plan claims and all six roof-sheet claims. Two of the four `flat roof` labels obtain unique complete enclosure associations. The other two have no qualifying complete enclosure and remain unbound; no larger outline is invented to accommodate them. `evidence/mutiny-roof-label-binding-audit.json` retains both associated source polygons, their boundary provenance and all per-glyph checks, alongside the unchanged band counts. Wall descriptions and eaves/ridge values remain unbound. No world geometry is generated: exterior wall identity, physical roof edges, vertical references and geographic registration still require evidence.

The version 3 replay retains those two roof associations and finds one exact shared source-edge link to a paired band on the roof sheet. Neither sheet supplies a qualifying unique source endpoint connection for the wall or level claims. Their printed heights remain unbound. `evidence/mutiny-architectural-component-links-audit.json` records the shared source component, its exact overlap and the unsuccessful label-connection checks. No park-world geometry is added.
