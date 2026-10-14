# Automatic source dimension comparisons

`voxel-building-data compare-source-dimensions` recomputes both the original
plan-enclosure hypotheses and the independent original elevation-region feed.
It measures each retained region's horizontal extent in the original displayed
view at its nominal printed scale, then compares that width with every enclosure's
long and short diagnostic extents. No manually supplied width target is used.

Use a request with this structure:

```json
{
  "version": "building-dimension-feed-v1",
  "footprint": {
    "version": "source-footprint-hypotheses-v1",
    "plan_audit": {}
  },
  "facade_feed": {
    "version": "building-facade-feed-v1",
    "buildings": []
  }
}
```

Populate `plan_audit` using the [original plan audit contract](source-plan-footprint-audit.md),
and `facade_feed` using the [facade source feed contract](raster-facade-source-feed.md).
Supply exactly one facade building with the same declared building ID as the
plan request. Paths are relative to the outer request. The ID links a declared
scope; it does not independently establish building identity or revision.

```bash
python -m voxel_mapper.building_pipeline compare-source-dimensions \
  --config source-dimension-job.json --output fresh-dimension-feed
```

The stage runs both source extractors automatically. The footprint audit's
optional `elevation_width_candidates_m` is ignored in this channel. Original
checksums and size limits are checked before extraction and again before the
final directory is published. Extraction failures retain diagnostic partial
directories and cannot publish accepted geometry.

`comparisons.json` retains every match and conflict, including competing regions,
roof/material-region roles, plan corridor dependencies, source document and page
identities, exact candidate/region record hashes, region width, signed difference
and measurement channel. Raw nominal extents and inverse furniture-layout extent
hypotheses remain separate. No geometry is stretched, snapped, simplified or
replaced by a bounding rectangle; these are diagnostic measurements only.

A material region may cover only part of a facade. Its width cannot be treated as
a full building-side width merely because it agrees with a plan extent. Neither
channel establishes physical correspondence, per-view state, scale applicability,
void/opening roles, exterior-boundary identity, revision or registration. No
candidate is selected, no complete building is assembled and no training label
or park block is produced. `review-queue.json` binds a null outcome to the full
comparison report and the original source hashes.

The default difference window is 0.25 m. `options.tolerance_m` may reduce it down
to 0.001 m; this is a discovery window, not a measured physical accuracy bound.
`options.max_comparisons` may reduce the 100,000-check budget. Inputs are bounded
to 128 enclosure candidates and 1,024 regions. Budget exhaustion discards all
partial comparisons. Missing scales, incomplete footprint hypotheses, invalid
facade sources and zero retained regions cannot generate positive matches.
Metadata reads are bounded to 64 MB; total staged output is bounded to 512 MB.

Synthetic tests cover source-feed recomputation, CLI operation, repeated replay,
manual-target exclusion, ambiguous matches, region role retention, corridor
support, separate layout channels, invalid scales/frames/geometry, checksum
mutation before and after comparison, source preservation and budget withholding.
This implementation has not yet been replayed against the recovered Wicker
originals in this workspace; fixture results do not establish real shop identity.
