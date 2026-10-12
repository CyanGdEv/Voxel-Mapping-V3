# Ordinary planning surface labels

The automatic reconstruction runner now supports standalone material labels in horizontal surface plans. Labels such as `brick`, `brick paving`, `stone paving`, `tarmac` and `concrete` no longer need structured `PATH:ID surface=...` callouts or per-polygon bindings.

The adapter splits spatially disjoint CAD glyph groups even when a PDF stores them in one text span. It retains original trace and character indices, recovers exact solid straight enclosures, and associates a complete label box only when one polygon contains it. It does not select the nearest polygon, close gaps, use an unlabelled enclosure as paving, or interpret wall/elevation/report prose as a floor finish. Nested enclosures remain ambiguous. Later paint crossing a boundary withholds that boundary.

Native glyph screens support unit rotations, preserve original glyph IDs for embedded TrueType subsets, and use 24 pixels per PDF point for text smaller than four points. Other text uses six pixels per point. The original font bytes, glyph origins and rendering are retained; minimum glyph ink and visibility thresholds remain required. Fonts or pixels that cannot be checked remain unresolved.

Within a bound polygon, brick takes precedence over stone; asphalt/tarmac takes precedence over stone. Explicit concrete or stone is retained when neither brick nor asphalt occurs. A standalone surface-role label such as `Footpath` can establish a candidate without a material word and uses the user's default stone rule. Unlabelled polygons do not receive that default. Unsupported finish combinations remain unresolved. Default stone is recorded as a user rule in feature metadata, not as printed stone evidence.

## Automatic publication

In the shared source manifest, select `semantic_annotation_contract: ordinary_surface_labels_v1` for the appropriate sources. Adapter v2 requires verified existing/as-built state and `view_kind: horizontal_surface_plan` or `mixed_plan`, with `surface_label_scope_verified: true` and the spatial evidence below. The old sheet boolean alone cannot authorize paving. A whole mixed sheet must not be declared surface-only merely because it includes some surface notes.

`surface_scope` is pinned to the PDF SHA, page and native coordinate frame. Each region represents a verified horizontal surface view, with a source evidence reference that establishes that its enclosure lines are physical surface boundaries. Regions can have holes excluding rooms, title blocks, survey annotations and other views. This is per-view scope evidence, not a hand-authored reconstruction recipe for every polygon:

```json
{
  "surface_scope": {
    "document_sha256": "<exact PDF SHA256>",
    "page": 1,
    "coordinate_frame": "pdf_native_points_y_up",
    "regions": [{
      "id": "external-surface-view",
      "view_kind": "horizontal_surface_plan",
      "physical_surface_boundaries_verified": true,
      "verification_reference": "<source evidence establishing this view and boundary convention>",
      "geometry": {"type": "Polygon", "coordinates": [[[0,0],[200,0],[200,200],[0,200],[0,0]]]}
    }]
  }
}
```

The example coordinates are illustrative. Scope must come from the actual drawing context; the adapter does not invent that evidence. A complete candidate must lie within exactly one region. It cannot cross a region edge or an excluded hole, be clipped into a region, or be reconstructed by joining adjacent views. Overlapping matching regions are ambiguous. Source/page/frame mismatches and invalid or nonfinite region geometry are rejected. Published features retain the region identity and its verification reference. Once the regions and registration are established, the area cycle processes supported labels automatically.

This mode consumes an established per-sheet registration, not a new object recipe. Source metadata binds the exact PDF SHA, page, `registration_coordinate_frame: pdf_native_points_y_up`, and verified local landmark identity to the horizontal registration review. Each retained control/checkpoint must match the shared independent survey references, including ID, target coordinate, source ID, source bytes and accuracy. The fit is recomputed using the printed scale, at least three noncollinear controls and two independent checkpoints; the one-metre error budget and registration domain remain enforced. A fabricated stored matrix cannot change placement.

The bridge dispatches ordinary sources to this adapter. Its registered paving features feed the automatic recipe builder, compiler, ten workers and native assembler already used by area cycles. No per-polygon interaction is needed once the sheet inputs are established. Complete physical area inventories remain separate from the subset discovered by this adapter.

## Real Mutiny Bay audit

Two retained native PDFs were audited: `3023-01 Existing Site plan` and `3023-08 Existing ground floor plan`. The reader found 54 relevant labels and eight unique enclosed surface candidates on the ground-floor plan: four brick, two tarmac and two paving/default-stone candidates. Forty-six labels lack a supported containing enclosure. The site's title does not verify every view or label's physical identity, and these are unplaced candidates, not accepted current park features. Independent sheet registration and verified surface scope are still missing; no new park world was published.

Evidence is retained in `evidence/mutiny-ordinary-surface-audit.json`, `evidence/mutiny-ordinary-surface-labels.jsonl` and `evidence/mutiny-ordinary-surface-candidates.jsonl`. Native integration tests use a separate fixture sheet: the controller creates a recipe without polygon bindings, runs ten payloads, exports a real Bedrock cycle and cold-reads brick, asphalt and default-stone cells, terrain contact, and an unlabelled enclosure left unchanged.

A subsequent drawing-context inspection found candidate enclosures inside rooms and across other plan linework. Their material labels do not establish physical paving footprints. All eight remain withheld pending boundary-role evidence and registration; none is assigned an accepted surface region. `evidence/mutiny-surface-context-review.json` records this inspection and the coordinate preflight. The only national-grid coordinate pair found in the selected corpus was on application forms, not attached drawing controls; it cannot register a sheet.

A read-only audit requires only pinned documents; it never creates registered world features:

```sh
PYTHONPATH=. python -m voxel_mapper.ordinary_surfaces \
  --documents documents.json --output ordinary-audit --max-pages 1000
```

The document list contains `file`, `sha256`, and optional `title`/`source_state` fields. Audit inputs and outputs are checksum checked on resume. Building elevations, roof planes, stairs, fences and ambiguous or scanned annotations still require their own ordinary-drawing adapters.
