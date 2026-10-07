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
