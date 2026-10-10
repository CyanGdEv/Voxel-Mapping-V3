# Recovered revised shop architectural sheets

The retained expanded planning archive contained 237 checksum-matching PDFs.
A native-text search found four shop/SW8 references, all site or block plans;
that search alone was not a complete visual-content search. The official cached
application page for SMD/2016/0315 supplied the missing architectural attachment
links. Six PDFs were successfully retrieved from those observed official links,
including three revised separate-building sheets and their earlier counterparts.

| Drawing | Attachment | Scope in this review |
| --- | ---: | --- |
| 2967-26 | 163937 | Dedicated shop elevations; four directional views |
| 2967-21 | 163935 | Revised overall floor plan, printed P1 |
| 2967-48 | 163940 | Revised overall roof plan, printed P1 |
| 2967-06 | 160154 | Earlier combined-building elevations; historical only |
| 2967-13 | 160157 | Earlier combined-building floor plan; historical only |
| 2967-14 | 160158 | Earlier combined-building roof plan; historical only |

The three revised attachments are listed with upload date 02/08/2016. The roof
and floor sheets print revision P1; the dedicated elevation sheet's attachment
label mentions P1 but its native text does not reproduce a printed P1 revision.
This distinction remains recorded rather than silently assuming identical status.
The official application page reports approval dated 31/08/2016. Application
approval and attachment association are not proof of an approved as-built survey
or an independently checked wall corner. The final condition-specific approved
sheet schedule is not claimed to have been verified from a decision notice.

## Newly available planning information

The revised floor plan gives a shop floor level of 182.50 m and a gross internal
area of 170 m². The area is not an external-wall footprint or roof area. The
printed level's relationship to ODN has not been independently verified. The
floor plan explicitly treats internal arrangement as illustrative, so partitions,
door layouts and internal geometry cannot be promoted to as-built detail.

The dedicated elevation sheet describes a simulated-thatch tile roof, weathered
horizontal timber above, and landscape or sandstone-style bunding below. These
are proposed appearance hints, not verified current materials or Minecraft block
assignments. The four directional elevation views and revised roof plan now
provide actual source context for examining roof/wall boundaries and entrances.

The earlier combined-building elevation's 192.20 m ridge annotation must not be
reused as a verified ridge height for the later separate shop. It belongs to a
different design scope. None of the six sheets supplies a newly accepted
independent horizontal checkpoint in this pass.

## Pipeline integration and limits

`scripts/ingest_wicker_shop_drawings.py` verifies every revised PDF checksum and
native drawing number before extraction. It produces 5,381 unplaced plan
candidates and 243 elevation candidates. These are drawing components/faces,
not 5,624 identified physical features. Elevations are kept in a separate stream
and must not be fed into horizontal XY matching as if they were plan views.
The earlier combined-building sheets are excluded from the active review streams.

All three revised sheets have native 90-degree page rotation. Native coordinates
are retained through the existing extractor rather than copied from display crops.
Scale and image-placement metadata are recorded separately. The elevation title
block uses an indicated scale with per-view scale labels; no global paper-scale
denominator is invented when `page_scale` cannot establish one.

The extractor still rejects 14 clipping/compositing scopes on the elevation
sheet, 66 on the floor plan, and 13 on the roof plan. The imagery and these
rejected scopes matter: the extracted records are not complete building outlines.
No gap filling, hatch-face union interpreted as a wall, or raster-to-vector
substitution is used to manufacture a supposedly exact overhang. Roof-to-wall
offset and physical roof-edge uncertainty remain unset. The next implementation
target is to inspect the relevant shop view/clip content and extract its visible
roof and wall boundaries with an explicit sampling/error basis, then compare them
with the dated LiDAR. Independent georeferenced checkpoints remain necessary.

## Replay

Source URLs, observed transport status, bytes, checksums, revision scope and
proposed attributes are in `evidence/wicker-shop-drawing-sources.json`. Download
the three revised PDFs using those URLs and save each as `<sha256>.pdf`.

```sh
python scripts/ingest_wicker_shop_drawings.py \
  --sources evidence/wicker-shop-drawing-sources.json \
  --pdf-directory shop-pdfs --output fresh-shop-ingestion
```

Outputs are `plan-candidates.jsonl`, `elevation-candidates.jsonl` and
`ingestion-report.json`. The report and both streams replay byte-for-byte.
The retained report is `evidence/wicker-shop-source-ingestion.json`; validation
is `evidence/wicker-shop-source-validation.json`. Zero controls/checkpoints or
world geometry additions are accepted.
