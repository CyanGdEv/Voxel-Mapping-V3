# Gardens paths, slopes and coloured barriers

V16 adds a reviewed garden overlay to V15, preserving its foliage, water beds
and ride clearance. It does not regenerate terrain or ride layouts. The SMD/2013/1105
Upper Gardens, Lower Gardens, White Bridge and Bridge/Dam sheets supply fence
routes and surveyed physical outlines. Source PDFs are verified by SHA-256.

Eleven path centre traces follow visually reviewed grey boundaries. Their
widths (1.8–2.5 m) and unspecified paving finish are estimates, not closed
surveyed paving polygons. Six narrow wall faces are retained closed survey
polygons; masonry and exposed height are proxies, with height estimated from
nearby terrain relief and capped at 3 m. Pond fill, tree removal and planting
proposals are excluded. Landmark vertical geometry is a separate unfinished task.

Absolute registration remains provisional. Relative sheet alignment uses shared
station and unique spot-height labels, with robust consensus and leave-one-out
checks. Its absolute position inherits the earlier Wicker survey alignment
hypothesis. Do not describe this as independently verified georeferencing.

`reconstruction.garden_surfaces` is independent of park names and export. It
quantizes walking heights to half metres. Gentle slopes use bottom/top stone
slabs; grades of 1:2 or steeper use uphill-facing stairs. Explicitly traced
stair flights can request stairs at lower grades. North-facing stairs correspond
to increasing local northing and decreasing Minecraft Z. A five-metre symmetric
profile smooths metre-scale DTM noise. Edits requiring more than 1.5 m terrain
change are withheld. Each accepted surface receives a solid foundation.

Barriers default to iron bars. Specified green / RAL6008 uses green stained glass
panes, the user's approved colour proxy. The fencing detail sheet 373/82/10D
specifies dark green steel and generally 1100 mm height. One-metre blocks
approximate this with one thin pane cell (1 m rather than 1.1 m). Bedrock derives connections from
neighbours. Source drawing segment gaps are retained; the input includes both
retained and proposed 2013 fencing. Actual gate profiles and exact steel sections
are not claimed. Barrier cells through a generated walking corridor are withheld.

Native collision checks protect supplied foliage, ride solids, rider air cells,
water columns and tree roots. Withheld columns remain visible in the evidence
report; some traced corridors are incomplete rather than damaging retained
features. The export verifies every cell of every touched native chunk section,
including unchanged cells and air, and unchanged overall chunk coverage.

```sh
python -m voxel_mapper.gardens \
  --source park-foliage-v15 --output park-gardens-v16 \
  --planning-files recovery/v4/files \
  --datum-grid recovery/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --protect park-foliage-v15/foliage-overlay.jsonl \
  --protect recovery/Alton_Towers_Wicker_Trestles_V9_Evidence/completion-overlay.jsonl \
  --protect recovery/Alton_Towers_Wicker_Trestles_V9_Evidence/rider-envelope.json \
  --protect park-water-v11/water-columns.json
```

`--features` accepts another reviewed bundle with source hashes, registration
candidates and native path/wall/barrier geometries. The bundled
`data/alton-gardens-v16.json` records geometry methods and material uncertainty
per feature. `scripts/extract_reviewed_gardens.py` reproduces its extraction when
run from the evidence workspace containing the retained PDFs and registered face
inventory. Colour-route extraction excludes the drawing legend/title area; native
curves are adaptively flattened. No broad garden/lawn polygon is paved by guess.

Outputs: native world, importable `.mcworld`, composed JSONL overlay, feature
provenance, withheld reasons and visit coordinates. The V16 release separately
checks all emitted cells, grounded rail bases, foliage preservation, original
water/bed cells, Wicker solids and protected rider clearance.
