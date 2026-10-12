# Source-bound survey station discovery

The area pipeline now discovers a narrow native station-coordinate table contract,
binds station identifiers to visible leader-attached marks and can emit a survey
reference registry without hand-copying coordinate rows. It does not certify
physical station identity or survey accuracy automatically.

## Discovery and reference release

Supported rows are standalone explicitly positioned standard-font native text:

```text
EPSG:27700
CP:A E=407345.123 N=343810.456
CP:B E=407350.123 N=343820.456 Z=185.200
```

Each station also needs one separate exact `CP:identifier` label connected by a
unique straight leader to an orthogonal crosshair. Text origins must agree with
the native glyph trace; original-font raster screening checks the table row,
mark label and CRS declaration. Source strokes must be unique, sufficiently
opaque and not covered by a later fill, image or shade. Missing or repeated rows,
marks, ambiguous leaders, white/covered strokes and unsupported rendering are
withheld. Label proximity, text-centre coordinates and application-form locations
cannot supply attachment points. Optional printed Z stays a candidate level;
it is not a verified vertical datum.

Station candidates remain unregistered. To emit references, the original survey
source must have an accepted, checksum-pinned, independently verified policy in
the shared manifest. Its `kind` is `survey`, `registration_status` is `accepted`,
and metadata needs:

```json
{
  "physical_landmarks_verified": true,
  "reuse_allowed": true,
  "station_coordinate_identity_verified": true,
  "station_coordinate_table_contract": "explicit_cp_en_station_table_v1",
  "station_verification_reference": "source-bound independent survey review",
  "station_pages": [1],
  "station_reference_role": "control",
  "reference_accuracy_m": 0.1
}
```

These values represent supplied verified evidence. Discovery never sets them
from successful extraction, geometric scores or world export. Each source has
one explicit role; a single survey cannot be split into controls and supposedly
independent checkpoints. The visible EPSG declaration must match its projected
metre CRS. Local/arbitrary-grid restrictions withhold reference release. Duplicate
station IDs across pages or revisions are excluded, never silently selected.
The existing qualification stage still rejects self-source alignment and reused
checkpoint survey bytes, and recomputes fit, scale, residuals and error budget.

## Area pipeline

Discovery runs by default with registration qualification or automatic
reconstruction. Its manifest and knowledge-store settings inherit from those
stages. An evidence-only audit can be enabled without a manifest. Use the released
registry instead of a handwritten reference file explicitly:

```json
{
  "survey_landmark_discovery": {
    "enabled": true,
    "use_discovered_references": true
  },
  "automatic_reconstruction": {
    "enabled": true,
    "manifest": "inputs/manifest.json",
    "terrain_config": "inputs/terrain.json"
  }
}
```

An empty discovered registry cannot qualify a drawing or bypass recipe checks.
Discovery uses only source pages already acquired for the area. Shared survey
documents must be included in those source inputs. The generated registry feeds
registration qualification and automatic component recipes. Ordinary and explicit
semantic adapters retain their separate view/state, component, material and
vertical-datum checks. Automatic recipe contract v5 pins this changed upstream
pipeline; use a fresh controller directory while keeping a stable evidence store.

Per-page facts retain original PDF hashes, source policies and dependency ancestry.
Original bytes and output receipts are checked on replay. Rejections block reuse;
changed policies create immutable new runs. Limits are 10,000 pages, 1,000 pages
per PDF, 64 station rows and 64 labels per page, 16 CRS declarations per page,
1,000 emitted references and 128 MB of page output. Native parser, glyph and paint
budgets remain enforced. Unsupported forms, custom fonts, raster tables and
complex rendering are retained as unresolved pages; no OCR coordinates are
promoted by this adapter.

## Real Mutiny result

The retained audit checked 73 PDFs / 213 pages. It found zero supported station
rows and emitted zero references. 91 pages have unsupported native coordinate
text; 122 completed the supported native inspection without a station candidate.
All 213 pages reuse their facts in a fresh output directory. This does not prove
that the unsupported drawings contain no survey information.

A separate run of the existing anchor auditor on the same originals retained two
application-form location hints and found no embedded/grid/axis candidates. Those
form coordinates remain location hints, not controls. No real frame, component
or park block was accepted by these audits.

```sh
python scripts/audit_survey_landmark_discovery.py \
  --corpus work/mutiny-bay/corpus --geometry work/mutiny-bay/drawing-geometry \
  --work-directory station-audit --output station-audit-receipt.json
```

Evidence: `docs/evidence/survey-landmark-discovery-validation.json`. Fixture tests
extract independent control/checkpoint registries, qualify a separate drawing,
and emit its path, wall and roof recipe without a handwritten reference file.
Negative tests cover local grids, wrong CRS, absent policies, station/attachment
occlusion, duplicate IDs, altered source/registry bytes and rejected parents.

The next real-data work remains broader survey-table/rendering support and
acquisition of actual area survey/control sources, with independently established
station identities and accuracy. General cross-view building assembly and model
training are separate unfinished stages.
