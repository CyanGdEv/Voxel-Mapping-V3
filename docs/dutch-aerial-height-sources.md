# Dutch aerial imagery and height source pilot

PDOK annual high-resolution RGB and colour-infrared imagery, plus native AHN4
height rasters, are now usable as source-pinned acquisition/training inputs.
Two actual fixed CPU fits compare finer RGB against a controlled coarsened
version, keeping labels, physical extent, UK inputs and height arrays identical.
The finer version improves three ground classes on the reserved Toverland crop,
but structure recognition and precise boundaries remain weak. Production model
weights and world geometry remain unchanged.

## Acquired inputs

- Efteling: Fata Morgana courtyard/lakeside, training only.
- Toverland: Merlin’s Quest/Avalon, prospectively reserved from all fitting.
- Each crop is1024×1024 on an exact RD New (EPSG:28992) grid at8cm sampling,
  covering81.92×81.92m. These are small park crops, not complete park surveys.
- RGB layer: fixed `2025_orthoHR`; CIR layer: fixed `2025_orthoHRIR`. No moving
  Actueel or quick-ortho aliases. Original JPEG responses are retained; the
  service advertises JPEG only. An initial PNG-signature assumption was rejected
  before acceptance and corrected to the advertised format.
- Publisher nominal imagery detail is5/8cm for2025, depending on region. These
  exports sample at8cm. Exact local flight days, per-pixel optical detail and
  independent surveyed registration have not been verified. No sharpening or
  synthetic super-resolution is applied.
- AHN WCS identifies version4, collected2020–2022, with native50cm float-valued
  terrain and surface rasters. Both products have identical source grids; heights
  are metres relative to NAP. The exact local LiDAR day is unverified. The DSM
  uses the AHN4 squared-IDW surface definition excluding classified water; it is
  not an EA last-return raster. CIR is retained for review, not fed to the model
  or represented as calibrated NIR reflectance.

AHN4 and2025 aerial epochs differ. Valid height neighbourhoods cover31.44% of
Efteling and40.52% of Toverland, including the required roughness support.
Missing cells stay missing; water gaps are not flat-ground evidence. No raw
point clouds were downloaded for this pilot.

The adapter requests native floating-point height, never coloured WMS pixels.
It samples the half-metre grid at exact RGB pixel centres in RD coordinates.
The Mercator extent in receipts is only an indexing envelope, not the alignment
transform. Relative height (DSM−DTM), terrain slope, local roughness and validity
supply four context fields. No NAP absolute heights are combined with UK ODN
heights. Half-metre roughness uses a centred7×7 native-cell (3.5m) window; the
existing one-metre3×3 processing remains numerically unchanged. These are
raster-derived features, not8cm height measurements or surveyed object edges.

## Source labels and class coverage

The prior six-image dense dataset is unchanged:36 image/receipt/mask assets
remain byte-identical. Efteling contributes213,111 paving,72,819 structure and
74,236 water pixels. No clear lawn patch is present, so grass remains unlabelled
there. A source-specific declared class scope permits this without weakening
the default four-class requirement for other sources. Training still has positive
support for all four ground classes across its seven images and five parks.

The reserved Toverland crop has58,735 paving,14,423 structure,36,921 grass and
81,547 water pixels:191,626 known ground pixels out of1,048,576. Most pixels
remain unknown. Planting beds, supports, uncertain banks, track crossings and
occlusion are excluded. Complete leaf-off crown extents are not invented; there
are no new positive-canopy labels, so this pilot does not test tree-canopy
precision. Ground and canopy heads remain separate.

All new regions are assistant source-assisted drafts traced before candidate
predictions, not independent human truth. Sparse/partial boundaries and a
single selected crop limit the score interpretation. Rebuilt native and
coarse datasets match exactly; all four Dutch height-array replays are exact.

## Frozen controlled comparison

The protocol SHA256 is `98f7b3c96c2fb93252dd72f3c9a6f02eea21aa2e82998e24d6b2c7e60f70d8bf`.
It was written before high-resolution crop acquisition or fitted predictions.
Source-only crop selection, annotations and datasets were sealed before fitting;
both model identities were sealed before reserved scoring. All Toverland
records are rejected by fitting/save guards and absent from training source
lists. Cross-park footprints pass the24m geographic context guard. Flamingo
Land remains excluded entirely. Toverland is now a consumed benchmark.

`native_rgb` uses the8cm-sampled Dutch RGB. `coarse_rgb` area-averages those same
photos to328×328 (approximately25cm spacing), then returns them bilinearly to
the unchanged1024 grid. This deliberately removes RGB detail while holding
physical context and target pixels fixed; it does not create extra optical
information. UK feature arrays and all height arrays are exactly identical.
Both use the same400-step seed137 schedule,batch4,96-pixel patches, learning
rate0.002,balanced loss and15% LiDAR dropout. The18,482-parameter20-channel heads
share the unchanged frozen aerial encoder. There is no boundary oversampling,
hyperparameter search or tuning against reserved scores.

| RGB input | Paving IoU | Structure IoU | Grass IoU | Water IoU | Macro IoU | Paving boundary F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native_rgb | 67.14% | 33.39% | 60.34% | 85.24% | 61.53% | 1.70% |
| coarse_rgb | 47.44% | 39.33% | 27.93% | 67.05% | 45.44% | 1.97% |

These are known-pixel scores on provisional Toverland labels, not whole-scene,
whole-park or independently surveyed accuracy. The finer RGB improves paving,
grass and water in this one comparison; structure IoU falls39.33%→33.39%.
Paving boundary F1 is only1.70% versus1.97% at a two-pixel tolerance on 222
supported target pixels. No improvement in precise boundaries is demonstrated.
Fitted Efteling previews are explicitly not validation. Positive canopy accuracy
is unsupported by this label set.

Both safe checkpoints changed from initialization; all four saved predictions
match safe reloads exactly. The successful serial run took
107.5s, peak process RSS1115.4MiB,
two CPU threads,no GPU. An earlier invocation stopped before fitting and
produced no checkpoints or scores; it is retained separately. The retry loads
one dataset at a time. Reported resources cover only the successful invocation,
not acquisition, feature extraction or the stopped process.

## Validation and reuse

41 relevant tests pass:6 Dutch source/grid tests,5 controlled-comparison tests,
and30 existing layered/LiDAR/reservation/dense-label tests. They cover fixed
layer/generation checks, byte and pixel budgets, native half-metre slope/gap
handling, rejection of changed sources/labels/splits, scoped missing classes,
coarsening invariance, default fitting, safe checkpoints and review pins.

The browser decoded all16 source/layer images and exercised48 park/layer/zoom
combinations. Both canvases retained1024-square pixel frames, all scope/metric
captions were present, and the narrow-screen layout passed without runtime
errors or external requests.

The self-contained review uses the original RGB/CIR bytes and lossless masks,
with two park frames, eight selectable layers and three zoom choices. All
layers and masks remain in the exact same RD pixel frame. Zooming enlarges
pixels without inventing detail. Display-only height colours distinguish
missing observations; raw float GeoTIFFs are in the bundle.

To acquire another supported Dutch crop, use:

```sh
python -m voxel_mapper.dutch_surface_sources --longitude 5.04512 --latitude 51.647 --spacing 0.08 --year 2025 --output new-dutch-crop
```

The command pins annual capabilities, bounds the area/bytes, preserves raw
responses and creates height features. It fails if the AHN service generation
changes, rather than silently accepting a different product. These native RD
inputs are handled by this grid-aware review/training path; the earlier GB
layer viewer’s Mercator/BNG assumptions are not used for their pixel alignment.

The download includes both pinned datasets, raw new RGB/CIR/height files,
capabilities/rights evidence, labels, protocol/seals, both checkpoints, scores,
reproduction results and the source patch. `prepare_all_features.py` regenerates
source-only caches using the included Dutch height pairs, the earlier
Multi-Park-Native-LiDAR.zip for UK pairs and Aerial-Encoder-Research.zip for the
unchanged encoder. The built datasets retain their exact IDs. Rebuilding the
native additions requires the previous parent dataset and original recipe
paths; relocating a fresh additions request changes its recipe identity.
The source patch needs the repository and optional research dependencies.
No Windows EXE, deployment or world geometry is changed.

RGB/CIR: © Beeldmateriaal / Het Waterschapshuis / participating Dutch public
authorities,CC BY4.0 (publisher link retained). AHN WCS capabilities stateCC0
for these height products. UK source attributions remain in original receipts.
Frozen FLAIR encoder and derived heads retain upstream NVIDIA non-commercial
research/evaluation scope; data licences do not expand pretrained model rights.
