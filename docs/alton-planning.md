# Alton Towers planning integration

The Actions location default is now Alton Towers. Location-only generation automatically selects the Staffordshire Moorlands adapter and fetches official HTTPS PDF URLs from the recovered historical catalogue. Other locations retain their existing acquisition behavior.

## Recovered data

The original August 7 corpus contains 154 document entries across 44 applications: 153 PDF entries (141 distinct PDF hashes) and one non-PDF document. This is a historical subset, not complete/current discovery. The catalogue keeps application references, document titles, roles, states, official attachment URLs and original SHA-256 hashes. Original PDFs are not bundled in this repository.

For repeatable offline inspection of the previously downloaded corpus:

```bash
python -m voxel_mapper.alton --cache /path/to/planning-prefetch-selected --output alton-planning
```

The same cache may be supplied to world generation with `--planning-cache`. Without it, the adapter downloads the catalogue URLs automatically. Downloads require HTTPS on the official host, reject redirects, enforce a 10 MB budget and verify the recovered hash. Changed or missing documents are reported rather than silently substituted. Acquisition stops after a 15-minute planning budget and reports omitted entries. The existing world build area limit remains 4 km²; this is not a whole-resort coverage guarantee.

## Registration and extraction

The adapter inspects up to two pages per PDF for embedded geographic registration, native survey labels, grids, elevations and material evidence. Scale-only PDF viewports are not geographic registration. Existing plan/landscape/terrain sheets with full six-digit E/N labels also receive an automatic BNG alignment hypothesis. A bounded majority fit identifies shifted border-label origins, explicitly records exclusions and checks withheld labels. Ambiguous fits, insufficient controls and fits outside the requested area are rejected. Insets, rotated pages, raster-only registration and unlabelled drawing origins are not solved by this method.

The retained alignment includes PDF-to-coordinate axis coefficients, finite control extents, nominal residuals and a hypothesised WGS84 extent. It is not verified registration: label origins can differ from grid lines and EPSG:27700 is not independently established. No extrapolation or automatic promotion to world polygons is performed.

## Site validation correction

The recovered catalogue mixes park and nearby Farley Lane applications. The adapter now retains the original application context and selects only context identifying Alton Towers on Farley Lane. It excludes 31 other-site PDF entries, leaving 122 park-site entries. This conservative site filter is not independent spatial or as-built verification.

The previously reported native-label survey alignment belongs to Wildwood, a neighbouring property, and must not be described as Alton Towers survey registration. Its three references SMD/2022/0230, SMD/2021/0636 and SMD/2021/0211 are excluded from park acquisition. The old 148/153 inspection count was for the mixed corpus; it is not a park-only validation result.

## Actual plan boundary extraction

Install `pip install '.[planning]'` for the renderer-backed extractor (Actions installs it automatically). Selected actual site, landscape and floor-plan PDFs now recover exact closed straight-stroke networks in native page coordinates. PDF rotation is kept in the coordinate-space metadata rather than guessed. Curves, clipped/grouped/optional-layer paths, opacity and dashed boundaries are withheld. Polygon holes are preserved; no gap snapping or extrapolation is used. Document hashes and page numbers retain provenance.

The Project Horizon existing site plan (SHA-256 `0b50fd7cf84cd7c06d4e30992cc89fe857cf746494824d237c909bc48aaef432`, SMD/2022/0556) yields 276 closed boundary candidates. Visual inspection confirms extraction includes building outlines alongside tree symbols and other closed plan linework. These are not 276 verified buildings. No recognised contained material labels were found in these candidates, so no material specification was inferred.

Zero planning physical features entered a new world. Candidates remain unregistered, with unverified semantics and construction status. The older 722-feature authority export is still not accepted: some open LineStrings are report-text outlines, and approval/confidence flags do not establish physical semantics or as-built state. The next registration work must use the actual park survey (the Horizon drawing names On Centre Survey Drawing 2936 MASTER LAND SURVEY), independently checked park landmarks, or explicit geographic controls; the excluded Wildwood survey cannot register it.

## Full attachment discovery and missing master survey

The adapter now reads entire official application pages, including legacy `javascript:AppBlobImage(...)` attachment links. It recognises only literal numeric attachment IDs; it does not execute JavaScript or follow external attachment hosts. The 33 recovered park application URLs seed discovery. This is still not discovery of every application at every date.

Archived-page validation found 1,080 attachment links across all 33 park pages, including 122 links for SMD/2022/0556. The old recovered PDF catalogue is a much smaller downloaded subset. Newly found links are queued with surveys and actual plan sheets ahead of reports. Ecology/arboriculture surveys are not classified as topographical controls. Existing downloaded hashes are preserved; hashes of new live downloads are recorded as observations, not verification claims. Cache mode reports uncached discovered documents and processes only retained PDFs, without network downloads. Actions uses live pages and downloads newly discovered attachments within the shared 15-minute budget. Three consecutive application-page failures stop further live requests and retain the recovered catalogue fallback. Failures, omitted applications and download omissions are reported.

The referenced `2936 MASTER LAND SURVEY` is now tracked explicitly from printed source notes. No matching standalone topographical/master-survey title was found among the 1,080 archived park attachment links. This does not prove the survey is absent from embedded drawing content or the current portal. The attempted current official Horizon page request timed out; the web retrieval returned 502. No master survey was acquired and no new geographic registration was verified in this update.

## Expanded address search and paving corpus (8 October 2026)

The official address search was paged to its final result page: 328 matching
park records across 19 pages. This is completeness for that exact query at that
acquisition time, not completeness of council references, document dates or
as-built coverage. The search snapshot and original page hashes are retained in
`data/alton-application-search.json`.

A targeted sweep inspected 96 application pages and found 861 attachment links;
three older pages returned server errors. Pages containing attachments added 63
application seeds, bringing attachment discovery to 96 seeds. The acquisition
retains 60 PDF attachments (50 distinct files), including six already in the
historical catalogue. The PDF catalogue gains 54 entries, reaching 207. An
additional 44 targeted downloads failed, returned empty/non-PDF bodies, or were
unavailable. Legacy-image checks yielded no additional image files. Raw transport
URLs and observed hashes are retained; this sweep used the official legacy HTTP
endpoint where current HTTPS retrieval was unavailable. No HTTPS fallback or
registration verification is silently claimed.

| Area | Additional application data | Use / remaining work |
| --- | --- | --- |
| CBeebies | SMD/2013/1047, SMD/2013/1056, SMD/2016/0410, SMD/2018/0793 | Site/layout plans; native tarmac labels and a concrete-paver/herringbone specification; some paving recovers through shared survey labels |
| Gardens, White Bridge, bridge/dam and Towers surroundings | SMD/2013/0426, SMD/2013/0587, SMD/2013/1105 | Broad survey/site sheets expose additional ground paving; application decisions do not establish current construction |
| X-Sector | SMD/2026/0211 | Existing block paving and proposed reuse around Oblivion; requires independent registration |
| Forbidden Valley | SMD/2024/0064, SMD/2023/0515, SMD/2023/0516 | Revised queue/block-paving and visitor-building plans; landscape attachments partly unavailable; requires registration |
| Entrance/admissions | SMD/2009/1212 | Visually reviewed scanned site plans among generic “1” attachments; forms and elevations separated; no new registered entrance geometry |
| Katanga restaurant/walkway | SMD/2009/0125 | Two scanned plan booklets retained; other legacy endpoints unavailable; requires visual registration |

`data/alton-planning-supplement.json` records download results, bounded native
text inspection, material mentions and visual reviews of generic attachments.
A mention of brick, concrete or stone can refer to a wall or drainage structure;
these mentions are not automatically floor specifications. Generic numeric,
“Plans”, “Map” and “Drawings” titles remain unclassified until inspected. Actual
underscored site-plan titles, layouts and misspelled landscaping titles now
receive appropriate acquisition priority. Habitat/tree surveys and landscape
appraisals remain context, rather than coordinate surveys or paving drawings.

For future bounded public address discovery:

```bash
python -m voxel_mapper.alton_discovery --output /absolute/path/application-search --max-pages 40
```

Live discovery uses the official HTTPS endpoint and retains partial results on
failure. The new source package supplies hash-addressed `files/`; merge these
with the existing planning cache to inspect both corpora offline using the normal
paving commands. PDFs are not bundled in GitHub. Newly acquired source hashes are
observations, not geographic or present-day verification.

Paving extraction now rebuilds interrupted gzip caches atomically and excludes
faces crossing recognised scale-bar annotation regions. A visual review found a
3,521 m² triangle incorrectly closed by a scale bar in the Gardens block plan;
that face is withheld rather than painted as tarmac. The source overlay and
acquisition/extraction audit accompany the source package.
