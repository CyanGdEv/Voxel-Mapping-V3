# Thorpe planning source audit — 7 October 2026

This inspection did not generate physical planning polygons or change the
downloadable world. Document titles and internal grid consistency do not
establish geographic registration, construction status or reuse permission.

| Automatically discovered document | Inspection result | Missing evidence |
| --- | --- | --- |
| 11076CR Master Land Survey (20-5-2026).pdf | One-page scan. Six recovered crosses cover E503500–503550 and N168350–168450. National Grid/resection wording recovered by confident OCR. | Explicit CRS, usable height datum, independent alignment and full Dome coverage. |
| 472-110-3 Site Plan as Existing.pdf | One native-text page, printed 1:200. Visual inspection shows the beach/Depth Charge area, surfaces and surrounding detail; the Dome is cut off. No supported embedded registration. | Complete Dome geometry and verified geographic alignment. |
| Roof Plans as Proposed.pdf (RU.24/0310) | One native-text page identifying a service-building roof plan. No supported embedded registration. | Evidence that this depicts the Dome; geographic alignment and as-built status. |

The retained OSM Dome footprint, `osm/way/60047915`, has approximate BNG bounds
E503550.82–503606.65, N168367.93–168423.26. Under the unverified BNG hypothesis,
it lies outside the recovered control rectangle. Only one of 78 inspected OSM
building footprints lies wholly inside that rectangle. This is a coverage audit,
not a correspondence check or a surveyed accuracy measurement. Other park
buildings outside the rectangle are not evidence that their OSM mapping is wrong.

Council document references:

- Master survey: `3222663424A24C30A4A37FFEF65BE56E`
- Existing-site plan: `B58774B2F5DF460A8F2393169C875374`
- Service-building roof plan: `B33B9D13E5B44F159E5DD267DE472C7D`

Each reference was inspected through the normal public document endpoint:
`https://docs.runnymede.gov.uk/PublicAccess_Live/Document/ViewDocument?id=REFERENCE`.
Raw PDFs, preview images and raw extracted text are not included in this repository.
Current acquisition marks this council source consultation-only.

Next acquisition work must expand beyond these sheets to a full Dome survey or
historical drawing with sufficient alignment evidence. A generic roof-plan title
must not be counted as recovered Dome geometry. Neither spot surface heights nor
lake descriptive statistics supply spatial lakebed measurements.

## Historical Dome follow-up

The twelve-page address search found Dome proposal mentions in RU.13/0215 and
RU.12/0190, referring to RU.83/0514. The original permission returned no eligible
drawings through the public document adapter. The two 2012 plan downloads timed
out. Both 2013 plans downloaded successfully; their portal titles were opaque
`TowID` identifiers, so titles alone did not reveal their contents.

- `29BB4F9BD81011E2A0AD005056B45E6D`: one native-text/vector page, titled
  **1986 Boundary from RMC**. Visual inspection shows a wider park context and
  red boundary. Automated inspection rejects its decompressed page content
  because it exceeds the existing ten-megabyte page budget.
- `29BB4F9CD81011E2A0AD005056B45E6D`: one native-text/vector page, titled
  **The Dome: Access & Parking**, with a complete Dome plan outline, access
  bridge and parking layout. The key explicitly describes an application for
  extended opening hours. Its blue application extent and parking annotations
  are not verified physical building/plaza polygons. No supported embedded
  geographic registration, explicit EPSG or height datum was found. No 3D
  Dome structure, as-built status or geometry reuse permission was established.

Automatic inspection now gives opaque plans from named-building applications
priority and alternates those applications before consuming a second plan from
one application. The six-PDF inspection budget and consultation-only source
handling remain in force. This follow-up found a relevant complete plan outline;
it did not extract accepted physical polygons or change the world.

Native suffix-grid inspection subsequently recovered 19 easting labels (10
distinct values) and 38 northing labels (nine distinct values) from the Dome
access/parking sheet. Held-out label-spacing residuals were below 0.04 drawing
coordinate units. These are native text-origin consistency checks, not grid-line
intersections, geographic registration or independent metre accuracy. No controls
or transforms are exported. Empty native-text callbacks are ignored for the
text-fragment budget; all callbacks separately remain bounded to 200,000.

## Grid-intersection feasibility check

The native Dome access/parking page has 8,074,310 decompressed content bytes,
101,809 stroke operators and 4,022 cubic-curve operators, plus clipping. A bounded
diagnostic of transformed, single straight stroked paths found 15 axis-aligned
segments longer than 100 PDF points, all horizontal; it found no comparable
vertical segments. The displayed dotted grid therefore cannot be treated as a
set of full-length continuous straight lines by the existing intersection parser.
This diagnostic is not a complete rendering analysis and does not certify which
short strokes belong to the coordinate grid.

Recovering intersections from this sheet requires bounded reconstruction of
fragmented/dotted lines, with label attachment and ambiguity checks. Increasing
the existing straight-path limits alone would not support its curves, clipping or
grid representation. The source remains geographically unregistered and supplies
no accepted physical planning geometry. No independent-feature alignment check
has passed.

## Dotted-line reconstruction

A dedicated bounded inspection now reconstructs regular collinear short-stroke
runs. It ignores out-of-crop strokes, curves and fills, limits operators, stack,
segments and candidate counts, and splits on missing/irregular/overlapping dashes
instead of bridging them. This operates separately from physical polygon parsing.
The live Dome sheet produced 19 line hypotheses: nine vertical and ten horizontal.
Its clipping remains unverified. No label attachment, grid intersections, CRS,
independent accuracy or physical geometry was established by this step; only
inspection counts are exported. Automatic PDF inspection runs this check when
native suffix-grid labels have internally consistent spacing.

## Dotted-line label and intersection inspection

The Dome sheet associated ten distinct coordinate declarations to reconstructed
runs under a unique one-PDF-point proximity rule. The associations supplied 24
intersections inside both runs' extents; no ambiguous labels were accepted, and
29 label instances remained unattached. Maximum held-out residual was about
0.0354 drawing coordinate units. This is an attachment hypothesis and internal
consistency, not independent surveyed accuracy or a verified CRS. Conflicting
labels, ambiguous proximity, reversed/degenerate axes, excessive extent and
inconsistent fits are withheld. Only counts and diagnostics are exported.

## Named-label comparison with OSM

Automatic native named-label comparison under an explicitly reported BNG
hypothesis found labels inside three distinct OSM building footprints, including
the Dome. A fourth building's label was outside its footprint by about 0.82
hypothesised coordinate units. An additional Dome label outside the fitted control
hull was withheld. Duplicate labels do not supply independent checkpoints.
The OSM footprints were not used to fit the drawing grid. This is named-label
containment, not surveyed-corner verification: reference uncertainty and source
independence are unknown, and the CRS is unconfirmed. No registration flag is
promoted, no accepted planning polygons are created and the world is unchanged.
