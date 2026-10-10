# Wicker Man survey-reference recovery

A checksum-verified text pass over the retained archive checked **237 distinct PDFs / 602 pages**, including **11 Wicker Man application documents**. It found a station-coordinate survey in the archive, but that survey covers Wildwood on Farley Lane. Its printed grid labels span 406860–406980 E and 342800–342900 N, outside the shop test area.

More decisively, this survey's notes explicitly disclaim true OS coordinates. It was oriented using GNSS and OSTN15/OSGM15, but its coordinates remain an arbitrary site grid without scale-factor adjustment. Those references do not make the station table a ready EPSG:27700 registration source. The retained PDF is `82cac12a14cd3d9d4232f409e681bd977f6c7f4f03be7b9049a6f845375543a9` and is shared by three application records; it was scanned once.

The Wicker woodland-path statement contains the numeric location reference 407628, 343522. That identifies application context, not a surveyed physical correspondence point. No controls or checkpoints are accepted from it.

## Parser change

Survey-note inspection now distinguishes a national-grid **orientation claim** from an explicit **arbitrary-coordinate warning**. The location checker returns `local_grid_requires_transform` before trying geographic overlap whenever that warning is present. An EPSG label or plausible coordinate magnitude cannot override it. Existing unverified EPSG and datum candidates retain their previous treatment.

## Reproduction and limits

```sh
python scripts/audit_wicker_survey_references.py \
  --archive ../inputs/attachment-recovery/Alton_Towers_Expanded_Planning_Data_V4.zip \
  --output evidence/wicker-survey-reference-search.json
python -m unittest tests.test_survey_reference tests.test_raster_location tests.test_drawing_ocr tests.test_alton_discovery
```

The script verifies each PDF against its catalogue checksum and deduplicates by content hash. The receipt retains source URLs, application identities, page-text hashes, printed coordinate labels and note findings. Archive, page and text budgets stop oversized searches.

This is searchable PDF text, not an OCR inspection of every raster drawing. No-hit pages do not prove absence of coordinates. The archive is an incomplete public attachment subset. All 30 focused tests passed; the search deterministically replayed.

Placement remains withheld: 0 controls, 0 checkpoints, 0 world geometry additions. Next, acquire and inspect the missing detailed SW8 site/section attachments for a stated survey base and identifiable physical points. A usable local grid would require a documented conversion and independent alignment checks before placement.
