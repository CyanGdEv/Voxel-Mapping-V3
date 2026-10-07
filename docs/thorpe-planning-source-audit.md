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
