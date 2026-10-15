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
entrance access, source-to-building identity, floor datum and independent
controls/checkpoints remain outstanding.

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
