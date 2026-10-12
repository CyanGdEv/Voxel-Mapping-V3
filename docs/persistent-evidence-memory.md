# Persistent reconstruction evidence

The intended pipeline discovers planning applications, retains original documents,
extracts source geometry, registers drawing frames, reconstructs physical components,
checks the native world, and carries verified evidence into subsequent cycles.
The existing scraper and PDF corpus already retain acquired documents and page
extraction. This change adds shared memory for drawing registration and semantic
results across output directories and area cycles.

## Implemented

`automatic_reconstruction` now passes a shared SQLite evidence store into the drawing
registration bridge. The default is `evidence-memory.sqlite` in the area work root.
Set `automatic_reconstruction.knowledge_store` to a stable path relative to the area
job to share memory between fresh work directories as well.

Each page fact stores its original PDF hash, drawing source policy, reference-file
hash, page number, adapter versions, registration review, feature records and withheld
decisions. Parent facts retain the policies and identities of the drawing and referenced
survey sources. Changing source bytes, registration references, relevant policy or an
adapter version creates a new fact; adding an unrelated drawing preserves the existing
page key. The original PDF is checksum-checked before memory is consulted. Retained
payloads are checksum-checked on read. Independent sources and checkpoint rules remain
unchanged. A cached candidate is never upgraded merely because it was cached.

For example, a registered frame already containing a building and a path can reuse its
original checked transformation and semantic feature records in the next area output.
It avoids repeating extraction and registration. This does not establish correspondence
between an unknown path drawing and a nearby building. The latter needs a matcher,
correct physical identities and independent checks before it can share an alignment.

Rejections include a reviewer, reason and review reference. They invalidate the rejected
fact and every dependent fact. Retained output directories are checked against memory
before the bridge returns them, so rejected evidence cannot silently return from a
completed bridge cache. Independent branches remain available. Rejections are retained
idempotently and cannot be erased by recomputing the same inputs.

```sh
python -m voxel_mapper.evidence_memory --store /path/evidence-memory.sqlite report
python -m voxel_mapper.evidence_memory --store /path/evidence-memory.sqlite reject \
  --fact-id FACT_SHA --reviewer REVIEWER --reason 'Wrong landmark correspondence' \
  --review-reference QA_REFERENCE
```

The store is a runtime asset and must persist with the job's source cache. SQLite
transactions serialize writes and rejection propagation. Use SQLite backup rather than
copying only the main database file while a writer has it open.

## Remaining automation

- Discover and rank landmark correspondences across different drawing views and
  source dates. Nearby geometry is a search hint, not proof of identity.
- Reuse verified physical anchors with a common CRS, independently validated frame,
  bounded spatial domain, construction state and accumulated uncertainty. Descendants
  must not supply supposedly independent checks for their own ancestors.
- Track individual accepted component and placement facts, not just page computations.
  The generic dependency store supports these records; their validators and matcher
  are not implemented by this change.
- Revalidate dependencies at chunk dispatch and final world publication. This change
  checks bridge reuse; it does not revoke previously published worlds or cancel a
  native cycle already dispatched before a rejection.
- Translate reviewed mistakes into appropriate training examples and evaluate held-out
  buildings before model promotion. The existing building ranker is separate; this
  memory generates no training labels, retraining or model promotion automatically.

The Mutiny/Wicker/Katanga trial still has no independently registered full-area recipes.
No new real-world anchors are accepted by this change. The shared-cache tests use
explicit, independently checked survey fixtures. Fully automatic full-area discovery,
cross-view assembly and placement remain incomplete.
