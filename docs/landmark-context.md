# Landmark context before map matching

The optional `landmark_context` stage screens native polygon candidates before `mapped_placement`. It retains eligible records byte-for-byte as JSON values and writes a separate explanation for every candidate. It does not classify or export buildings. Original extraction feeds remain available.

Enable it after drawing geometry and, optionally, exact linework/envelope recovery:

```json
{
  "drawing_geometry": {"enabled": true},
  "linework_boundaries": {"enabled": true, "envelopes": true},
  "landmark_context": {"enabled": true}
}
```

Default diagnostic policies withhold candidates below 4 square metres and candidates whose boundary follows two distinct parallel solid straight source lines continuing at least 3 metres outside the candidate, with outside length greater than twice the shared boundary length. These rules can exclude genuine small buildings or connected structures. Thresholds are configurable through `options` (`min_area_m2`, `min_continuation_m`, `continuation_ratio`). No geometry is snapped, joined, clipped or altered by this stage.

Visible native room and roof-detail labels can withhold a primitive enclosure only when its complete glyph box has one containing candidate. Hidden or ambiguous text cannot classify a candidate. Adjacent-face envelopes are excluded from room-label association: containing a kitchen does not make an entire building an internal room. Floor/roof captions supply page-level hints only.

The stage requires a unique visible printed scale pinned to the exact PDF and page. Missing scale withholds that page. Native records are checked against retained extraction; source and output hashes, options and glyph versions are checked on resume. Input grouping is limited to 100,000 records per feed; larger jobs must be partitioned by area.

Outputs are `landmark-candidates.jsonl`, `landmark-context.jsonl` and `landmark-report.json` in the stage directory. These remain diagnostic candidates. Physical boundary identity and geographic registration are still required before reconstruction.

## Real Mutiny Bay replay

Run `scripts/audit_mutiny_map_alignment.py` with `--envelopes --landmark-context` and the retained input root. `evidence/mutiny-landmark-context-audit.json` records the two pinned PDFs, glyph screens, candidate decisions, retained OSTN15 grid and mapped references.

The pools reduce from 255 to 60 floor-plan candidates and from 116 to 38 roof-plan candidates. Small-enclosure thresholds account for 185 and 65 exclusions respectively; continuing parallel boundaries account for 13 on each sheet, with overlapping reasons. No room/detail label obtains a unique complete enclosure on these real sheets, so those labels do not drive exclusions. The remaining pools produce zero map-placement hypotheses and zero cross-sheet hypotheses in the bounded search. This removes the earlier repeated-linework matches from this test; it does not establish genuine wall or roof outlines, and it adds no world geometry.
