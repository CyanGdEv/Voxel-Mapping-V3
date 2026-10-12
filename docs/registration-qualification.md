# Drawing-frame qualification before park recipes

The area pipeline can qualify horizontal drawing frames before an accepted area
boundary or component recipe exists. Each extracted original page receives a
checksum-bound qualification record or a missing-evidence record. This separates
registration readiness from semantic reconstruction; a qualified frame creates
zero components and zero world blocks.

The same `qualify_page` implementation is used by the explicit object bridge and
the ordinary surface bridge. It requires pinned original drawing bytes, permitted
reuse, a projected metre CRS and one visibly checked printed scale. It supports
two existing correspondence contracts:

- Exact `CP:identifier` labels with unique straight leaders to crosshairs, joined
  to an independent survey registry.
- Supplied native-point correspondences bound to the original PDF, page and
  coordinate frame, with verified local identities and matching survey records.

Both recompute a similarity fit from at least three non-collinear controls and
two independent checkpoints. Survey source hashes, identities, accuracy, scale,
residuals and the one-metre error budget remain checked. A caller-supplied accepted
matrix cannot replace recomputation. Invisible or layered text, an overpainted
scale, unverified correspondence and conflicting source policies cannot qualify.
The ordinary adapter now retains its combined reference/attachment error budget,
expected scale and target CRS, enabling later contextual uncertainty assessments.

A qualification receipt retains the raw registration review, checked domain and
remaining component requirements. Existing/proposed state is preserved. A proposed
sheet can have a qualified horizontal frame while still being rejected by the
component adapter. No polygon is accepted as a physical object merely because
its page can be registered.

## Area configuration and replay

Automatic reconstruction enables the preflight by default, reusing its manifest,
references and shared knowledge store. Enable an evidence-only audit independently:

```json
{
  "registration_qualification": {
    "enabled": true,
    "manifest": "inputs/manifest.json",
    "references": "inputs/survey-landmarks.json",
    "knowledge_store": "shared/evidence-memory.sqlite",
    "max_pages": 1000
  }
}
```

Omit manifest/references to inventory missing evidence; this cannot qualify a
frame. The report appears as `registration_qualification` in the area report.
Set `enabled` to false to disable the separate audit; component bridges still
perform qualification before emitting features.

```sh
python -m voxel_mapper.registration_qualification \
  --corpus work/mutiny-bay/corpus \
  --geometry work/mutiny-bay/drawing-geometry \
  --store shared/evidence-memory.sqlite --output work/frame-qualification \
  --manifest inputs/manifest.json --references inputs/survey-landmarks.json
```

Exact page facts are reused across output directories. Original PDFs, retained
payloads, source policies and dependency ancestry are checked on replay. Changed
references, target CRS or source policies create new audits; rejected parents
block reuse. Adding an unrelated source preserves unchanged page computations.
The area/controller contracts pin qualification inputs and versions. Automatic
recipe contract v4 and bridge v3 require a fresh controller/output directory when
upgrading, with stable memory retained. At most 10,000 pages, 10,000 source policies
and 1,000 survey references are accepted; each original PDF has at most 1,000 pages.

## Retained Mutiny audit and remaining work

`scripts/audit_registration_qualification.py` checks original pins, unchanged
resume and fresh-output reuse. The retained Mutiny audit covers 213 pages and
reuses all 213. All pages lack a unique supplied verified source policy and an
independent survey registry; 198 also lack an unambiguous visibly verified scale.
Zero real frames, physical components or blocks are accepted. The receipt is
`docs/evidence/registration-qualification-validation.json`.

Tests qualify independent-survey fixtures and exercise them through the existing
automatic component recipe, compiler and native cycle tests. They also cover
missing evidence, source/receipt tampering, changed CRS/references, reviewed
rejections, overpainted scale, ordinary-frame budget retention and area integration
before a boundary exists. These are capability tests, not real Mutiny placement.

The next real test still needs independently identified park landmarks, source
policy/view/state evidence, terrain and an accepted boundary. General cross-view
building assembly, automatic correspondence certification and training feedback
remain unfinished. The preflight does not infer these from shape agreement.
