# Automatic wall and roof projection profiles

The new downstream pass replaces the NW main façade's rectangular display proxy
with lossless source-cell wall and roof projection meshes. It consumes the
[automatic façade preview](automatic-facade-preview.md), checks its full replay,
and uses the original elevation raster. No manual outline, wing seed, crop box,
roof dimensions or local placement is supplied to extraction. Existing component
extraction and the prior preview remain unchanged.

```sh
python -m scripts.build_automatic_facade_profile \
  --preview PREVIEW_PACK --components COMPONENT_PACK --views VIEW_PACK \
  --corpus CORPUS --output output/facade-profiles
python -m scripts.audit_automatic_facade_profile \
  --profile PROFILE_PACK --preview PREVIEW_PACK --components COMPONENT_PACK \
  --views VIEW_PACK --corpus CORPUS --output output/facade-profile-audit.json
python -m scripts.render_automatic_facade_profile \
  --profile PROFILE_PACK --preview PREVIEW_PACK --components COMPONENT_PACK \
  --views VIEW_PACK --output output/facade-profile.html
```

Restore the same three checksum-verified originals and follow the extraction and
preview commands in the preceding guide first. `PROFILE_PACK` is the hash-named
directory reported by the build command. It contains `facade-profile.json` and
four binary PNG masks, two per threshold. The HTML embeds the untouched source
image, exact polygon overlays and an orbitable planar mesh. It retains all
30 previous witness links and seven distinct opening outlines. There is no
physical component acceptance, aperture carving, world export or training label.

## Source topology and the supported projection

At each unchanged threshold, 220 and 235, the pass labels the original white
pixels with four-connectivity. Regions touching any image border are outside.
The remaining closed white regions, together with original dark pixels, define
source topology. No outside white pixel is added to a roof mask, and no source
image is edited.

The automatically retained parent rectangle supplies the main wall span and a
candidate upper wall edge. Above it, a broad upper projection must have at least
24 pixels of height, at least 95% full-width rows and one unique most frequent
original horizontal span supported by at least half those rows. That span must
stay inside the source image and be between one and 1.5 parent widths. These are
source-pattern constraints, not fitted physical dimensions. A blank, open,
fragmented or gabled projection failing this recipe stays withheld. General
pitched/gabled silhouette interpretation is not implemented by this pass.

Whole closed original white regions that intersect the supported upper band,
end at or above the parent top and fit entirely inside the repeated upper span
supply the roof projection. One layer of adjoining **original dark cells** is
also retained. This retains small raster steps and gaps at the boundary; it does
not extend or smooth a line. A whole region crossing the span is deferred rather
than clipped into a roof. The neighbouring gable and callout-enclosed regions
outside the main projection are not joined to it.

For each original parent column, a separate scan walks upward from the raw lower
parent edge through a contiguous midtone run in grayscale range 128–224. A run
needs at least 16 rows to support a source shaded-band interface. The wall mask
keeps original dark/enclosed source cells between the parent top and that
interface. Every column result is retained. Unsupported columns stay empty;
there is no interpolation or extrapolated horizontal base. This interface is
drawn ground shading, not verified exterior-wall contact or a finished floor.

## Wicker source result

Both original threshold variants recover the main NW projection. The old raw
jamb lower endpoint remains about 0.984 nominal m below Shop Level; this pass does
not use it as a doorstep or wall base. The source ground interface now follows
its observed uneven contour, from original rows 588 to 595. All 536 columns have
source support in both variants. The earlier doorway base envelope remains a
separate source measurement near Shop Level.

| Source measurement | Result |
| --- | ---: |
| Main roof projection source span | x=335–907 pixels |
| Main roof source vertical envelope | y=342–478 pixels |
| Main wall source span | x=353–889 pixels |
| Main wall top | y=477 pixels |
| Main wall lower envelope | y=588–595 pixels |
| Roof projection width | 16.892943 nominal m |
| Roof projection top above printed Shop Level | 7.256110 nominal m |
| Main wall span | 15.829751 nominal m |
| Main wall top above printed Shop Level | 3.269140 nominal m |
| Roof variant overlap | 99.536505% |
| Roof cells differing between variants | 359 |
| Wall cells differing between variants | 0 |

These are drawing measurements at the original nominal scale. They are not
verified physical widths, elevations or pitch. The roof's lower boundary and
wall's upper boundary overlap by their original source cells; the overlap is
reported and stays unrepaired. Both meshes lie on `y=0` in the elevation frame.
There is no inferred roof depth, pitched 3D roof plane or wall thickness.

At threshold 220 the roof retains 77,455 cells and five enclosed mask gaps; at
235 it retains 77,096 cells and nineteen gaps. The wall retains 60,818 cells in
both variants. Raster gaps, antialiasing and callout overlaps are retained as
uncertainty, never promoted to real roof openings. The roof projected areas are
67.556637 and 67.243516 nominal m²; the wall projection is 53.045763 nominal m².
They are projected source areas, not roof surface or floor areas.

## Exact mesh and review

Each selected raster row is decomposed into half-open runs. Identical intervals
on consecutive rows coalesce into rectangles, without bridging a hole or moving
an endpoint. Each rectangle has four source-grid vertices and two triangles.
The two variants contain 507 rectangles and **1,014 triangles** in total. Mask
polygonization retains every original grid step and hole without simplification.
The mesh area equals the selected-cell area exactly, up to floating arithmetic.
No material is assigned from the display colours.

The interactive review switches between both thresholds and all seven original
opening outlines. Independent roof/wall/overlay toggles compare against the
untouched source, and a previous-rectangle toggle exposes the change. The raw
jamb extent remains separate from two source-outline hypotheses at the ends of
the measured base envelope. Neither is selected as a physical threshold. No
aperture is cut from either surface.

The drawing's printed state remains `unspecified`. Adjacent gable/wing identity,
other façade profiles, source wall/roof/aperture/ground roles, physical scale,
roof depth/pitch, wall thickness and geographic/vertical registration remain
unresolved. The semantic ranker remains untrained. The same three verified
originals are used; this change claims no new portal acquisition or gameplay.

## Bounds and independent audit

The build first reproduces the complete preceding preview and verifies every
original detail crop. It binds original component/view reports, raster bytes,
source PDF checksums and the complete source review chain before and after work.
Its contract pins implementation/dependency hashes and relevant library versions.
At most eight source profile groups, six million pixels per raster, 8,192 white
regions, 8,192 coalesced rectangles per surface, 256 polygons per surface,
100,000 work checks and 64 MB total output are allowed. A budget hold discards
all partial profiles, geometry and masks. Deterministic reuse rejects altered
saved JSON or masks.

The independent audit reproduces the saved profile, uses an outside flood fill
instead of the kernel's border-label method, checks every closed roof region,
recomputes every shaded column run and derives original dark-cell adjacency
without the kernel's dilation call. It reconstructs each exact mask from disjoint
mesh rectangles, checks every vertex/triangle and projected area, and separately
rasterizes all polygon rings to verify holes. Original opening witness links and
both threshold comparisons are checked as well.

Eleven new regressions cover source topology, missing/shaded columns, unsupported
open/gabled/callout patterns, holes and disconnected cells, exact mesh area,
threshold separation, region/rectangle limits, original-PDF replay, source
mutation, deterministic reuse, independent audit and early/late budget discard.

The final local suite passes **1,674 tests**, including eleven new
regressions. All fourteen upstream artifacts and the original source preview
reproduce. The profile audit independently checks 463 roof regions, 1,072 ground
columns, four masks, 507 rectangles and 1,014 triangles. Browser verification
covers 28 threshold/choice/angle states, six display toggles and the original
image hash with exact coordinates and zero JavaScript errors. Receipts are in
`docs/evidence/facade-profile/`.

The downstream [pitched-roof review](automatic-gable-roof.md) now derives a
conditional main roof from original plan-line spacing and these source panel
heights, then checks separate end-elevation slopes without refitting. These
original profile masks, gaps and all opening witness links remain unchanged.
