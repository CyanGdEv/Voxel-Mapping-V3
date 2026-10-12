# Mutiny Bay, Wicker Man and Katanga Canyon: area trial

Run date: 12 October 2026. This completed an offline trial using the original PDFs retained in the current workspace. It did not build three complete areas.

| Area | Catalogue records | Verified original PDFs | Pages processed | Geometry candidates | Native area cycles |
|---|---:|---:|---:|---:|---:|
| Mutiny Bay | 139 | 73 | 213 | 26,257 | 0 |
| Wicker Man | 40 | 0 | 0 | 0 | 0 |
| Katanga Canyon | 2 | 0 | 0 | 0 | 0 |

Catalogue records and PDF counts differ because several links can reference the same document. Catalogue coverage is not an exhaustive area inventory. Wicker Man and Katanga PDFs were missing from this retained-input set; this does not establish that they cannot be acquired from the planning portal.

## What worked

All three areas reached a readiness report. Mutiny produced 677 unbound component mentions, 108 wall-band candidates, 34 elevation material regions and 31 caption-layout candidates. These remain hypotheses. Its 426 evidence tasks consist of 213 view-scope tasks and 213 horizontal-registration tasks. Of its 213 pages, 195 require complete extraction and a visible scale before architectural interpretation; three require boundary recovery. These pages remain recorded rather than silently becoming accepted geometry.

The trial exposed an empty-vector-page crash. Architectural interpretation v16 skips graph-scoped reviews on pages without vector parents, retaining diagnostics and allowing later pages to run. A blank/text-only/vector-page regression test passes. An unchanged-input resume was verified byte-for-byte across the completed trial artifacts; it produced no additional pages or native cycles.

## Existing building previews included

The archive includes the previously reconstructed Mutiny courtyard and Wicker shop previews. Both were checked again against the current shared compiler and their retained world checksums. They pass native occupancy checks, preserve protected openings, contain no glass or stairs, and respect full-block walls/ground with slabs for roofs and eligible details below 0.75m. Mutiny has 7,292 surface cells, 22,372 composed blocks and 16 chunks; Wicker has 646 surface cells, 2,716 composed blocks and four chunks. Composed blocks include the display-world context. These are isolated, provisional local-coordinate studies, not newly generated full areas. There is no Katanga model yet.

## Required before a combined area world

1. Acquire and checksum the missing Wicker and Katanga original drawings, plus the pending Mutiny links. Expand Katanga's application coverage: the current selection covers only the restaurant seating/walkway application SMD/2009/0125. The kiosk application SMD/2007/0009 is an unbound lead, not accepted geometry.
2. Bind accepted boundaries and terrain to a common coordinate system. Register source views and retain uncertainty for dimensions, levels and existing/proposed state.
3. Build a source-bound physical component inventory for buildings, rooms, paths, ride infrastructure, fences and vegetation. Resolve the evidence queue rather than treating every drawing primitive as a building.
4. Compile reviewed components into reconstruction recipes, validate coverage and export geographically registered cumulative native cycles. The controller currently has no accepted boundary, recipe or complete bound inventory for any of the three areas.
5. Collect reviewed feedback and evaluate held-out buildings before promoting a learned ranking model. This trial creates no accepted training labels or model promotion.

## Replay

Unzip the bundle. With this repository and its dependencies installed, run `python -m voxel_mapper.area_cycles local --job /absolute/path/to/bundle/job.json --max-cycles 3`, followed by `python scripts/audit_area_trial.py --job /absolute/path/to/bundle/job.json --output /absolute/path/to/replayed-audit.json --check-resume`. The portable job uses included source PDFs and catalogues and creates a fresh work directory. Original trial reports are included for comparison. New job hashes and absolute paths will differ; compare semantic counts and pinned source/output hashes.
