# Original-drawing area reconstruction pilot

The planning pilot runs building-view discovery and ordinary surface-label
extraction together on checksum-pinned original PDFs. It creates a drawing
review pack and records source, extraction and reconstruction blockers without
hand-entered view rectangles or per-polygon recipes. It does not yet reconstruct
the buildings or register paths into a park world.

Run the Woodcutters facilities application pilot from source:

```sh
python -m voxel_mapper.planning_area_pilot \
  --config examples/desktop/alton-woodcutters-planning-pilot.json \
  --source-directory /path/to/planning-originals \
  --download-missing \
  --output fresh-woodcutters-planning-pilot
```

The source directory contains `<sha256>.pdf` files named in the manifest.
Without `--download-missing`, unavailable originals remain explicit source
blockers. Optional recovery uses the existing bounded council downloader:
recorded official attachments only, no redirects, checksum checks, byte/time
limits and cancellation. The example records the same-attachment legacy HTTP
transport observed during acquisition; failed HTTPS and fallback attempts stay
in the run receipt. Changed retained originals are withheld, never overwritten.
No original PDFs or trained weights are bundled in the repository.

In the desktop, choose **Advanced jobs / learning → Planning drawing pilot /
source coverage** and select the example JSON. Set its `source_directory` to
the originals folder; set `download_missing: true` to enable recovery. Relative
source directories resolve against the selected JSON. The managed worker uses
the existing one-heavy-job policy, cancellation, monitored memory limit and
persistent history. Open `review.html` through **Results folder** after the job
finishes. This is an advanced source review operation, separate from the world
generation presets.

## What changed in source interpretation

Exact ordinary captions now include front/rear/side elevations and prefixed
sections, such as `Existing Front Elevation`, `Proposed Side Elevation.` and
`Existing Section A-A`. Their own existing/proposed state is retained. Relative
facade names do not establish compass bearings, local axes or an association
between the two side elevations. Prose, conflicting states and mismatched
section letters remain unsupported.

Native caption and glyph inventory now survives incomplete geometry extraction
or topology budgets. These fallback inventories bind an explicitly empty
geometry graph. They cannot assign partial source linework to a view or make
an incomplete document eligible for reconstruction. The original geometry
failure remains visible.

## Real Alton development run

Application **SMD/2024/0136** concerns the facilities/container building near
Woodcutters; it is not a reconstruction of the entire Woodcutters restaurant or
Dark Forest area. The live application page exposed three useful drawings
missing from the selected historical PDF catalogue. Their newly observed
download hashes supplement three previously pinned originals:

| Drawing | Council attachment | Provenance |
| --- | --- | --- |
| Existing Site Plan | 353042 | Existing retained pin |
| Proposed Site Plan | 353043 | Existing retained pin |
| Existing Sections and Elevations | 353046 | Existing retained pin |
| Proposed Floor Plan | 353044 | Newly observed original download |
| Proposed Sections and Elevations | 353045 | Newly observed original download |
| No Dig Surfacing Detail | 353047 | Newly observed original download |

All six originals were recovered over the official legacy HTTP endpoint after
HTTPS returned 503. New hashes are acquisition observations, not independent
verification of physical truth, permission to reuse, or current as-built state.
The surfacing detail is a section/material specification; it is not treated as
a horizontal path footprint.

The six-page run retains **14 visible caption claims**, including four relative
elevations and two sections on each elevation sheet. Two floor-plan claims
include the title-block wording and the actual drawing caption; the count is
not a count of independently identified views or buildings. The existing plan
contains **20 supported surface labels**, with **zero supported contained
surface boundaries**. They remain withheld. White-corridor crop inference also
remains ambiguous on the proposed plan/elevation sheets.

The retained originals have already appeared in development inspections. This
is a development pilot, not an unseen-source accuracy benchmark. Caption-parser
before/after comparisons measure recognition on the same PDFs, not geometry
accuracy. No new training labels, neural checkpoint or accepted park blocks
are produced.

## Outputs and remaining work

Each run requires a fresh output directory and writes:

- `config.json` and `contract.json`, pinning the request, limits and runtime
  implementations; frozen executables can pin actual loader code without
  requiring loose Python source files;
- per-page JSON with original source geometry or its explicit failure,
  caption claims, candidate view regions, surface labels and enclosure results;
- bounded original-page PNG previews and `review.html`;
- `reference-requirements.json`, listing the separate checked evidence needed
  for building and path/plaza measurement;
- `report.json`, with completed/failed page denominators, missing sources,
  blockers and output checksums.

Sources are rechecked before completion. Cancellation, source mutation or an
exceeded output budget has no completed report. Failed sources/pages stay
explicit; inspecting a page does not mean its geometry extraction succeeded.
Physical component coverage and accuracy remain `null` without a checked
reference inventory. Surface connectivity is explicitly unassessed while
surface identity/boundaries remain unresolved.

Next work must establish measured building footprints, corresponding facade
corners and heights, real surface boundaries, surveyed registration and finished
levels. Keep proposed designs separate from current-state reconstruction. A
separate untouched area and checked reference inventory are still needed to
measure generalisation. The six-page development run is not a whole-park or
physical 6 GB Windows-PC acceptance test.

## Packaged verification

```powershell
.\VoxelMapperV3.exe --planning-pilot-smoke-test fresh-planning-validation
```

The synthetic packaged check runs the actual managed worker, recognises two
caption claims and one enclosed surface candidate, verifies output hashes and
persistent restart, and confirms zero labels/checkpoints/physical acceptance.
The Windows workflow runs this against the frozen executable in addition to
source tests. A synthetic check does not supply real Alton reconstruction truth.

Closed source outlines, bounded regional extraction, nominal scale measurements and source overlays are described in [planning outline recovery](planning-outline-recovery.md). They remain unclassified and unregistered.
