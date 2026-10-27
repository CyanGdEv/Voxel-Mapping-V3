# Map-guided planning research

The mapping reader turns public map feature names, former names, tags and references into planning-application research tasks. This is an added research capability and persistent evidence memory; neural weights are unchanged by reading a map. The existing learning cycle still fits its heads when verified source-pair training data changes.

The initial supported mapping source is the official OpenStreetMap API, plus checksum-pinned retained OSM XML. It works across configured parks and areas. It reads structured data rather than map screenshots or proprietary tiles. Referenced official websites, Wikidata and Wikipedia pages can be inspected by the existing web research controller. It does not implement a general browser for every mapping website or every council portal.

## Use

In the updated desktop source, choose **Map names / planning application research** and submit `examples/desktop/alton-map-planning-research.json`. A new Windows EXE has not been rebuilt in this change. The same job works from a source checkout:

```sh
python -m voxel_mapper.map_planning_research --config request.json --output run-001 --cache web-cache
```

Each output directory must be fresh. Keep the cache to reuse exact retained bytes. Set `max_research_jobs` to zero to extract names/tags and prepare queries without following web sources. An uncached map still requires network access unless a pinned local snapshot is supplied. `offline: true` inside `map_source` requires a retained map; `research.offline` separately controls the web jobs.

Configure the site name, public location, WGS84 bounds `[west,south,east,north]`, and relevant council `planning_hosts`. Optional `focus_names` prioritizes specific mapped rides/areas in the order supplied. Queries retain the selected park/location and primary council host. A balanced queue reserves places for buildings, facilities, areas and paths alongside rides. Former and alternative names are retained as separate search clues, not merged into verified identities. Features with the same name produce one initial query within the selected site.

For a local snapshot, set `map_source.snapshot_path` and `snapshot_sha256`. Relative paths resolve against the request JSON. The reader filters features to those with an available member point in the requested bounds. A pinned file does not independently prove that the original download used those bounds. Relations are examined one level deep; missing/outside members remain explicit gaps.

## What it studies

- Ride and track tags, names, `old_name`, `alt_name`, local and official names.
- Buildings, named paths/areas, toilets, shops and other named facilities.
- Operator, brand, public address, opening/date and structural-layer tags when present.
- Official website links and syntactically valid Wikidata/Wikipedia references.
- Explicit `ref:planning` and `planning:reference` tags, treated as unverified leads.

OSM element type/ID, map URL, source body hash, tag name, timestamps/version when present, and the original XML are retained. Dates and bridge/layer tags do not become ride heights or construction dimensions. No contributor identity is used as a training feature.

The reader also examines fetched originals for literal project codes such as **SW8**, **Secret Weapon 8**, and **Project Exodus**, and recognized SMD/RU application-reference patterns. These produce cited follow-up searches within the same bounded web-job allowance. Witness snippets and original hashes show where each clue came from. A code found on a linked page is a candidate association, not proof that it names the mapped feature. Other councils' reference formats are not yet covered by this extractor.

## Connect it to the learning cycle

Each `public_sites` entry in `research-learning-cycle-v1` can now supply:

```json
{
  "map_context": {
    "bounds_wgs84": [-1.897, 52.984, -1.882, 52.994],
    "offline": false
  },
  "map_focus_names": ["Wicker Man", "Mutiny Bay"],
  "planning_hosts": ["publicaccess.staffsmoorlands.gov.uk"]
}
```

See the updated `examples/desktop/adaptive-research-cycle.json` for Alton and Thorpe configurations. Map names specialize the current coverage/error curriculum. Track/support tasks use explicitly tagged coaster candidates; building/opening tasks use building/facility clues. Existing supplied plan links remain first in the seed list. Referenced web pages can then expose more detailed codes and application references.

Map source bodies, successful task IDs and up to 256 derived follow-up tasks persist in SQLite. On restart, compatible follow-ups for the current map body and site are loaded before other tasks. Tasks without retrieved sources remain retryable. Source hashes and task payload digests are checked; this is research memory, not automatic validation of the assertions inside a map or web page.

The cycle supports at most four map areas, sharing its existing 64 MB / 600 second research budget with subsequent web jobs. A standalone map job has the same total budget and allows at most six web jobs. A map XML is capped at 16 MB and 100,000 top-level elements; each requested dimension is capped at 0.05 degrees. Up to 256 named features and 32 initial queries are retained; each completed web job can propose up to eight follow-ups. Cancellation, source hashes, fixed official API requests, public DNS checks, no redirects/authentication for API acquisition, and the existing web-download guards remain enforced.

## Validation and limits

Live map acquisition returned 205 named features from the selected Alton Towers area and 174 from the selected Thorpe Park area. These are records selected from the API snapshots, not independently verified park inventories. The snapshots include mappings for rides, buildings and areas, with former-name examples Galactica/Air and Nemesis Reborn/Nemesis. Map edits may be inaccurate, recent, historic or speculative.

Using the retained Alton snapshot and linked public pages, the focused Wicker Man job recovered literal Secret Weapon 8 and SW8 clues and automatically queried the project code. That follow-up returned no source. No new independently verified planning application or geometry training pair is claimed from this check. Initial council searches were sparse, and the official ride page returned HTTP 403; the reader recorded the failure and used the accessible referenced material.

The actual 96-pair learning cycle reused its existing checked checkpoint while consuming the map evidence. Its output, curriculum, original source pins, restart results and tests are recorded in `evidence/map-planning-research-validation.json`. Synthetic tests separately exercise fitting, restart, persistent discovered application follow-ups, and safe map/web handling. No world blocks, neural weight updates from maps, production promotion or measured geometry-accuracy improvement occurred.

OpenStreetMap attribution: © OpenStreetMap contributors, ODbL-1.0; https://www.openstreetmap.org/copyright. Referenced pages/documents retain their own provenance and rights.
