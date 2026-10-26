# Existing and proposed paving coverage

The initial hatch review recovered proposed paving, but omitted solid existing
paving and plazas. It also withheld valid PDF fills with self-touching or
retraced boundaries. A blanket requirement that a source fill fit to the left
of the legend column omitted two further paths extending across that column.

The updated reader preserves exact direct DeviceRGB, DeviceGray and DeviceCMYK
fill values and their graphics-state scope. Both solid and patterned paving
require a complete visible printed paving key, one unambiguous original swatch,
matching source appearance and opacity, and no conflicting key. Similar colours
are not merged. Ordinary surface/annotation guards remain unchanged.

A first bounded scan establishes visible keys. A second scan, sharing the parsed
original operations, resolves only unsupported fills belonging to unique paving
keys. It polygonizes original flattened edge walks and evaluates their even-odd
or nonzero winding rule. Retraced edges keep their multiplicity. No polygon
buffer repair, hull, endpoint snapping or invented bridge supplies an outline.
Original controls, paint indices, fill rules and source fill geometry remain
in the evidence. Curved display approximations retain the 0.05 PDF-point bound;
exact curved topology and physical accuracy are not asserted.

Same-colour text backplates are withheld using their source geometry and native
text extents, including rotated and L-shaped masks. This correspondence can
only withhold a role. It cannot infer paving or replace source boundaries with
text boxes. The Wicker replay withholds all 18 matching annotation backplates.

Paths crossing the legend column require an original opaque white backplate
covering the complete visible paving keys and their swatches. Only a later
source backplate painted before those swatches can authorize the separate
review occlusion. Source geometry is retained; `review_geometry` hides the
legend backplate in the overlay. This is rendering evidence, not a physical
terrain boundary or a complete later-paint visibility screen. Unrelated solid
fills are retained unclassified but do not obscure the review overlay.

## Wicker development replay

The updated source review retains **24 existing and 19 proposed paving fills**,
including five curved fills. Three large existing fills and one proposed fill
now follow their original compound PDF fill rules. Existing hatch geometries
are unchanged. The blue union covers about **5.25 times** the previous review
area. Source fills are not separate certified path features or a verified
walkable network.

The four compound fills are checked independently by rendering their isolated
original PDF primitives and comparing them with the recovered display polygons.
The review pack includes the original PDF, source controls, glyph proofs,
updated PNG/SVG and raster comparison receipt. The document was previously
inspected and is not an unseen accuracy benchmark. This replay checks the
paving stage; the unrelated real building/section pipeline is not rerun.

The same lower-only caps still apply to source paths, points, resources and
output. Both passes are charged to aggregate geometry/resource limits. Additional
limits bound total scan work to 1,000,000 operations, source fill arrangements
to 2,000,000 work units and text-mask comparisons to 64,000. A quota failure
clears the whole new review. Unrelated unsupported water, vegetation and other
fills cannot consume the paving-only arrangement pass.

Synthetic tests cover solid-only plans, holes, exact colours, graphics-state
restoration, compound winding/retracing, annotation backplates, cross-column
paths, source legend occlusion and quotas. The frozen Windows smoke checks both
paving states and an original retraced hole, while retaining the previous
layout/world counts.

**No new world geometry or training labels are produced.** Later visibility,
physical boundaries, levels, surveyed placement and world promotion still need
validation.
