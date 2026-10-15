# Provisional planning-component review worlds

The Wicker example places an existing source-derived shop study onto dated
terrain and mapped paths for visual inspection. It preserves both retained
orientation hypotheses as separate worlds. This is an explicitly estimated
review scene: the study was assembled previously through manual source review,
and this job does not establish automatic complete drawing reconstruction,
independent placement, as-built identity or a trained production model.

The normal `world-pilot-v1` job continues to exclude these components. Review
geometry requires a separate `world-pilot-review-v1` job and the explicit policy
`estimated_review_only`. The exported world name starts with **PROVISIONAL
REVIEW**, the embedded quality report identifies the review component, and every
component voxel has `accepted_physical_geometry: false`. Accepted planning counts
and training labels remain zero. Review geometry is never returned as an
accepted planning adapter record.

## Retained source inputs

The job requires the exact original PDFs at these repository-relative paths:

* `retained-source-input/wicker-shop/files/08afa2513a3cb9ab35b515bcdbd5acb16b125ca5e5ffcedc4e2e14a7e10d9ad3.pdf`
* `retained-source-input/wicker-shop/files/d1a7251596b240489c145e76ac06f94448c76972b156f64b4a985753c532c0b6.pdf`
* `retained-source-input/wicker-shop/files/6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047.pdf`

Keep these originals outside Git; that directory is already ignored. The supplied
review bundle includes them in this layout for local replay. Each source PDF,
study model, direct parent-evidence file and placement file is checksum checked
before generation and again before publication. Missing or altered originals
prevent generation. A model's original PDF references must be represented by
retained bytes, and its direct study-parent hashes must be supplied. Those checks
establish input identity, not independent physical correctness or reuse rights.

The fallback was selected after Smiler existing/proposed PDF requests returned
HTTP 503 over both checked transports. An October 7 Actions artifact was also
downloaded and inspected: it contains reports but no original PDFs. Other Actions
artifacts were inventoried, not all downloaded. The catalogue's repeated
topographical-survey lead refers to Wildwood, a separate private property, and
cannot supply park controls. The receipt is
`docs/evidence/pilot-review/source-selection-2026-10-15.json`.

## Generate both orientation hypotheses

Install `.[planning]`, restore the three originals, then run from the repository:

```sh
python -m voxel_mapper.world_pilot \
  --job examples/wicker-component-review-a-job.json \
  --output output/wicker-review-a

python -m voxel_mapper.world_pilot \
  --job examples/wicker-component-review-b-job.json \
  --output output/wicker-review-b
```

Use fresh output directories. Each exports `park.mcworld`, ordinary pilot reports,
`review-component.json` and a source/native comparison SVG/JSON. The original
verified-world pipeline remains unchanged. The report retains the opposite
orientation, rather than treating the context preference as an accepted choice.
The source study's `world_placement_eligible` field remains false.

Terrain comes from the original EA P_10682 survey on 5 January 2022. Downloaded
DTM/DSM rasters match their retained original hashes; archive ZIP bytes differ.
The included 120 by 120 metre crops retain the matched survey and native BNG
grid. Ground coverage is complete; DSM nodata remains explicit. The scene uses
DTM ground, not DSM-derived track or floor heights. Its fixed OSTN15 operation
is the same pinned regional operation used by the area pilot.

The model is rotated in local metric coordinates before voxelization. Its BNG
bearing is converted through the local tangent; the source mesh is not stretched
or rotated after voxelization. Nearest-metre anchor/floor offsets are recorded.
Terrain intersection or missing ground withholds the entire review scene. A
review level pad uses the existing estimated-foundation builder, preserves
source openings, limits fill depth to 16 blocks and never excavates terrain.

Both Wicker jobs explicitly use review floor **184 m**, following the retained
clearance experiment. It is not a measured ODN shop floor. The self-fitted roof
reference and proposed printed floor do not certify that elevation. Materials,
floor and foundation fill remain estimates. The three elevated OSM paths without
explicit absolute heights are withheld and reported as generation errors; they
are not flattened onto the terrain or silently removed from the input inventory.

The retained study also carries unresolved cross-view canopy height, roof/wall
centring and construction-detail questions. The original model and its direct
evidence files are included in the review bundle; visual preference does not
resolve those source ambiguities.

Native export checks all written blocks and unwritten air. The comparison also
reads component materials from the saved native world. This establishes storage
and rasterization behaviour, not real-world fidelity. Minecraft inspection,
source-to-building identity, floor datum and independent controls/checkpoints
remain outstanding. The bounded entrance audit below checks a conservative
collision route; it does not replace Minecraft inspection.

## Access review and estimated approaches

Review jobs now audit supported standing positions, two metres of headroom,
doorway-to-interior connectivity and routes from emitted mapped walking surfaces.
They choose an integer-height spawn with bearing support and clearance instead
of the previous fixed position above the terrain. Ordinary `world-pilot-v1`
jobs do not run this review-only stage.

The existing component-review examples add no approach geometry. To opt into
estimated approach construction, run the additional jobs:

```sh
python -m voxel_mapper.world_pilot \
  --job examples/wicker-access-review-a-job.json \
  --output output/wicker-access-a

python -m voxel_mapper.world_pilot \
  --job examples/wicker-access-review-b-job.json \
  --output output/wicker-access-b
```

These retain the same pinned originals, source study, terrain and both placement
hypotheses. The explicit extra setting is:

```json
"access": {"policy": "estimated_half_step_approach_v1"}
```

Put it inside `review_component`. The additional per-opening policy is described
in the [connected doorway guide](connected-doorway-review.md). Unsupported
policies or additional acceptance flags are rejected. Approach blocks carry `accepted_physical_geometry: false` and a
separate `review/<component>/approach` feature ID. They add no accepted planning
components or training labels. A second review feature is not a second building.

The rule uses centred, cardinal movement in a one-block-wide corridor with no
more than a half-metre change between standing surfaces. It checks swept overhead
clearance at changes in height. Known full cubes and slabs may bear weight;
stairs, fences, trapdoors, liquids and unknown shapes conservatively obstruct
the corridor. This is a simplified player route, not complete Minecraft physics
or an accessible-design assessment.

The construction search covers at most 32 metres in each horizontal direction,
32 route columns and 60,000 explored states. It considers level or descending
routes from existing interior-connected openings to emitted `path`, `sidewalk`,
`queue` or `plaza` cells. Withheld elevated paths and roads do not become targets.
It prefers short routes with little fill and adds only full stone or bottom
stone slabs over emitted terrain. Fill depth is at most 16 blocks. It never
excavates terrain, covers mapped path cells or alters source building cells.
Absence of a bounded route is reported, not interpreted as proof that no route
could exist. Other orientations, higher approaches or different site access
designs require separate review.

Before packaging, the audit reopens the native LevelDB, reads collision geometry
and stored spawn metadata, and rechecks the proposed route, threshold, interior
connection, support and headroom. A proposed route or spawn that fails these
checks prevents publication of the world. `access-review.json` and the standalone
plan/profile diagram `access-review.svg` record the result. The same audit is
embedded in `park.mcworld`'s quality report before its checksum is calculated.

In the initial access exports (PR #25), both hypotheses needed two bottom stone
slabs for a seven-metre route from `osm/way/1182076342`. The narrow `door-NW` had
clear air at its declared column but no usable interior connection. Those
historical exports retain that unresolved result. The connected-doorway revision
changes the native cut, records its width approximation and offers a separate
exterior approach for every opening. The single-approach policy above still
builds only one approach and can leave other exterior connections unresolved.
The spawn remains on mapped paving at native coordinates `[11, 69, 3]`.

These are estimated access experiments using the unverified **184 m** review
floor. They establish neither a real-world entrance design nor measured floor
height. The three elevated paths remain withheld. See the retained validation
receipt in `docs/evidence/pilot-access/` for hashes and replay results.

## Review component contract

A review job adds `review_component` with:

* `policy: estimated_review_only`;
* pinned `model` and `placement` descriptors;
* `original_pdfs`, a list of pinned originals;
* `evidence`, a list of pinned direct study parents.

Paths are relative to the job. The initial renderer consumes the existing legacy
study mesh format (`wall_mesh`, `roof_mesh`, optional `projection_mesh`, wall
outline and opening segments). It uses the shared shop slab/decorative compiler;
it is not a general-purpose parser for arbitrary building meshes or PDFs.

Placement explicitly supplies an `id`, BNG anchor, BNG bearing, retained
orientation alternatives, floor elevation/datum and descriptive basis.
`estimated` must be true and `production_placement_eligible` false. Unsupported
frames, excessive extents, out-of-bounds geometry, an accepted-placement claim,
source changes and terrain conflicts fail without publishing a completed world.
Prepared internal state cannot be supplied through job JSON.

After independent source controls, floor and as-built identity are established,
the verified planning/park adapters must evaluate the component separately. A
successful review export or an operator's preferred picture cannot promote it.
