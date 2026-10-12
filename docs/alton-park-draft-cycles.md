# Alton Towers: progressive 1:1 draft reconstruction

The Wicker V12 mesh, ground-detail and access review now feeds the park cycle
workers alongside retained full-park draft layers. The real input has 4,757
native chunks. Section one is the 100-chunk Wicker review area; fourteen
balanced sections cover the remainder in 166–167 chunk batches, for 29 cycles.
Ten workers serialize disjoint canonical payloads and one native writer composes
each cumulative download. Existing accepted-geometry generation remains separate.

## Sources and scope

The base is `Alton_Towers_Mutiny_Bay_V22.mcworld`. Retained geometry comes from
the V17 evidence archive's completion, foliage, garden and path overlays and
the V22 courtyard overlay. Only rows still matching the latest native base are
retained; superseded records are withheld. The Wicker V12 terrain/platform is
not copied into the park. Its shop, station and pre-show meshes are rotated
and sampled again in the park's projected metre CRS, with terrain-bearing
foundations and compound door apertures. Paths, beds and rocks follow the park
terrain. Access uses the same deck/slab/fence generator as V12.

The park frame is local azimuthal equidistant; Wicker's frame is British
National Grid. OSTN15 and the retained terrain mosaic support the conversion.
Mesh dimensions remain metres; the small local projected scale difference is
recorded instead of stretching them. Landscape raster cells are resnapped.
The source building placement, station passenger floor and access dimensions
are still provisional. The pre-show uses printed 183.30 m snapped to grid 183.

The real snapshot contains 847,646 cells in 3,126 detail-bearing chunks and
5,139 review features. 807,921 selected foliage cells above terrain are deferred
in the initial context, so later sections visibly add detail. Other legacy
terrain, rides, buildings and reviewed bridge context remain. This is replay
of available draft geometry, not automatic architectural interpretation of
every park PDF. Detailed roofs/facades for unreviewed buildings remain upstream.

## Prepare and continue

`voxel-park-draft-cycles --job draft-cycle-job.json` creates a fresh portable
bundle containing `geometry.sqlite`, `base-world/`, `cycles.sqlite` and
`draft-snapshot-report.json`. The example job describes the retained inputs;
asset paths are relative to the job. Preparation pins source bytes, validates
native chunk coverage and checks changed baseline sections after closing and
reopening the world. Completed bundles resume through the cycle runner, not
by rerunning preparation. Incomplete preparation requires a fresh directory.

```sh
voxel-park-cycles run --plan bundle/cycles.sqlite \
  --geometry bundle/geometry.sqlite --base-world bundle/base-world \
  --output output --max-cycles 1
```

Use a larger bounded count to continue automatically. The CLI starts a fresh
process for each cycle when the count exceeds one, releasing native backend
caches between previews. A process killed by memory limits does not advance
the cycle; completed chunk checks and worker receipts are reused on resume.
For large native jobs,
stage mutable workers/native output on a local POSIX filesystem, then save a
checkpoint after completed cycles. Payloads are flushed before promotion;
canonical manifests exclude stale temporary/self-receipt files. Pending payloads
are verified before promotion and again before native publication. Failed hash
or block checks never advance the cycle.

Every draft row pins the exact expected baseline block fingerprint. It can
replace that block only in its immutable snapshot; a different baseline stops
export. Native clearing of old Wicker extrusion is bounded to new building
columns, above sampled terrain and at most twelve metres above each base.
The production compiler's registration, identity and global conflict checks
are not bypassed or reclassified as accepted controls.

## Actions and quality

Actions uses the existing `park-generation-cycles.yml` ten-job matrix,
checkpoint handoff and automatic next-cycle dispatch. Select `allow_draft=true`
for this review bundle; it defaults false and is preserved on continuation.
The workflow still needs to exist on GitHub's default branch for dispatch.
This revision runs real cycles locally; it does not claim an Actions run.

An independently initialized review snapshot requires `--allow-draft`.
`--focus-chunks` optionally supplies the first section, limited to 200 owned
chunks. No chunk gains duplicate ownership. All reports and downloads retain
`review_draft` and `production_placement_eligible: false`.

Park paving extraction now shares the whole-polygon rule: contained brick wins,
then tarmac, then explicit concrete/stone; unlabelled identified paving defaults
to stone. Mixed unrelated finishes remain withheld. This rule does not turn
arbitrary closed roof/annotation polygons into paving and does not recolour
old raster-only overlays without their polygon labels.

The first real cycle passed: 100 scheduled chunks, 84 detail-bearing chunks,
26,057 cumulative geometry cells. The writer verifies every cell of touched
sections, including air and unchanged context, and unchanged park chunk coverage.
Synthetic tests additionally cover a multi-megabyte worker handoff, protected
block replacement guards, draft opt-in, focus ownership, deferred future layers,
portable resumption and material precedence. These checks establish native
composition correctness, not in-game visual fidelity or surveyed accuracy.

The complete real run finished all 29 cycles and all 4,757 scheduled chunks,
with 847,646 cumulative detail cells across 3,126 native geometry chunks.
All 802 repository tests pass. The canonical final preview SHA256 is
`c888928d055842e9cbcc82e39460eea4312110b732060725c10ad7e4cf108bdd`.
The downloadable delivery changes the display name and spawn to Wicker paving;
the checkpoint retains the canonical preview and its original metadata.

Final native inspection found 33 air cells beneath drafted footings where raster
and saved-world surfaces differed. A separate guarded three-chunk completion
cycle filled only those air cells; no existing non-air block was replaced.
Cold readback verifies 17,431 Wicker cells and solid contact for all 559 bearing
columns. The checkpoint includes this completion cycle separately; the main
29-cycle receipts and source geometry remain immutable. Future preparation now
checks the native base beneath footings and bounds air extensions to eight blocks,
withholding larger unsupported gaps. Roof overhangs do not create foundation piers.
