# Exact envelopes and cross-sheet matching

The linework stage can now derive larger landmark candidates by joining adjacent
recovered faces. This removes internal room dividers from a candidate outline
without replacing the source with a rectangle, convex hull or buffered shape.
Enable it in a park job:

```json
"linework_boundaries": {"enabled": true, "envelopes": true}
```

The CLI also accepts `python -m voxel_mapper.linework_boundaries --envelopes`
alongside its existing corpus/candidates/output arguments. Envelopes enter the
existing source-checked candidate feed, so mapped placement can test them with
the original faces. They do not replace the original source geometry.

Only exact positive-length shared edges connect faces. Gaps and point contacts
cannot be bridged. Overlapping faces are not joined. Explicit holes in recovered
faces are protected: nested faces cannot fill them, including through indirect
adjacency chains. Area must equal the sum of the joined faces. This is a
topological rule, not proof that every unclassified closed loop is a physical
courtyard or void. Missing/open/curved boundaries and omitted small faces remain
limitations of the underlying linework reader.

Each envelope retains all contributing face IDs and contracts, paint references,
the native PDF/page/frame and the original extraction contract. The retained
reader rebuilds the faces and envelope from pinned native parents before using
the record. Changed provenance, source bytes or the envelope option on resume is
rejected. Bounded face, pair, vertex, provenance and page budgets apply.

Envelopes are `unclassified_region_envelope` records. They do not establish a
building, wall, roof, material, source state or accepted geographic placement.
The generic semantic exporter rejects them. Ordinary
paving extraction does not consume them.

`drawing_sheet_links.link` compares two source-bound native sheets after scaling
each into metres using its visible printed-scale review. The scale review now
binds the exact PDF SHA and page, so a different sheet's scale cannot be reused.
Similarity proposals retain all competing locations. The existing five-landmark,
held-out boundary, topology, one-metre, 85% IoU and 1% scale checks apply. Native
source-to-target transforms are returned with hypothesis indices and evidence
hashes for inspection; no geographic alignment is propagated. A passing relative
link remains unverified physical identity and is not an independent survey check.

## Mutiny Bay replay

The two pinned 1:200 sheets yield 29 ground-floor and 11 roof-plan envelopes.
Testing original polygons plus envelopes increases the candidate counts from
226/105 to 255/116. Neither sheet finds a shared map placement against the retained
45 comparison polygons in the bounded search.

Cross-sheet search finds six competing hypotheses. The strongest uses 28 distinct
outline correspondences with approximately 0.0051 m centre RMS. Three hypotheses
pass the held-out consistency checks individually, but alternatives keep the
overall result withheld. Source-context inspection shows some strongest-fit
matches are repeated section/survey linework and small fixture outlines. Those
matches do not prove physical building boundaries or a geographic transform.

Replay and inspect the full source-linked diagnostics:

```sh
PYTHONPATH=. python scripts/audit_mutiny_map_alignment.py \
  --input-root <retained-input-directory> --envelopes \
  --output evidence/mutiny-envelope-alignment-audit.json
```

The evidence records source hashes, scale glyph screens, recovered-envelope
counts, map search attempts, cross-sheet alternatives and held-out checks.
Existing park worlds are unchanged. Identifying comparable wall/roof/view
boundaries and independently checking geographic placement remain outstanding.
