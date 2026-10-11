# North-range core-shell hypothesis study

The courtyard-only preview is open at its rear, ends and floor. The user requested a complete structure preview after in-game arch repair. This opt-in study closes the selected north-range core for review while retaining the source-pinned front, roof dimensions and native arch support correction. It does not reconstruct the full four-range Ingestre complex or certify unmeasured faces.

The retained AL05 ground-floor view gives the frontage/depth traces; AL06 gives the courtyard silhouette and 16 front aperture traces. Both selected end cross-sections join neighbouring ranges, as recorded in the earlier outline review. The retained Smytheman elevation sheets also show annexes and changing profiles; they are not silently reduced to a matching blank rear facade. Thus the new rear and end closures are explicitly hypothetical. Their purpose is to provide a usable core-shell preview while rear apertures, adjoining-wing correspondence and roof junctions are resolved.

`evidence/mutiny-north-wing-shell-study-seed.json` pins the exact parent model SHA-256 and acknowledges these closure assumptions. Wall thickness is 0.5 m, floor thickness 0.25 m and roof thickness 0.25 m vertically. These are bounded display choices rather than source measurements. No glass is generated. Only the front arch is provisionally projected through to the rear; front windows and doors are not mirrored onto the rear. The rear aperture inventory remains unresolved.

Six exact solids are exported: inward-thickened courtyard wall, rear wall, two joining-plane caps, roof shell and floor. Polygon triangulation preserves holes and doorway notches. Every component must have paired opposite directed edges and its signed volume must agree with profile area times extrusion thickness. These individual components are watertight; intersections/overlaps have not been boolean-unioned into one manifold. No claim of whole-assembly watertightness is made.

The native exporter first retains all 296 previous front/roof cells unchanged. It adds 120 rear-wall cells, 22 cells for each joining-plane closure and 192 floor cells: 652 review cells in total. End closures fill beneath the actual native roof columns. Rear clearance and all intervening depth columns retain two standing air blocks across the arch. Floor cells sit below drawn floor zero, and replace the artificial grass under the footprint. Cold native readback verifies all 5,860 composed blocks and unwritten air in eight chunks. Per-cell part and hypothesis provenance is retained in the shell audit.

The exact shell uses the 32.06749 m elevation frontage and 5.84043 m reviewed plan depth. The native footprint is 32 by 6 blocks; this is quantization rather than sheet stretching. The unchanged three-source parent model is included beside the shell output. `surveyed_complete_structure`, `full_complex_reconstructed` and `world_placement_eligible` remain false. Park additions are zero.

```bash
python scripts/build_wing_shell_study.py \
  --recipe evidence/mutiny-north-wing-window-cycle-review-seed.json \
  --closure-seed evidence/mutiny-north-wing-shell-study-seed.json \
  --sources /path/to/checksum-named-pdfs \
  --output /path/to/fresh-core-shell
python scripts/render_wing_shell_study.py \
  --model /path/to/fresh-core-shell/shell-model.json \
  --output /path/to/core-shell.png
```

The exact-mesh render shows the courtyard silhouette in blue and hypothetical rear/junction closures in amber. The Bedrock export uses the existing generic stone and dark-oak palette. Its appearance needs an in-game check. Room partitions, upper floors and stairs, annexes, neighbouring ranges, measured rear openings and physical construction details remain required for a complete surveyed structure. Geographic registration and datum are still required before park integration.
