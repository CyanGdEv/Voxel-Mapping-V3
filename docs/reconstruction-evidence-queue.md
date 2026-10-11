# Reconstruction missing-evidence queue

An area run with `architectural_interpretation.enabled: true` now automatically
prepares `reconstruction-evidence-queue/missing-evidence.json` after the source
architectural review. The area report and full sweep expose its summary.
This is a source-bound requirement planner, not an evidence-discovery service
or a reconstruction solver. It does not download additional documents,
accept candidate geometry, assign heights or advance world-generation readiness.

Each reviewed source page gets view-scope and horizontal-registration requirements.
Each traced region beside a room-to-outdoor wall candidate adds physical-exterior,
plan/elevation-correspondence, relative-dimension and vertical-datum requirements.
A region ID identifies its source face, not a certified building wing or room.
Each task retains its source PDF/page, complete page-record hash and exact proof
location. Exterior tasks retain every unpaired original ring/segment index,
protected-hole count and paired-boundary fraction. No unsupported piece becomes
an opening or an absent wall.

Dependencies describe evidence needed for interpretation: correspondence depends
on scope and physical exterior; relative dimensions depend on correspondence;
absolute datum depends on horizontal placement. They do not prohibit searching
for the documents supporting those requirements in parallel. `search_terms`
are targeted inputs for a later retained-document search/acquisition stage,
not completed searches or established source matches.

Task identities depend on area, source page, requirement kind and source-region
identity. Source-record changes update proof hashes without renaming an unchanged
requirement target. Reordering pages does not change the sorted output. Repeated
source page identities reject. The default task budget is 10,000; its maximum is
100,000. Exhaustion removes all partial tasks and dependencies instead of retaining
an incomplete plan. Page and segment inventories have independent bounds.

The queue pins the architectural report and its verified page-stream hash. An
unchanged run validates and reuses the output, reporting zero newly prepared
tasks. Modified source contracts, page streams or queue outputs reject resume;
use a fresh run for intentional evidence changes. Existing source/world artifacts
are preserved. The area-controller version is bumped to v2 for this behavior,
so old v1 controller runs require a fresh work directory and can retain their
previous native world as the configured baseline.

## Mutiny Bay replay

```sh
PYTHONPATH=. python scripts/audit_mutiny_evidence_queue.py \
  --input evidence/mutiny-wall-perimeter-coverage-audit.json \
  --output evidence/mutiny-reconstruction-evidence-queue-audit.json
```

The existing-floor-plan audit produces ten requirements: two page requirements
and four for each courtyard/storeroom containing source region. It preserves
495 unpaired and two partially paired segment references, plus the courtyard's
25 protected holes. This replay is limited to the retained floor-plan perimeter
audit; it is not a complete area inventory or a replay of all 213 acquired pages.
All tasks remain missing evidence and no world blocks are generated.

The retained-document matcher now consumes these requirements, searches acquired
native PDF text and records attempts by requirement plus corpus hash. See
[retained-evidence-matching.md](retained-evidence-matching.md) for candidate proofs,
benchmark-label review and optional official archive corroboration. New evidence must still
pass view, physical identity, dimensions, state and registration checks before
normalization and the existing ten-worker native generator.
