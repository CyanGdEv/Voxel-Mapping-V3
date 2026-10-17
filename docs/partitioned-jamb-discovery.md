# Exact work partitions for dense jamb discovery

Component inventory v3 resolves the remaining Wicker south-west group-limit
failure. It processes independent compatibility components under the existing
active-group limit. The operation retains every eligible pair and leaves source
pixels, endpoints, drawing thresholds and physical-role uncertainty unchanged.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-partitioned-jambs-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-partitioned-jambs-job.json --output output/partitioned-jamb-audit.json
```

The example enables the existing automatic views and component inventory, with no
manual rectangles, traces or exclusions. It includes known-source acquisition;
actual validation reused checksum-verified originals offline. Area/controller
contracts advance to v8/v6. Older area jobs require a fresh output directory.

## Exact compatibility components

The old scanner stopped once the whole crop exceeded 512 original vertical-run
groups. The south-west crop contains 157 groups at threshold 220 and 787 at 235.
Many cannot participate in the same pair because their endpoints or width differ.

On this specific failure, the stage retries with `partition_groups=True`. The
scanner retains at most 4,096 complete original groups per threshold, matching
the existing stroke-context retention cap. A separate work graph connects two
groups only when their original left/right gap is within the declared width
range (normally 20–600 pixels) and both endpoint differences are at most two
pixels. This is before head tests; every potentially valid directed pair belongs
to one connected component. Transitive endpoint bridges stay in the same component.
Groups without a compatible partner remain as explicit singletons.

Each component must contain at most the configured 512 active groups. An oversized
connected component is withheld whole; it is never split to evade the limit.
Pair discovery only compares groups with the same component owner and keeps the
original indexed pair ordering and source indices. Threshold consensus still runs
over all retained pairs across both thresholds; no per-component consensus cutoff
loses alternatives between threshold variants.

The work graph describes computational compatibility, not physical connectivity,
a drawing-object boundary or a building part. No endpoint snapping, source crop,
nearest-pair choice, hull or gap repair occurs. Partitioning supports the all-pair
scope only; adjacent-jamb scope rejects this option because its competition rules
need a different proof.

## Limits and receipts

The optional retained table cap is 4,096 groups per threshold; the component limit
remains 512. Indexed pairs remain capped at 8,192 per threshold and work at 100,000
checks per attempt, including graph construction. The raster limit remains six
million pixels/3,000 pixels per side. The original capped attempt and the retry
each have their own unchanged work limit. Exhaustion discards that attempt's whole
candidate/index result. Nothing silently raises an oversized component, pair or
work cap.

Successful `group_partition_proofs` retain all group memberships, component sizes,
eligible directed-pair counts and a zero-cross-component-pair claim checked by the
audit. Whole original group/pixel evidence remains in the existing scan index.
The component report preserves the failed capped runs in
`legacy_group_limit_attempts`, then exposes the successful selected scan. The raw
and residual search scopes remain distinct. The residual scope still excludes
the recorded repeated-stroke groups, which can include real repeated mullions.

Component contracts pin the new partition kernel. Cached replay checks source
PDFs, crop/feed hashes and every output. The audit independently enumerates all
potentially compatible original pairs, checks component ownership and directed
counts, reproduces geometry transforms and compares a fresh six-file pack.
With `--baseline /path/to/pr38/pack`, it also checks unchanged native geometry and
the original capped attempts against the prior hash-verified pack.

## Wicker validation

The south-west components have maximum sizes **13 and 373** at the two thresholds,
with **76 and 3,983** eligible directed pairs. Both fit the active-group budget.
The selected raw and residual scans each complete in **29,208 checks**, producing
the same **52 threshold-consensus families**. No repeated-stroke exclusions were
present for this view; the raw result covers the whole declared all-pair recipe.
That recipe still detects only a particular jamb/head pattern, not all physical
openings.

| Elevation | Residual families | Residual result |
| --- | ---: | --- |
| South-east | 18 | Complete within residual scope |
| South-west | 52 | Complete through exact work partitions |
| North-west | 192 | Complete within residual scope |
| North-east | 29 | Complete within residual scope |

All four residual passes now complete, retaining **291 families**. The broad
south-east/north-west passes still exceed their pair cap, so the overall
`all_requested_passes_completed` flag remains false. All 110 native regions,
14 wall bands, 28 rectangle cycles and their glyph context remain unchanged.
The fresh replay reproduces all six inventory files. The compatibility audit
checks **8,118 eligible pairs and 1,888 group occurrences**, covering the separate
raw and residual retries without implying independent physical observations.

Regression cases cover more than 512 original groups in separate components,
legacy/index equivalence where both fit, transitive bridges, exhaustive pair
coverage, failed component/work/retention/pair caps, late-consensus proof removal,
threshold ambiguity, source
exclusions and automatic fallback provenance. Receipts are under
`docs/evidence/jamb-partitions/`.

The source also contains shading, cladding, background structures and annotations.
The 52 families are source hypotheses. Physical window/door identity, complete
boundaries, plan/elevation correspondence, construction state, registration and
vertical datum remain unresolved. This pass adds zero accepted physical components,
world blocks or training labels and introduces no trained semantic model.

The final local suite passes **1,571 tests**, including nine new partition regressions.
The related focused suite passes 39 tests.
