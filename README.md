# Voxel Mapper V3.1

Automatically acquire public geographic data and generate a **Minecraft Bedrock `.mcworld` at one block per metre**. Start with a park name/address or bounding box. The normal workflow needs no uploaded terrain, manually prepared GeoJSON, dataset URLs or Minecraft world template.

**Scale and accuracy are different.** Export preserves metric scale and terrain relief, but available public evidence limits reconstruction detail. Current worlds are labelled draft/unverified: building extrusions or DSM-derived roof profiles and mapped paths do not establish themed facades, interiors, or 3D coaster tracks.

## Run on GitHub Actions

### Measured beds and planning components

Permitted registered PDF vectors now retain paint-group identities. A polygon stage reconstructs explicit even-odd fills (`f*`, `B*`, `b*`) using their fill topology, preserving holes and islands while keeping independent paints and viewports separate. Groups with an omitted/out-of-domain boundary are withheld in full. Invalid rings and resource exhaustion produce no partial topology. Nonzero-winding fills, strokes, curves and complex rendering remain unsupported by this stage. Outputs are unclassified, unplaced candidates, not verified plaza/path/ride geometry. Runnymede's reuse gate remains closed and cannot produce polygons through this stage.

Native PDF text origins can now produce bounded semantic association candidates for permitted registered polygons. Single-line feature labels, materials/colours and labelled elevations are retained when the origin falls strictly inside exactly one polygon in the same viewport and CRS. Holes, boundaries, overlapping polygons and multiline fragments are withheld; there is no nearest-feature guessing or cross-page matching. Text origins are not reliable text extents or leader-line targets, so containment remains an unverified hypothesis and does not select a material, establish a floor height or insert world geometry. Runnymede inspection reports this stage as reuse-blocked.

Ordinary PDFs with one explicit projected metre EPSG declaration and four to 64 single-line `E: <value>; N: <value>` labels can produce candidate registration from native text origins, subject to reuse permission. Available non-ballpark coordinate transformations must declare at most one metre accuracy; the affine fit uses residual and leave-one-out checks and forbids extrapolation outside the control hull. This does not locate grid intersections or verify survey marks: constant label offsets can pass every consistency check. Missing/conflicting CRS declarations, geographic/non-metre CRSs, unstable controls, wrong-area fits and resource exhaustion are rejected. Embedded GeoPDF registration is not overridden, Runnymede stays reuse-blocked, and no world geometry is added.

Council document discovery now also selects materials/finishes/paving schedules, topographic/bathymetric surveys and flood/drainage reports. A deterministic round-robin inspection order gives plans, elevations, materials, surveys and water reports a share of the existing PDF budget rather than spending it all on location plans. The budget remains bounded; omitted inspections are reported.

Temporary PDF text inspection extracts labelled floor/water/bed/ground/ridge/eaves level candidates, retaining numeric values, explicitly printed units and datum labels separately. AOD/mOD alone never establishes a specific datum, units are not invented, and scale/layer numbers are not elevations. Context-labelled material and colour candidates remain separate when specifications are mixed. Existing/proposed labels are recorded as unverified text. At most 100 candidates per page are retained, long lines/overflow are reported, and raw text/PDFs are not packaged. Candidates have no verified polygon association and never enter world generation by themselves. Automatic application discovery remains subject to provider coverage/access; this is not an automatic drawing-to-polygon implementation.

The build engine now supports a separate `bathymetry` raster specification with `elevation_type: bed_elevation`, metre units, registered source ID and a declared vertical datum matching terrain. It emits one stone substrate block at each sampled bed elevation and a water column above it up to the estimated/mapped surface. Stone is a substrate approximation, not measured bed material. Missing, nonfinite, above-water, deeper-than-100 m or sub-voxel-depth samples retain surface-only output with counted warnings; no depth interpolation is performed. Airborne DTM is not automatically used as bathymetry. No automatic Thorpe bathymetry provider has been connected.

Drawing adapters can supply `planning_geometry_records` to the build engine. Each component needs a unique ID, registered source, document/revision identity, verification reference, confirmed reuse permission, confirmed registration and confirmed as-built status. Supported semantic types are `plaza`, `path`, `ride_structure`, `building_component` and `building`. Registered WGS84 polygons/multipolygons preserve holes and must fit acquisition bounds. Structure components require finite `elevation.base_m` and `elevation.top_m` with the matching datum; PDF layer names/numbers never substitute for elevations. Multiple independently specified components can describe an elevated structure without filling the air underneath. Buildings in this pathway use explicit component elevations rather than mixing drawing geometry with unrelated DSM estimates.

Known drawing `surface` materials use the same Minecraft palette as mapped paths. Concrete additionally supports the sixteen named Minecraft colours via `surface_colour` / OSM `surface:colour`; unsupported colours keep the base material and a warning. Material and colour are Minecraft approximations, not an exact visual match. Adapter confirmations are required inputs, not independent verification performed by the voxelizer. Rejected components produce explicit report decisions. Automatic acquisition is wired to consume a council adapter's `geometry_records`, but the existing Runnymede adapter does not yet produce usable records: automatic PDF semantic interpretation/registration and a permitted drawing source remain outstanding. These engine capabilities do not change the downloadable Thorpe draft on their own.

Elevated OSM building footprints with positive layer tags can retain a DSM-derived roof surface when the existing coverage/plausibility checks pass. Only a one-block roof surface is emitted: the unknown elevated floor, walls and supports are left unmodelled. Negative layers and tunnels remain omitted without explicit elevation. This is a partial unverified roof model, not complete complex-building reconstruction.

Automatic polygon locations now acquire a 200 m context margin and build the resulting bounding box, including mapped lakes outside the leisure boundary. Explicit bounding boxes remain unchanged; all area and voxel budgets still apply. Lakes crossing the context bounds remain clipped, so this does not guarantee complete surrounding lake coverage.

Polygon water is represented by a single horizontal surface using an explicit datum-compatible elevation, or a median of at most 81 interior terrain samples when their central elevation range is within 1 m. Raster estimates are unverified, and inconsistent or insufficient samples cause omission with a reported error. Airborne terrain over water is not bathymetry: grass terrain is suppressed inside mapped lake polygons, and no measured lakebed or depth is claimed. River centerlines still use the existing extrusion model.

Path materials use mapped `surface` tags, including asphalt, concrete, paving stones, brick, cobblestone, wood, metal, stone and unpaved surfaces. Minecraft blocks approximate the real material. Missing or mixed material tags retain an explicit fallback warning; `paved`/`unpaved` identifies a class rather than a known constituent material. Planning drawings do not yet supply material specifications or constructed polygons automatically.

Open **Actions → Voxel Mapper 3.1 — Bedrock World → Run workflow**:

- `location`: a specific park name and country/address, such as `Thorpe Park, Chertsey, United Kingdom`.
- `bbox`: optional `west,south,east,north`; overrides the location name. Maximum bounding area is 4 km² per run.
- `strict`: fail the accuracy gate after generating and retaining the draft world if evidence warnings remain.

Download the workflow artifact. Open `park.mcworld` in Minecraft Bedrock to import it. Inspect `quality-report.json` for omitted features, assumed dimensions, terrain coverage and reconstruction limits. `acquisition.json` records provider outcomes. Ambiguous names fail rather than selecting a park silently.

The workflow is manually dispatched, but every supported data acquisition and export step inside it is automatic. Larger regions currently need separate bounding-box runs; seamless tile stitching is future work. This pipeline targets Bedrock 1.21.130 data through pinned Amulet Core; an actual in-game import still needs validation.

## Automatic sources

| Data | Acquisition and evidence handling |
| --- | --- |
| Park location/boundary | Nominatim; polygon boundaries are used when available |
| Buildings, roads, footways, parking, water, mapped attractions | OpenStreetMap/Overpass with retained raw response and source attribution |
| England terrain | Environment Agency native 1 m DTM WCS, with coverage discovered from capabilities |
| England building surfaces | Automatic last-return 1 m DSM acquisition when compatible EA ground elevations are available |
| Other regions / unavailable EA data | Automatic Open Topo Data Mapzen sampling; coarse mixed-source fallback is flagged |
| England planning evidence | Automatic spatial queries for planning authorities, applications and listed-building records; coverage and document-catalogue availability reported |
| Supplemental buildings | Automatic Overture release discovery and bounded footprint download; disjoint non-OSM source footprints supplement existing mapped features |
| Runnymede drawings | Automatic application-address search and document lists from discovered references; bounded temporary PDF inspection, with blocked searches and reuse restrictions reported |
| Bedrock world | Automatic LevelDB world creation, block composition, read-back validation and `.mcworld` packaging |

Mapzen's approximately 30 m output includes areas derived from lower-resolution data. It does not supply one-metre surveyed accuracy. Provider outages cause failure, or a documented supported fallback; no fabricated terrain is substituted. All extracted raster/input evidence is retained alongside reports. Data provider API limits are respected for the elevation service (100 samples/request and at least one second between requests).

OSM multipolygons preserve courtyard holes. Incomplete relations are reported. Missing widths/heights are reported as assumptions; draft buildings default to 6 m. Ground features follow per-column sampled terrain. Bridges, tunnels and nonzero layers without absolute elevation evidence are omitted with errors; OSM layer numbers never become guessed heights. Their elevations are not currently acquired from another automatic source.

Verified planning-drawing geometry extraction, independent surveyed control-point validation, classified building meshes and 3D ride geometry are **not implemented**. Planning record discovery and spatial context matching are implemented for the England national API. A Runnymede adapter supports address search, document listing and temporary PDF inspection; incomplete/blocked coverage is explicitly reported. Capability gaps are included in every report, so strict mode cannot certify a complete accurate park with the current adapters. There is no manual data preparation step hidden behind these capabilities.

## World export

- One voxel maps to one Bedrock block; exports reject other voxel sizes.
- East is Minecraft positive X; north is negative Z. Local projection details are recorded.
- A constant Y offset places the lowest mapped elevation at Y=64 while preserving relative heights. Geographic elevation equals Minecraft Y minus the recorded offset.
- Areas exceeding the supported vertical range fail instead of being resized or cropped.
- Terrain receives four blocks of ground fill. This is not a full geological volume.
- Generic block materials represent feature classes; accepted DSM building profiles use distinct wall and roof blocks. Overlap is composed deterministically: structures/buildings take precedence over paths, parking, water and terrain.
- Chunk writes are processed one at a time using an on-disk composition database. Every composed block and every unwritten air cell in saved sections is checked after reopening the Bedrock world before packaging. Palette index zero is explicitly reserved for air to prevent solid blocks filling otherwise empty sections.
- The world name marks it as a draft, and attribution/georeferencing files are included in the `.mcworld`.
- Minecraft can generate unrelated terrain beyond exported chunks; the mapped area is recorded in the configuration.

The voxel budget, scan budget, native raster budget and world block budget bound resource use. The world is structurally verified using Amulet, which is not equivalent to testing import and play inside Minecraft.

## Local execution

Python 3.12 is used in Actions. Native dependencies may require a C/C++ compiler.

```sh
CC=gcc CXX=g++ python -m pip install .
python -m voxel_mapper.cli --location 'Thorpe Park, Chertsey, United Kingdom' --output output
python -m voxel_mapper.cli --bbox=-0.5124,51.4027,-0.5116,51.4033 --output small-area
python -m unittest discover -s tests -v
```

Use an empty output directory per run to prevent stale exports being mistaken for successful new output. `--strict` retains the generated draft and fails if warnings/errors remain.

## Evidence and formats

`voxels.jsonl` retains feature/source identifiers before composition. `input.geojson` is WGS84; `features-local.geojson` uses the local projected CRS recorded in the report and is not RFC 7946 WGS84 GeoJSON. `resolved-config.json` records the automatically selected sources, location and bounds. GeoTIFF checksum, pixel spacing, horizontal CRS and declared vertical datum are reported. EA data uses ODN; fallback Mapzen heights are not asserted to share a verified survey datum. No automatic vertical datum transformation is applied.

Provider documentation:

- [Environment Agency DTM WCS](https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs)
- [Open Topo Data Mapzen data](https://www.opentopodata.org/datasets/mapzen/) and [API limits](https://www.opentopodata.org/)
- [OpenStreetMap attribution/licence](https://www.openstreetmap.org/copyright)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Amulet Core](https://github.com/Amulet-Team/Amulet-Core)

## Automatic building surface profiles

When EA terrain is selected, the pipeline automatically downloads the compatible last-return DSM without asking for files or URLs. Other regions currently retain the declared-height/estimated-extrusion fallback; the report records that no compatible surface provider is implemented there. Mixing the coarse Mapzen terrain with ODN surface data is prohibited.

Within mapped building polygons, ground and surface samples form a 2.5D model: vertical columns from one estimated foundation plane to observed surface elevations. This retains metre-grid roof slopes, ridge height changes, stepped profiles and courtyard holes. The default foundation plane uses the 10th percentile of available ground elevations inside the footprint; it is an estimate, not a surveyed foundation. Observed roof columns receive a roof block over the generic wall material.

Checks reject insufficient sample coverage (below 90%), implausible surface-minus-ground heights (outside 1.5–120 m), and strong conflicts with declared building height. Isolated returns more than 3 m above neighbouring samples are omitted. Rough surfaces can trigger rejection as possible vegetation or complex geometry. Missing/outlier columns in otherwise accepted profiles are left unmodelled and reported, rather than interpolated. Small footprints with fewer than four usable voxel columns fall back. Building sampling is capped at 200,000 bounding-grid checks per feature and shares the total scan budget.

Rejected surface profiles use the existing tagged/assumed-height fallback with the rejection reason retained. Accepted profiles retain DSM/DTM source IDs, height statistics, usable fraction, omitted/outlier counts, foundation method and uncertainty warnings in `building_profiles` within the quality report. All profile records remain `accepted_unverified`: a DSM includes vegetation and equipment, and the composite's observations span different dates. These checks do not classify every return or prove that a current footprint matches an old survey.

The automatically selected EA source metadata records its composite observation period (2000–2022). Newer construction may be missing; detailed decorations and overhanging/undercut geometry cannot be recovered from this surface grid. [EA DSM metadata](https://environment.data.gov.uk/dataset/9ba4d5ac-d596-445a-9056-dae3ddec0178) describes the source's last-return surfaces and observation period.

The EA adapter also downloads the open OSTN15 datum grid automatically, retains its checksum, and records the selected coordinate operation and its stated accuracy. If that download fails, the available fallback operation is recorded and the quality report flags degraded horizontal conversion. Operation accuracy does not certify OSM footprint accuracy or survey alignment.

## Automatic transport surfaces

Mapped roads, paths, sidewalks, queues, cycleways and steps retain separate feature classes. Closed `area:highway` polygons use their actual mapped footprint; ordinary closed centreline ways remain lines. Construction/proposed/abandoned/razed highways are omitted and reported. Sidewalk and queue geometry must be mapped explicitly; road tags alone do not establish their position.

Line widths use `width_m`, then OSM `width`, then `est_width`. Single positive metre, feet and feet/inches values are supported. Ambiguous lists/ranges and unsupported values are reported before trying another supported value or a documented class estimate. `maxwidth` is an access restriction and is never used as geometry. Defaults are 6 m for roads, 3 m for service roads/tracks, 2 m for paths/sidewalks/cycleways/steps and 1 m for queues. These are assumptions, not measured dimensions; sub-metre widths warn about voxel quantisation. Lane counts do not invent lane geometry.

Supported `surface` tags choose approximate Minecraft materials: asphalt, concrete, paving stones, cobbles, wood, gravel, compacted earth, dirt, grass and sand. Missing/unsupported surfaces use a generic class material with a warning. Paving occupies one block at the sampled ground elevation, including fractional raster elevations, rather than raising paths into two-block extrusions. Steps follow sampled terrain; individual tread dimensions are unknown. `transport_profiles` records class, width, width source, original surface, selected block material and assumptions. Each paving voxel retains its feature and elevation source IDs. Tagged widths/materials are evidence from OSM, not independently surveyed accuracy.

References: [OSM width](https://wiki.openstreetmap.org/wiki/Key:width), [surface](https://wiki.openstreetmap.org/wiki/Key:surface), [area:highway](https://wiki.openstreetmap.org/wiki/Key:area:highway).

## Automatic planning evidence and feature matching

Inside the England provider discovery window, every run queries the [Planning Data API](https://www.planning.data.gov.uk/docs) using the selected WGS84 bounding polygon. The adapter discovers intersecting local planning authorities, planning applications and listed-building records. It checks the planning-document catalogue automatically. No dataset URL or record upload is required. A separate Runnymede adapter handles that council's public portal; other council adapters and drawing georeferencing are not implemented. Regions outside the discovery window are explicitly `not_supported`; the window itself does not establish national coverage.

Raw query pages, checksums and the document catalogue are retained in `planning-evidence/`. `planning-discovery.json` records timestamps, counts, provider failures, empty results and pagination limits. Queries are bounded to five pages of 100 records per dataset; hitting the limit reports truncation. Outages are distinct from successful empty responses and do not silently claim complete coverage. Empty results do not establish that a site has no applications or buildings.

`planning-matches.json` records spatial candidates in a local metric CRS. Site polygons/record points are associated with intersecting mapped features; multiple candidates are explicitly ambiguous. Authorities are separate context. Original OSM geometry, heights and source IDs remain intact; `planning_evidence` references add record IDs, dates and links to candidate features. The matcher does not assert identity from proximity or turn a development-site boundary into a building footprint. Invalid/out-of-area evidence is rejected, courtyard holes are respected and candidate comparisons share a bounded budget.

Planning permission or an application date does not establish that a structure was built. All associations are context with construction status `not_verified`; the current adapter makes **zero physical additions or geometry replacements**. Confirmed as-built survey/drawing interpretation and stronger geometry conflict resolution require further adapters. Coverage status and matches appear in the packaged world quality report and Actions artifact, so the added records cannot be mistaken for increased measured world accuracy.

## Runnymede consultation drawings

When authority discovery identifies Runnymede (`E60000275`), the pipeline automatically searches its public portal using the resolved place name. Bounding-box runs use a unique named theme park from the raw OSM response when available. Search uses the public form's state and selected fields, carries the form/page referrer through navigation, and follows at most three results pages. Application references are prioritised by recent reference year/serial within the last century before the application budget is applied; this is not a construction-date or approval-status claim. Address matches are candidates, not surveyed spatial matches. A 403, outage or unrecognised page is reported as blocked/unavailable. The adapter can also use application references found in the national records; it never hardcodes a Thorpe Park application number or guesses document IDs.

For up to ten discovered applications, the adapter reads public document-list metadata, verifies the requested reference, keeps plan/drawing/survey entries and records their opaque IDs, titles, original received-date strings and URLs. Dates remain raw because portal date formatting can be ambiguous. At most 500 drawing records and six PDF inspections are processed per run; omitted/truncated counts remain visible in `council-drawings.json` and the world report. Original correspondence documents are excluded from the drawing inventory.

PDF inspection downloads at most 10 MB per document temporarily, validates PDF format and inspects up to twelve pages. It records checksums, page sizes, printed scale/revision/date candidates, and viewport/LGI registration results. Encrypted/invalid documents and budget failures are reported. Fonts used by planning PDFs are supported through fontTools. Scanned pages without text are identifiable, but OCR is not implemented. Printed scales are **not map registration**; no geometry is placed, no revision is assumed to be current/approved, and no construction is inferred.

The council's [copyright notice](https://www.runnymede.gov.uk/planning-permission/view-object-support-application-1) restricts downloaded drawings to consultation uses. The adapter records `consultation_only` reuse status and does not retain/redistribute original PDFs in the Actions artifact or world. Licenced geometry reuse, drawing vectorisation, control-point alignment and as-built verification remain outstanding. Public availability alone does not give a drawing the national planning dataset's OGL licence.

## Embedded GeoPDF registration checks

PDF inspection automatically validates ISO-style `/VP` viewports with `/GEO` measures containing explicit WGS84 EPSG:4326 coordinates. `/GPTS` is read as latitude/longitude and `/LPTS` as normalised viewport positions. EPSG/WKT declarations must agree. Other datums/projected systems, legacy LGI encoding, page rotation, non-default UserUnit and missing control arrays are currently unsupported rather than inferred.

Each viewport needs four to 64 unique controls, a valid page rectangle, a stable non-collinear fit, and a maximum local extent of 20 km. An affine transform maps normalised page positions into the build's local metre CRS. Both fitted residuals and withheld-point prediction errors must be at most 0.5 m. When build bounds are available, the registration must intersect them. Multiple/inset viewports retain separate candidates; none is selected automatically. At most sixteen viewports per page are inspected.

Successful registrations remain `internally_consistent_unverified`: embedded control agreement is not independent surveyed accuracy. Reports retain the transform, CRS, errors, controls' convex hull and any declared boundary restriction. The coordinate helper rejects points outside that domain to prevent extrapolation. Plain PDFs report `metadata_missing`, and rejected metadata retains a reason. These checks establish an auditable candidate coordinate mapping, **not drawing vectorisation, physical geometry, construction status or reuse permission**. No original PDF is added to the world.

References: [GDAL GeoPDF documentation](https://gdal.org/en/stable/drivers/raster/pdf.html), [ISO 32000-2 geospatial specification corrections](https://pdf-issues.pdfa.org/32000-2-2020/clause12.html).


## Reuse-gated vector boundary candidates

`drawing_vectors.extract_vectors` can extract straight, painted PDF subpaths for sources with established geometry reuse permission and validated GeoPDF registration. It applies nested content matrices and graphics-state restoration, handles line/rectangle/close operators, and retains fill boundaries separately without interpreting them as building footprints or resolving holes. Each viewport is a separate layer with its local metre CRS. Paths crossing the registered domain or page crop box are omitted rather than extrapolated.

The default reuse gate blocks extraction. Runnymede consultation inspection explicitly keeps this gate closed and reports `blocked_reuse`, with no derived coordinates retained. No automated permitted drawing provider is connected yet. This is an extractor capability tested with synthetic PDFs, not an additional source of park detail in the current workflow.

Curves, clipping, form/image XObjects, marked/optional content, external graphics states and unknown operators reject the entire page with a reason; partial geometry is discarded. Extraction is capped at 10 MB content, 100,000 operations, 2,000 painted subpaths, 20,000 constructed points and 64 graphics-state saves. Candidates remain unclassified and construction-unverified, and are never inserted into a Minecraft world. Semantic interpretation, independent alignment and a permitted source adapter remain required.

Reference: [ISO PDF graphics/path specification](https://udp.adobe.io/document-services/docs/assets/35e4369068f86065372c18787171a17e/PDF_ISO_32000-1.pdf).


## Automatic supplemental building footprints

Every location/bbox run queries the official Overture STAC catalog, pins its current release, and downloads bounded building records through `overturemaps` 1.0.2. An isolated Linux reader has a 180-second deadline, a 64 MB output ceiling and a 20,000-feature ceiling. The same 4 km² area budget applies. Interrupted, malformed or failed downloads are discarded completely, with explicit provider errors; an empty result is `empty_coverage_unknown`, not verified absence. Catalog/data hashes, UTC query time, release, source metadata and per-feature decisions remain in the Actions artifact and world quality report.

The building theme is ODbL. The world credits Overture and upstream contributors and links the [building attribution list](https://docs.overturemaps.org/attribution/#buildings). Full upstream source records are retained on each accepted feature. See the [official building guide](https://docs.overturemaps.org/guides/buildings/) and [official Python client](https://docs.overturemaps.org/getting-data/overturemaps-py/).

OSM-derived geometry is withheld, including buildings absent from the current OSM response: an older Overture release cannot silently reintroduce deleted OSM buildings. Additional geometry needs a traceable non-OSM source (upstream record ID or provider/resource/version tied to the retained GERS ID and release), a valid ground-level 2D polygon, 2–100,000 m² area, and at least 0.9 confidence when its source supplies confidence. Underground/elevated records and unsupported heights are rejected. Candidates within 2 m of any mapped feature or an accepted supplemental building are withheld; footprints are never cut into fragments to make them fit. Existing geometry and attributes remain unchanged, and a shared 100,000-check budget bounds conflict resolution.

Accepted supplemental footprints enter normal building generation, including the existing DSM roof checks when compatible data is available. Supplied height is in metres; otherwise the same documented fallback applies. Footprints can be imagery-derived roofprints and do not establish recent construction status or surveyed accuracy. Building parts, independent validation and detailed facades remain unsupported; additions remain draft/unverified and cause strict mode to fail. An additional Actions workflow performs a live Thorpe Park-area download check and retains its evidence; offline tests independently verify conflict handling and actual supplemental blocks in a packaged 1:1 Bedrock world.

The reader explicitly labels rows from the selected `buildings/building` partition because its Parquet files can omit partition fields. Conflicting partition labels fail rather than being overwritten. A source without an upstream record ID must provide provider, resource and version; the decision is marked `provider_resource_version_only`, so source-level traceability is not mistaken for an independently addressable upstream observation.


## Automatic bridge-deck candidates

Explicit `bridge=yes`/`bridge=boardwalk` transport centerlines may now use compatible projected-metre terrain and surface rasters at 1 m or finer sampling, with the same declared vertical datum. Only simple open 4–500 m spans, 1–20 m transport widths and a 1 m voxel grid are supported. Tunnels, stacked/negative layers, steps, ride tracks, multipart/closed spans and spans clipped by the build boundary still require stronger absolute-elevation evidence. `layer` is never converted into height.

Every station (at most 1 m spacing) needs three transverse samples with at most 0.75 m surface variation; longitudinal deck changes must not exceed 0.5 m per metre. Both ends must meet terrain within 1 m, with two-metre exterior approach checks. At least half the central-half samples must show 1.5 m clearance, and voxelisation must retain at least a two-block gap somewhere. Every emitted column needs finite DTM/DSM values within the supported clearance range, must agree with its nearby longitudinal station within 1 m and cannot introduce disconnected height jumps or footprint gaps. No missing columns are interpolated. Per-span scans are capped at 100,000 checks and consume the shared build scan budget. These conservative thresholds are heuristics, not independently certified accuracy tolerances.

Accepted results remain `accepted_unverified`. They emit a single transport-material block at the sampled deck elevation, preserving the terrain below and the intervening air; thickness is an explicit one-block assumption. Supports, railings, underside geometry and bridge object classification are not invented. Falling sand/gravel surfaces use a documented stable-stone approximation where structural support is unknown. Profiles retain source IDs, height/clearance and connection metrics, budgets and rejection reasons in `bridge_profiles`; every accepted candidate adds strict-mode warnings. The EA [last-return DSM description](https://environment.data.gov.uk/dataset/9ba4d5ac-d596-445a-9056-dae3ddec0178) includes vegetation and vehicles as well as buildings and terrain, so smoothness and clearance alone do not certify a measured bridge deck.

Validation against the saved automatically acquired Thorpe Park evidence: four transport spans fail surface slope/transverse consistency, one crosses the park build boundary, and one is stacked. Two additional bridge-tagged log-flume segments are ride geometry, not transport decks. No new Thorpe Park bridge blocks are justified by this evidence. Tests independently cover a supported synthetic span, numeric clearance, missing/coarse/nonfinite data, disconnected approaches, canopy/rail/spike rejection, datum/budget limits, clipped and stacked spans, and an actual Bedrock deck with air below after export/read-back.
