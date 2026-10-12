# Automatic matching across drawings

The contextual matcher proposes a horizontal frame for an unplaced drawing using
registered landmarks retained from prior bridge runs and area cycles. It generates
outline associations itself; a hand-prepared candidate/reference pairing file is
not required. It is an algorithmic matching stage, not a newly trained AI model.

## Algorithm

1. Read checked drawing-page facts from shared evidence memory. Preserve their
   semantic polygons, source identities, original horizontal registration domain,
   control/checkpoint source hashes and dependency ancestry. Non-polygon features
   and unregistered pages cannot become matching references.
2. Extract shape descriptors from the already retained native polygon feed. Compare
   aspect ratio, rectangle fill and area at the source's visible printed scale.
   If a candidate already has a source-bound semantic family, require it to match.
3. Test pairs of possible correspondences, then require at least three distinct,
   non-collinear object outlines to agree with one orientation-preserving similarity
   transform. Verify every supporting outline at least 90% IoU and centroid error
   at most one metre. Nested outlines cannot stand in for several objects.
4. Retain competing placements, ambiguous assignments, truncated association lists,
   exhausted fit budgets and scale disagreement as explicit review flags. A unique
   contextual proposal is still not an accepted registration.
5. Save per-page hypotheses with dependencies on the retained landmarks. Reuse exact
   page inputs on restart or in another output directory. Adding unrelated pages
   does not invalidate their keys. Adding or rejecting landmarks creates a new
   immutable matching audit. Rejected ancestors cannot be reused.

A source drawing cannot independently align itself using landmarks extracted from
its own bytes or evidence roots. Bounds are 64 source objects per page, 1,000
landmarks, 2,000 pair fits per page by default, and 1,000 pages per stage. Oversized
source groups are withheld rather than silently sampled into an accepted result.
The original PDF hashes are rechecked on resume, and final outputs are checked
against current memory dependencies before committing their report.

## Pipeline and replay

Area jobs with automatic reconstruction enabled run contextual matching by default.
They use the automatic reconstruction manifest's CRS and shared knowledge store.
This discovery stage can run before an accepted area boundary exists. Its report
appears as `cross_drawing_alignment` in the area report. Matching references from a
new bridge run become available to following area stages or reruns.

The stage can also be enabled independently:

```json
{
  "cross_drawing_alignment": {
    "enabled": true,
    "target_crs": "EPSG:27700",
    "knowledge_store": "shared/evidence-memory.sqlite",
    "max_pages": 1000
  }
}
```

Setting `enabled` to false disables the stage explicitly. Changed automatic jobs
use automatic recipe contract v3 and require a fresh controller work directory;
a stable configured knowledge store still allows prior page computations to be
reused. Matching audits are stored under their own contract hash.

```sh
python -m voxel_mapper.cross_drawing_alignment \
  --corpus /path/area/corpus --geometry /path/area/drawing-geometry \
  --store /path/shared/evidence-memory.sqlite \
  --output /path/context-matching --target-crs EPSG:27700
```

`scripts/audit_cross_drawing_alignment.py` verifies unchanged resume and fresh-output
reuse against retained original PDFs. The real Mutiny audit processed 213 pages:
198 need an unambiguous visible scale and 15 await registered landmarks. No real
registered landmarks are present in that trial memory, so zero registrations,
world blocks or training labels were accepted. All 213 records were reused in a
fresh output directory with an identical proposal stream.

## Remaining acceptance and learning

The algorithm can propose that several source outlines correspond to known nearby
objects. It cannot infer verified physical identity, source view extent, current
construction state or independent checkpoint evidence from shape agreement alone.
It does not apply a tentative frame to every path or elevation elsewhere on the
sheet. Those checks must precede any transformation of new physical components.

Geometry dates and alternative source revisions remain separate evidence; this
change does not choose a current revision automatically. Parent registration
error remains available in landmark facts, but an accumulated uncertainty model
for chained placements is not yet implemented. Source-bound landmark identity,
independent checkpoint matching and component-level placement validators are the
next acceptance stages. Only after those stages can building A safely help place
path A and provide reusable anchors for another drawing.

Reviewed correspondence decisions need a dedicated alignment training dataset and
held-out source/building evaluation. The existing building ranker is not trained
by these hypotheses. This change creates no positive labels from its own guesses
and performs no automatic model promotion.
