# SW8 site and section source recovery

Retrieved **20 official attachments**, each a distinct single-page PDF, from links on the retained SMD/2016/0315 application page. The batch contains eight site/block plans and twelve section sheets: four existing sections, four original proposed sections and four revised proposed sections. The source receipt retains attachment labels, listed upload dates, URLs, byte hashes and retrieval outcomes. Original uploads are listed on 31/05/2016; the revised uploads on 02/08/2016. Neither upload nor approval establishes as-built status.

## Recovered constraints

| Source version | Building parameter | Printed value |
| --- | --- | ---: |
| Original proposed sections | Combined station/shop envelope | 192.2 m |
| Revised proposed sections | Separate shop top | 189.75 m |
| Revised proposed sections | Station building level | 188.7 m |
| Revised proposed sections | Maintenance building level | 190.3 m |

The combined envelope is deliberately a different claim type from the separate shop height. It must not be applied to the later shop model. Revised section notes describe reductions in plan and section on 28.7.16.

Other extracted candidates include the 201 m HP1 parameter, 191.4 m HP3 parameter, 179 m ride low point, and sound-tunnel limits. These are section parameters with native word boxes; they do not supply a complete 3D centreline, support positions or verified ODN levels. The section level marks at 175/180 m also do not establish a vertical datum.

Material text candidates cover dark timber for ride structures, tunnels and screens; thatch/profiled metal for roofs; timber boarding for walls; and forest thinnings for thematic structures. These remain proposed descriptions requiring feature-specific review and Minecraft palette mapping.

## Visibility and plane handling

All twelve section pages are marked ineligible for horizontal geometry matching. A vertical drawing cannot become an XY footprint merely because its vectors form polygons.

Eight proposed section PDFs contain overlapping “Existing” and “Proposed” title text at the same native position. Visual inspection of revised CC/DD attachment 163932 shows the proposed section and revised shop/station values; plain PDF text extraction also recovers the earlier title underneath. The review detects and flags those incompatible markers. Every extracted level remains an unreviewed text claim; source visibility, physical identity and vertical datum are explicitly unverified. A title match alone cannot certify the visible drawing state.

Site-plan X/Y annotations are retained as untyped labels, not national-grid controls. No verified horizontal registration or vertical datum was established by this batch. Accepted controls: 0; checkpoints: 0; world geometry additions: 0.

## Reproduce

```sh
python scripts/acquire_wicker_site_sections.py \
  --application-page ../outputs/wicker-shop-source-search/sw8-application.html \
  --output work/wicker-site-sections
python scripts/review_wicker_site_sections.py \
  --receipt work/wicker-site-sections/download-receipt.json \
  --directory work/wicker-site-sections \
  --output work/wicker-site-section-review.json
python -m unittest tests.test_wicker_site_section_acquisition \
  tests.test_wicker_site_section_review tests.test_survey_reference tests.test_raster_location
```

Acquisition uses four concurrent requests and a 20 MB / 100-page document budget. Every requested attachment must occur on the hash-pinned application page. Unexpected redirects, non-PDF responses and corrupt existing content-addressed blobs are rejected. Fresh downloads may have different bytes; the historical receipt remains the reference for this review.

The review verifies PDF hashes and page counts, preserves native annotation boxes and deterministically replays. All 22 focused tests passed. Next, review visible physical boundaries in the revised site plan against independent survey evidence; these additional section constraints can then be used without mixing old building envelopes or section geometry into map placement.
