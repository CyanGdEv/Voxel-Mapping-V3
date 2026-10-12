# Source-bound survey station discovery

The area pipeline now discovers a narrow native station-coordinate table contract,
binds station identifiers to visible leader-attached marks and can emit a survey
reference registry without hand-copying coordinate rows. It does not certify
physical station identity or survey accuracy automatically.

## Discovery and reference release

Supported rows are standalone native text with retained origins and checked ink:

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

Version 2 adds a bounded display-list adapter for Form text, transformed straight
strokes and readable native-font traces. It preserves original glyph positions,
font screening, paint identities and rectangular clip scope. Translated/rotated
Forms work; repeated invocations cannot silently choose one identity. Compound,
dashed, nonopaque, optionally layered or unsupported clipped strokes cannot
become marks. Native Unicode decoding and raster ink agreement do not themselves
certify station meaning: the source policy still verifies table interpretation.

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
    "use_discovered_references": true,
    "max_ocr_pages": 4
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
budgets remain enforced. Unrecoverable font encodings, image-only tables and
complex rendering remain unresolved. By default at most four text-poor image
pages are inspected with Tesseract: 20 seconds per page, 3,072 pixels per side and
minimum line confidence 70. `max_ocr_pages` accepts 0..16. The engine binary hash,
adapter version and selected PDF/pages enter the observation contract. OCR leads
never enter the emitted survey reference registry, including when a survey policy
exists. An OCR-recognised number is not a verified native coordinate attachment.

## Real Mutiny result

The retained audit checked 73 PDFs / 213 pages. It found zero supported station
rows and emitted zero references. The old operator adapter rejected 91 pages:
74 contained image XObjects, eight contained Form XObjects and nine hit budgets.
The new adapter completes native inspection on 171 pages and identifies 42
image-only pages needing OCR. Four OCR samples produced three no-lead results
and one unbound numeric lead (`417553`); it is neither a verified E/N pair nor a
station attachment. The remaining 38 image-only pages await budgeted OCR. Native
inspection also cannot certify absence of coordinates in image-backed content
on mixed pages. All 213 page observations reuse in a fresh output directory.

A separate run of the existing anchor auditor on the same originals retained two
application-form location hints and found no embedded/grid/axis candidates. Those
form coordinates remain location hints, not controls. No real frame, component
or park block was accepted by these audits.

Five missing block/amended-plan links first returned HTTP 502 through HTTPS. The
same official attachment resources succeeded through HTTP: five links yielded
three distinct checksum-pinned original PDFs. They contain extensive topographic
linework and native labels for levels, surfaces, fences, trees and footbridges.
One inspected sheet has 215,484 drawing paths; all three pages exceed the current
native extraction path budget and are withheld whole, rather than partially
sampled into geometry. No station coordinates, embedded grid or axis candidates
were accepted. Registration, vertical datum and current construction state remain
unverified; these are dated key/block plans, not certified independent surveys.

The recovered source catalogue is `evidence/mutiny-recovered-plan-sources.json`.
`Corpus.ingest` now accepts an explicit `transport_url` for the exact same official
host, path and query as the canonical HTTPS identity. HTTP transport requires a
pinned PDF hash; different hosts, resources, credentials, ports and fragments are
rejected. There is no automatic downgrade or endpoint probing. Replays verify
retained bytes and preserve canonical source identities. The acquisition and
analysis receipt is `docs/evidence/mutiny-survey-source-acquisition.json`. A reusable
source pack contains the three unchanged PDFs, catalogue and consistent corpus
database. Raw PDFs are not committed into the code repository.

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

The next real-data work includes partitioning the recovered large maps into bounded
source regions, handling their actual scale captions and source-bound annotations,
and finding independently established station identities and accuracy. General
cross-view building assembly and model training are separate unfinished stages.
