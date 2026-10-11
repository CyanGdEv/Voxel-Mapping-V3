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

Claims retain the exact native text and original-font glyph screen. Hidden or unsupported glyphs remain unbound. A visible roof-role label binds only when its entire glyph box lies inside one primitive recovered enclosure; overlapping alternatives cannot be resolved by selecting the smallest or nearest polygon. The association supports a candidate roof region, not verified physical roof boundaries.

Printed heights retain their stated units, or `unspecified` when none are printed. `ridge u/s` is recorded as an underside value, not a roof apex. Drawing levels have no assumed ODN datum. Wall heights and eaves/ridge values are not assigned to geometry through proximity, and cannot set world heights. Roof pitch, roof-to-wall offset, exterior identity, openings and independent registration remain separate requirements.

## Resume and source checks

The stage replays each source PDF using the pinned native extraction options and compares it with retained extraction. Complete extraction, complete boundary recovery and a source-bound visible printed scale are required. Source/feed/output hashes and interpretation/recovery/glyph versions are pinned. Extraction run/resume counters are excluded from the semantic pin so a routine extraction resume does not invalidate interpretation.

Outputs are `architectural-pages.jsonl` and `architectural-report.json`. Source PDF edits, retained extraction differences, changed options and altered outputs are rejected. Both generic park jobs and area-cycle extraction expose the stage.

## Mutiny Bay replay

`scripts/audit_mutiny_architecture.py --input-root RETAINED_INPUT_ROOT --output AUDIT.json` replays the two pinned floor/roof PDFs with a 0.25-point short-edge cutoff and 10,000-candidate extraction budget.

The real floor plan yields 67 unique paired-line bands, with 88 competing pairs withheld. The roof sheet yields 11 bands, with five competing pairs withheld. These are unverified geometric hints, including bands on the roof sheet that cannot be called walls from their location alone.

There are 18 floor-plan and six roof-sheet architectural text claims. Ten floor-plan claims pass the glyph consistency screen; none of the roof-sheet claims does. No flat/material roof label passes both glyph consistency and unique complete enclosure association in this replay. Wall descriptions and height values remain unbound. `evidence/mutiny-architectural-interpretation-audit.json` records the source pins, exact paired geometry and references, text screens, ambiguity counts and limitations. No world geometry is generated.
