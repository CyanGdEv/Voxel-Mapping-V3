# From saved corrections to regenerated geometry

Open **Review and accuracy → Try correction demo**. The original synthetic
drawing specifies an 8 m frontage; the candidate deliberately uses a 6 m
horizontal scale. This is an engineering example, not a real park model.

1. Choose **dimension**, axis **x**, value **8**, then **Add correction**.
2. Press **Save correction draft**.
3. Press **Regenerate saved corrections**.
4. The desktop runs a managed CPU worker and opens the new candidate for review.
   Select its completed job and use **Open world**, **Compare geometry** or
   **Results folder** to inspect the actual outputs.

The fixed synthetic reference is supplied automatically for this demonstration.
Its measurements come from fixture drawing constants, not from the generated
prediction. The width correction also restores the scaled window coordinates.
The before/after reports must show the changed model passing the reference
tolerances. This demonstrates correction mechanics; it does not measure real
park accuracy or train a neural model.

## Supported edits

- **Outline:** replace a defined extrusion's outer profile in its matching XY,
  XZ or YZ plane. The existing depth and holes are preserved. An outline that
  excludes an existing hole is rejected.
- **Dimension:** resize one component along X, Y or Z, anchored at that
  component's minimum coordinate. Its existing holes scale with it. A zero-span
  axis cannot be assigned a dimension.
- **Opening:** replace one overlapping existing hole, or add a disjoint new
  opening. A polygon touching the outer boundary can create a door notch.
  The resulting component must remain one valid extrusion. Ambiguous overlaps
  with several holes or other opening corrections are rejected.
- **Local placement:** rotate the complete model around its local Z origin in
  90-degree steps, then translate in local XYZ metres. Protected half-block air
  volumes require half-metre translation increments and are transformed with
  the model. This does not establish a geographic position or surveyed datum.

The application applies outlines, dimensions, openings and placement in that
order. Repeated outline/dimension/placement instructions for the same target
are rejected. Opening coordinates describe the final local profile after
dimension changes. Interior extrusion holes retain their component binding and
can participate in later revisions. Explicit native air guards, including those
needed for boundary door notches, currently have no component ownership;
further shape edits to such models remain blocked until that binding is
available. You can resume the original correction draft and save another full
iteration. The retained Wicker mesh supports the guarded placement path, while
arbitrary outline replacement of its mesh remains unresolved.

## Evidence, validation and learning

Regeneration reopens the saved review, checks its queue/batch/source hashes and
validates the saved annotations. It checks those inputs again before publishing
the success report. Every run uses a fresh directory. Original geometry,
existing decisions and source PDFs remain intact. Interrupted or failed work
can retain partial files but has no completed result or promoted checkpoint.

Outputs include original/corrected specifications and GLBs, a comparison SVG,
separate native previews/worlds, native opening/structure diagnostics and a new
hash-bound candidate review queue. Native exports are read back from the actual
saved world. Checks retain unsupported joins, missing floor support and native
aliasing; valid exports do not certify complete structural or physical accuracy.

The corrected candidate has a different identity, inferred correction evidence
and all acceptance gates withheld. Its source coverage and native diagnostic
features are computed; unavailable drawing-agreement features stay explicitly
missing. The original candidate's accepted/rejected label is never copied to
the new geometry. Independently review the new queue and explicitly import its
decision to contribute a separate training record. Existing sample counts,
source-separated evaluation and model-promotion rules still apply.

These are isolated local study worlds on a display platform. Inserting changes
into real terrain with qualified geographic placement and verified path/plaza
connections remains further work. Wicker registration, levels, identity,
materials and as-built status remain unresolved. No trained real-park checkpoint
or completed real-building accuracy benchmark is supplied.

## Independent before/after measurement

Supply a frozen `reconstruction-benchmark-v1` reference in the review window or
through `--benchmark`. The frame must be `local_xyz_metres_z_up`, with metres
and the exact building/source set. Each reference must declare
`geometry_definition: "projected_xy_bounds_origin_v1"`:

- footprint: the union of actual triangle projections into local XY;
- height: actual Z span;
- position: the selected geometry's minimum XYZ bounds;
- optional `component_id`: select one known component;
- optional opening geometry: interior extrusion holes, with an explicit
  `opening_projection` of `xy`, `xz` or `yz`.

A rotated facade in a different opening plane remains unassessed/incomplete
against that opening reference. No fitting, stretching or reference editing is
performed to improve the score. References are pinned before predictions are
derived. Declared training/evaluation overlap is checked using the active model
lineage. Review references remain audit pointers, not authenticated truth.

These metrics describe continuous candidate geometry. Native occupancy,
protected air and saved-world integrity have separate checks; a continuous
geometry score is not a voxel-accuracy or Minecraft gameplay result.

From source:

```sh
python -m voxel_mapper.building_corrections \
  --review SAVED_REVIEW_DIRECTORY --output FRESH_RESULTS_DIRECTORY
```

Use `--no-world` for models and native cells only, and `--benchmark` for a frozen
reference. All desktop regeneration uses the existing worker, cancellation and
memory controls; the 6 GB CPU-only default remains two workers and one heavy job.
