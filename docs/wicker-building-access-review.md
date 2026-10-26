# Wicker architectural access and wall-role review

The three remaining conditional floor/path differences are station edge samples, not three entrances. The proposed architectural drawing places its nearest traced stair flight 2.63–3.47 m from these samples. This review maps the source details and preserves the unresolved connections instead of placing stairs at arbitrary perimeter cells.

## Source geometry

The checksum-pinned revised overall floor plan 2967-21 P1 supplies two manually sampled station-side stair outlines and three visible door openings: the station/preshow double doorway and the adjacent station/maintenance service doors. Three existing reviewed shop openings are also carried forward. These are eight proposed access features, not eight verified physical entrances. Exact thresholds, stair levels, riser counts and landing connections remain unset. The floor sheet explicitly says the internal layout is illustrative.

Both original architectural PDFs are checked against their hashes and complete 1888-pixel-wide rendered RGB sample hashes. Page rotation is accounted for before converting sampled pixels to native coordinates. The existing checksum-pinned sheet-furniture normalization corrects floor-sheet content reduction; this is a provisional document correction, not a physical stretch to match OSM. Manual stair/door endpoints have ±2-pixel sampling bounds, which do not establish physical accuracy.

The architectural roof shop is aligned to the current landscape shop by fixed-scale rotation and translation. Both half-turn candidates remain in the receipt. Station and maintenance centroids distinguish the drawing layout without refitting: the selected correspondence differs by 0.037 m and 0.048 m respectively; the alternate places them more than 55 m away. This is strong agreement between drawings, not independent survey accuracy. The existing OSM/terrain transform is retained.

## Roof envelopes versus walls

| Building | Current plate source outline, m² | Proposed architectural outer-wall trace, m² | Existing floor sample cells outside wall trace |
| --- | ---: | ---: | ---: |
| Shop | 215.88 | 187.04 | 42 |
| Station | 167.54 | 152.47 | 26 |
| Maintenance | 296.86 | 271.26 | 41 |

The landscape outlines agree with architectural roof envelopes at approximately 99.61%, 98.62% and 99.16% IoU respectively. A roof outline must not silently become an exterior wall footprint. Differences remain separate source roles; no existing plate is trimmed and no headroom, access or foundation is certified by this review. Cell counts are per building and are not additive unique area measurements.

## Reproduction

```sh
python -m voxel_mapper.planning_building_access \
  --config alignment-request.json \
  --preview-directory floor-preview \
  --pdf-directory original-pdfs \
  --evidence-directory evidence \
  --output fresh-access-review
```

The config is the existing six-input geographic planning request. Supply the original 2967-21 and 2967-48 PDFs under their SHA256 filenames. The evidence directory contains the existing shop floor-scale review and local-floor trace. The desktop packaging workflow runs the new access tests; no new GUI action or standalone executable installation is added.

Outputs include an annotated source render, an aligned overview, a JSON evidence receipt and projected EPSG:27700 GeoJSON (not RFC7946 longitude/latitude). The original `.mcworld` is hashed before and after; no world geometry or training labels are added. The floor datum remains unverified, and no Minecraft client test has been performed.

Next implementation is an isolated wall-based floor/shell prototype using these separate source roles, followed by source-supported landing/threshold geometry and access/headroom checks. The three existing edge differences must be reassessed against wall-based footprints, rather than treated as confirmed entrance locations.
