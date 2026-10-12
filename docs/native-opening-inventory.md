# Native opening inventory

`native_opening_inventory` discovers native window, door and archway labels in
the elevation scope supplied by an existing checksum-pinned local-wing seed.
It checks original-font raster support and keeps original text/character indices.
View discovery remains manual. The existing reviewed model is never rewritten.

Exact solid axis-aligned source segments can form rectangular cycle candidates.
Continuous collinear source intervals may jointly support a side, with original
component, ring, segment, endpoint and interval-fraction proofs retained. There
is no snapping, gap bridging, curve closure, endpoint extension or fitted hull.
All nearby and nested alternatives remain. Dashed, curved or truncated source
paint components are excluded from this rectangle method. Geometry rejected by
the upstream extractor remains unavailable, rather than being repaired here.

Source cycles can be panes, frames or drafting objects. Even one nearby cycle
does not establish a complete aperture. Layout margins are search rules, not
verified annotation attachment or physical uncertainty. No cycle is promoted
to a wall hole, accepted object or world geometry. Duplicate/hidden labels,
missing cycles and competing candidates have explicit statuses. Bounded frame
exhaustion removes all frames; association exhaustion removes all assignments.
Visible label discovery and the separately bounded seed-label check remain
available if frame discovery is withheld.

Area runs with `local_wing_review_seeds` automatically retain a parallel
`native_opening_inventories` result, exposed by sweeps. Inputs must come from
the acquired area corpus. Missing PDFs are reported without external fallback.
Original PDF checksums, raster hashes, captions, source states, recipe bytes and
output bytes are verified. Unchanged reruns validate and reuse identical audit
bytes; stale output requires a fresh output directory. This stage does not mark
required reconstruction families complete or establish geographic registration.

```sh
python scripts/audit_native_opening_inventory.py \
  --recipe evidence/mutiny-north-wing-review-seed.json \
  --sources /path/to/original-pdfs --output /path/to/fresh-inventory

python scripts/render_native_opening_inventory.py \
  --inventory /path/to/fresh-inventory/native-opening-inventory.json \
  --recipe evidence/mutiny-north-wing-review-seed.json \
  --source /path/to/original-elevation.pdf --output /path/to/audit.png
```

## Mutiny north-range result

The original existing CTD elevation yields 17 visible labels: three doors,
13 windows and one archway. Its reviewed scope contains 112 exact source
rectangle cycles. Four labels have one nearby frame candidate, seven have
competing candidates and six have no supported complete source rectangle.
None is a verified physical aperture. The audit uses 188,863 bounded frame
checks, below the one-million default ceiling.

The seed-label check flags `w3.06-a` as a disagreement with native `w.3.05`;
`w3.06-b` matches native `w.3.06` by layout. Native `w.3.13` has no matching
seed trace and is drawn beside a “window boarded over” note. That note is
visible context, not authorization to carve another hole. The original seed,
partial 3D model and isolated review world retain their previous identities.

The real three-source area replay reuses the exact inventory hash and runs
zero new extraction pages on its second pass. The area remains awaiting
reconstruction, with zero new park geometry. Compact evidence is retained in
`evidence/mutiny-north-native-opening-inventory-audit.json` and the corresponding
area replay audit. The full generated audit contains original source component
and four-side interval proofs and can be reproduced using the CLI above.

Next geometry work must establish complete aperture boundaries for skew,
fragmented and curved linework, distinguish panes from physical openings,
and review the boarded opening before changing the mesh. Outer/end walls,
roof junctions, materials, physical identity and park registration remain
separate unresolved work.
