# Explicit material callout connections on Wicker drawings

The park pipeline can now trace a narrow class of ordinary CAD material callouts: a numbered text label, a unique unbranched chain of straight native strokes, an explicit filled triangular arrowhead, and the matching numbered roof/wall legend entry. This produces a source-linked material anchor candidate. It does not infer an entire component outline or promote a feature into the world.

## Real source results

The same four hash-pinned PDFs used for the native annotation test were processed. The shop elevations provide 12 connections; the maintenance plans/elevations provide 11. Eight point to roof material legends and 15 to wall material legends. Multiline legend entries retain their original native text spans and paint identities, including material descriptions on continuation lines.

After the final visibility screen, eight roof connections remain `explicit_material_anchor_candidate`. All 15 wall connections are `withheld_label_or_legend_visibility`: later white background masks intersect font-metric text boxes on preceding legend lines. This is a conservative screening result and can over-report obscuration; it is not a claim that the rendered legends are actually unreadable. Resolving it requires glyph visibility evidence, rather than silently ignoring a small overlap.

The maintenance overlay was inspected against the rendered source sheet. The recovered leader chains follow the original arrows, without manual endpoint transcription. This visual check is diagnostic, not proof of material/as-built identity or national-grid position.

No supported filled-face polygon was reproduced at the arrow endpoints. These elevations contain linework and shading rather than one usable filled polygon per face. The material anchor identifies a location with a candidate roof/wall class; it does not define the face extent, openings, depth or extrusion axis. All records therefore keep `component_association_verified`, `outline_identity_verified`, `registration_verified` and `accepted_feature` false.

The existing site section has no matching numbered legend. The proposed section exceeds the adapter's 100,000-path budget and is withheld explicitly. It uses different prose annotations and needs a separate adapter. No source is discarded silently and no fallback nearest-component match is used.

## Matching rules and limitations

- Match the exact number to one supported legend. Duplicate legend numbers are ambiguous.
- Screen native text rendering and layers. Retain the text boxes, trace indices and paint sequences of multiline legends.
- Candidate label attachment uses a font-relative distance to a terminal stroke endpoint. This is a heuristic that remains unverified; it never picks the nearest of several valid chains.
- Chain traversal is limited to four edges, no branches or cycles, and 1,000 PDF points of length. A unique explicit triangular arrow must terminate the chain.
- Stroke connectivity is quantized to 0.001 PDF points. This is source-page precision, not world accuracy.
- Clipped/layered paths, curved leaders, unsupported dashes and ambiguous arrows are excluded. Filled-path containment is retained only as paint evidence, never as automatic component identity.
- A page allows at most 100,000 native paths, 10,000 text spans, 500,000 characters, 40,000 graph nodes and 500 matching labels. PDFs and batches retain the existing 20 MB / 1,000-page and 1,000-document / 10,000-page bounds.

The output stores coordinates in unrotated MuPDF page points. View scales, drawing state, actual material identity, vertical datum and independent horizontal registration remain separate requirements.

## Run and integrate

A document list uses the same pinned `file` and `sha256` entries as the native annotation extractor:

```sh
python -m voxel_mapper.drawing_callouts \
  --documents documents.json --output material-callouts
```

For the four Wicker versions, first run `scripts/replay_wicker_annotations.py` with the exact PDFs. It writes `wicker-annotation-documents.json` beside them; use that list above to reproduce the retained callout output.

Add this to an existing park job:

```json
{"drawing_callouts":{"enabled":true,"documents":"documents.json","max_pages":10000}}
```

The compile/reconstruction stage pins the callout contract and output checksum. `callouts.jsonl` is evidence, not a geometry feed. Completed output can be reused only when input bytes and output hashes match; interrupted runs require a fresh output directory. Each page with an unsupported budget or structure receives a withheld receipt.

Retained evidence: `evidence/wicker-material-callouts.jsonl`, `wicker-material-callout-report.json` and `wicker-material-callout-validation.json`. The real-source report still records zero accepted controls, zero checkpoints and zero world additions.

The next step is associating these anchor points with complete view-specific face boundaries, and resolving the wall legend visibility screen. Independent registration evidence and a verified vertical datum are still required before placement. Elevation markers, bridge geometry and path boundaries are not resolved by this adapter.
