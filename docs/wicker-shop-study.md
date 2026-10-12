# Wicker shop isolated surface review

This deliverable provides two importable Bedrock worlds built from the retained
proposed shop model: one block per source metre (1:1), and four blocks per source
metre (4:1 detail study). Both use an artificial flat platform and STUDY_ZERO.
Neither assigns park position, geographic rotation or ODN floor level.

The source pipeline recomputes the original PDF/render/annotation checks, floor
trace and sheet-layout normalization, endcaps, elevation opening candidates and
wall model before export. The wall model must match pinned SHA256
`5d791eb4dd6665fce7d889d6a32f5f65672cf8db82628d307cde864f89e9ab22`.
The study contains seven solid wall-base segments, three opening/lintel regions,
two gables and the main roof, using the earlier manually traced proposed model.
It does not silently substitute the 1.011 m recovered northwest cap span for the
retained 0.901 m normalized manual opening. Wall-face identity, reveal roles,
roof/wall centring and 180-degree source correspondence remain unresolved.

Surface rasterization projects each triangle along its dominant normal and
samples its plane at projected voxel centres. It emits a one-block display
surface, not an inferred physical thickness. Walls use spruce planks and the
roof dark oak planks solely as illustrative block palettes. Roof/wall cell
aliasing uses roof display priority with every shared cell counted. Degenerate,
nonfinite, oversized and altered models are refused. Shared triangle edges and
opening air are tested. The source model remains unchanged.

The 1:1 model contains 372 surface cells; two small wall triangles have no cell
centre sample. The 4:1 model contains 6,663 surface cells and every triangle has
samples. The 1:1 preview shows visible wall/roof quantization gaps; the thin source
surfaces and unmeasured construction thickness are not filled to hide those
gaps. This is a surface study, not a watertight shell or accepted reconstruction.
Canopy, fascia, detailed cladding/bunding, frames, interiors and physical wall
thickness are omitted. All three opening centre columns remain air below their
sampled heads in both studies; this does not certify full-width clearance or
player movement.

The exporter reopens every written block and checks all unwritten air cells and
chunk coverage before packaging each world. The preview depicts the actual
planned block cells, not an in-game screenshot. The native validation receipt is
`evidence/wicker-shop-study-validation.json`.

```sh
python scripts/build_wicker_shop_study.py --preview \
  --pdf-directory /path/to/checksum-named-pdfs \
  --output /path/to/new-study-directory
```

The optional preview needs Matplotlib. The output ZIP includes the two `.mcworld`
files, README, source review, quality reports and preview. Tests cover dominant
projection and winding, triangle seams, doorway air, model tampering/scale guards,
repeatable voxel planning and cold-reopened native export.

Next: inspect both worlds in Minecraft, resolve the northwest leaf/frame/reveal
roles, confirm wall-face and roof-centre/orientation correspondence, add any
source-supported thickness/canopy details, then obtain independent geographic
placement and floor-datum checks before composing into a park world.
