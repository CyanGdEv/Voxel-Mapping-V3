# Retained source matching and benchmark corroboration

Architectural area runs automatically search their acquired PDFs after preparing
the reconstruction requirement queue. The area report and sweep expose
`retained_evidence_matching`. This stage records source leads; it never resolves
a requirement by keyword, accepts a source view, sets a building height or
registers a component.

The search covers floor/site/roof views, sections, elevations, opening references,
eaves/ridge/floor labels, survey/control terms and datum/benchmark terms. Each
hit retains its original PDF hash, page, native-text hash, character offsets,
exact matched text and a bounded context excerpt. All hits survive within the
budgets; no highest-scoring source or nearest object is selected. Existing and
proposed claims on the same page remain explicit. Metadata links retain their
application and declared state; shared application membership does not establish
physical area membership or common project/object identity.

Application address eastings/northings are location context, not surveyed
controls. FFL or an unspecified datum is level context, not an absolute datum.
Tasks distinguish `candidate_sources_found`, `related_text_only` and
`no_retained_text_lead`; none becomes resolved. Missing text evidence does not
prove a raster drawing lacks dimensions. Unavailable document titles are kept
as discovery leads alongside their download status.

The default bounds are 1,000 unique PDFs, 10,000 pages, 20,000 text hits and
100,000 task/hit associations, with 500,000 native text characters per page.
A late page/hit/association budget removes all partial hits and task assignments.
PDF hashes are checked before and after search. The queue, document-link
inventory, unavailable links, glyph-screen versions and matcher versions form
the attempt contract. Unchanged attempts validate and reuse their output with
zero newly searched pages. A changed inventory creates a new content-addressed
attempt and preserves the old one. Edited source PDFs, queue or matching outputs
reject. An unfinished attempt does not masquerade as a complete search.

## Printed benchmark evidence

The matcher recognises both `OSBM` and dotted `O.S.B.M.`. An additional native
review retains exact original marker and parenthesised `(value ... m/mm)` labels,
reading direction, native geometry, trace/character indices and original-font
glyph screens. Only nearby, parallel-reading label boxes with overlapping
horizontal extents can create layout candidates. All competing values remain;
none is selected as nearest. This is label-layout evidence, not the physical
survey symbol or benchmark coordinate. Hidden markers and values cannot support
one visible value candidate. Exhausted comparison budgets discard all partial
marker/value records. Rotation is preserved.

Optional OS archive matching reads a checksum-pinned original CSV, retains
original rows and National Grid reference resolution, and compares visible
printed values with archive heights using the literal printed rounding interval.
All matching rows remain; a unique height candidate is still not verified
physical benchmark identity. Search bounds are a discovery domain, not an area
boundary. Old marks and coarse references cannot satisfy one-metre registration.
The official archive is published under the Open Government Licence; OS warns
that the historic network is no longer maintained and low-order heights cannot
be relied on to accurately define ODN:
https://www.ordnancesurvey.co.uk/geodesy-positioning/legacy-data/benchmark-search

Area configuration for a previously acquired archive CSV:

```json
{
  "evidence_matching": {
    "benchmark_archive": {
      "file": "inputs/CompleteBenchMarkArchive.csv",
      "sha256": "SHA256_OF_ORIGINAL_CSV",
      "search_bounds_bng": [405345, 341810, 409345, 345810]
    }
  }
}
```

This optional input is part of the matching attempt contract. The adapter does
not silently download, replace or certify an archive. The area-controller
version is now v3; retain previous native worlds as baselines in a fresh controller
work directory when upgrading earlier runs. No production Alton source bundle,
accepted controls or datum is created by enabling this configuration.

## Actual Mutiny replay

All 73 retained PDFs and 213 pages yield **484 native text leads**: 130 view-scope,
109 exterior, 191 correspondence, 33 relative-dimension, 11 registration and ten
vertical-datum leads. Ten targeted floor-plan requirements have retained text
leads. This is a candidate count, not 484 objects or resolved constraints.

Five source pages contain benchmark marker labels. Only the existing 3023-08
floor plan supplies one visibly supported marker/value layout pair for
`O.S.B.M.` and `(value 178.90m)`. The four other marker copies fail the original-font
screen. The source label position is not a surveyed control position.

The downloaded official archive ZIP has SHA256
`5528b3efe9b37a522dab3cd8145e246e5bcb054cf1b007015989b431f5d24488`;
the decompressed original CSV has SHA256
`57d480bd272778e8b89ffd4a50f520442b8912e4b2cd6746202c2e991e910f7b`.
The ZIP uses Deflate64; system `unzip` can decode it. The CSV has 517,201 rows.
A discovery box around the retained application address selects 51 historical
records. One has a height consistent with the visible 178.90 m label:
SK 0744 4354, archive height 178.9000, datum code N, description
`BLDG NE SIDE RD SW FACE W ANG`, verified/levelled 1961, height above ground 0.7 m.
The four-digit east/north fields have ten-metre reference resolution, not
established ten-metre or one-metre positional accuracy.

At that coarse grid reference the retained DTM pixel is 176.21 m; its surrounding
10 m search window spans 175.92–178.982 m. These observations remain terrain
context, not a selected terrain alignment or proof of benchmark identity/datum.
The whole candidate row, archive/source hashes and terrain statistics are in
`evidence/mutiny-os-benchmark-corroboration-audit.json`.

The real matcher/queue runner searched all 213 pages on its first invocation and
zero pages on an unchanged replay, retaining the same 484 hits and ten source-lead
task results. The optional archive review was part of the hashed attempt. Its
report is retained in `evidence/mutiny-matching-pipeline-replay-audit.json`.
This used the targeted floor-plan queue, not a full-area physical inventory.

All 19 unavailable council links were retried once in an isolated corpus. Every
request returned HTTP 502, downloading zero new bytes. Their URLs, errors and
attempt counts are retained in `evidence/mutiny-source-retry-audit.json`. This
records the attempt from this environment, not a claim of permanent unavailability.

Reproduce the native search:

```sh
PYTHONPATH=. python scripts/audit_mutiny_retained_evidence.py \
  --input-root INPUT_ROOT/mutiny-bay-sources \
  --catalogue SELECTED_CATALOGUE.json \
  --output evidence/mutiny-retained-evidence-matching-audit.json
```

Reproduce archive corroboration with the downloaded original CSV:

```sh
PYTHONPATH=. python scripts/audit_mutiny_benchmark_archive.py \
  --archive CompleteBenchMarkArchive.csv \
  --output evidence/mutiny-os-benchmark-corroboration-audit.json \
  --terrain alton-terrain-mosaic.tif
```

The remaining work is to identify the actual drawn/physical benchmark, check its
survival and datum against independent current evidence, separate source views,
and bind building exteriors/dimensions. No Mutiny geometry or absolute heights
are promoted by these searches and corroboration candidates.
