# Area planning source expansion — 11 October 2026

The source selection now covers **12 of 15 areas**, up from five. This adds 19 area-to-application links covering 17 unique applications already present in the catalogue; it is not new application discovery. The registry preserves council URLs, description hashes and location markers.

The acquisition pass recovered **37 additional pinned PDFs**, reused 40 verified files and left 21 pins unavailable after a focused Katanga retry.

## New area coverage

| Area | Linked applications | Candidate document records | Verified PDFs | Extracted pages |
|---|---:|---:|---:|---:|
| Forbidden Valley | 6 | 22 | 15 | 17 |
| X Sector | 1 | 3 | 1 | 1 |
| Dark Forest | 1 | 5 | 4 | 11 |
| Gardens | 5 | 80 | 50 | 116 |
| Towers ruins | 4 | 70 | 43 | 121 |
| CBeebies Land | 1 | 10 | 2 | 2 |
| Katanga Canyon | 1 | 2 | 2 | 8 |

Shared applications and identical PDF blobs appear in multiple areas. Table rows must not be summed as unique resort-wide PDF/page totals. Drawings are candidate sources; no individual geometry is accepted from an application match alone.

## Remaining work

Adventure Land, Gloomy Wood and Towers Street still need verified application associations. Targeted council-site indexed searches for Spinball, Haunted and Towers Street returned no usable matches; this does not establish absence from the council archive. The registry records additional search aliases and pending companion references.

All 15 areas were exercised. Twelve await reconstruction setup; three await applications. No area execution or native extraction errors occurred. **No new native world cycles were generated**, and the V25 package hash remains unchanged. Source-bound recipes, accepted boundaries, sheet registration/current-state review and physical component inventories still gate generation.

## Validation

839 regression tests passed. Four final association tests passed after the URL/empty-marker checks were tightened. They verify idempotent scoped selection, rejection of stale descriptions and incorrect official pages, and the real seven-area registry. Repeat extraction preserves candidate hashes for unchanged source areas.

The detailed receipts are `evidence/alton-area-association-audit.json` and `evidence/alton-associated-area-cycle-test.json`. Reproduction and source-binding command usage are in `docs/resort-area-reconstruction.md`.
