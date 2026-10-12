# Automatic survey-source discovery and acquisition priorities

The source-discovery stage investigates where usable geographic evidence might exist. It does not release controls, infer a CRS from National Grid wording, verify coordinate attachment, or accept a frame.

It scans checksum-bound original PDFs using bounded native text and retains page observations in `survey_source_pages`. Recognized investigation signals include explicit EPSG declarations, station/coordinate-table headings, measured/topographical/control survey wording and references such as `Survey Drawing 2936 MASTER LAND SURVEY`. Arbitrary/local-grid restrictions and reference notes remain visible. OCR, glyph visibility and physical coordinate attachment are separate stages; an empty native-text result cannot establish that a raster page lacks survey evidence.

Cited drawing numbers are matched exactly against existing catalogue drawing-number fields and complete title tokens. Multiple revisions remain ambiguous candidates. Missing references retain their source SHA, page and search terms with no invented attachment URL. Ecological or arboricultural survey wording alone does not become a topographical source. Application-form Easting/Northing labels alone score below the acquisition threshold and cannot become controls.

Known attachment titles and retained source-page signals are ranked deterministically. At most 128 distinct canonical URLs are passed to `Corpus.acquire(priority_urls=...)`; unknown or duplicate priorities are rejected. Priority selection respects the existing attempts, worker, document and byte budgets. It does not bypass source transport/hash rules, redirects, the offline setting or failed-request limits. Existing downloaded sources are not requested again. The stage does not probe arbitrary URLs, run a web search automatically, or refresh council application pages itself; full attachment discovery remains `planning_bulk discover-alton`.

Native observations reuse unchanged source SHA/page/parser contracts. Catalogue growth recomputes associations against the new titles without re-reading unchanged PDF pages. Source byte changes fail checksum checks before stale observations can be published.

## Area cycles

The area runner enables survey-source discovery by default. Before acquisition it ranks existing metadata and retained pages; after acquisition it updates the queue from newly available PDFs. The usual landmark discovery and independent frame qualification still follow geometry extraction.

```json
{
  "survey_source_discovery": {
    "enabled": true,
    "max_pages": 1000,
    "max_priorities": 128
  },
  "max_acquisition_documents": 16
}
```

`max_acquisition_documents` limits new attempts per run (default 10,000); retained sources still undergo their normal checksum checks. The output `survey-source-discovery/survey-source-queue.json` is included in the area's result. Disabling this stage restores ordinary acquisition ordering. It can also operate on a park-wide corpus to investigate references across area catalogues:

```bash
python -m voxel_mapper.survey_source_discovery \
  --corpus /absolute/path/park-corpus --output /absolute/path/source-search \
  --max-pages 1000
```

## Retained Mutiny trial

The 73-PDF / 213-page native-text trial completes without errors and reuses all 213 observations in a fresh output directory. Its only coordinate signals are the two application-form location hints. There are no qualifying survey-source candidates, missing cited survey drawings or acquisition priorities in this retained area catalogue. Zero controls, checkpoints or geographic frames are accepted. This does not establish absence from other park applications, raster pages or the current live portal.

The receipt is `docs/evidence/mutiny-survey-source-discovery-validation.json`. Fixture tests cover missing references, ambiguous revisions, exact drawing-number matching, catalogue growth, limited page scans, source changes, persistent replay and priority acquisition within a one-document limit. The next geographic step still requires acquiring and verifying actual park survey/control evidence.
