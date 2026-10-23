# Source captions independent of artwork crops

The roof-reference lookup previously reported two missing targets for
`2967/42/9` and `2967/42/12`. The original maintenance-building PDF contains
both captions. Its current automatic artwork layout only exposes elevation 11
as a measurement target. Repeating a source download cannot fix that layout
failure.

The new caption inventory separates finding a printed source label from finding
a usable artwork crop. It screens the original caption and sheet-header glyphs,
joins exact project/sheet/view keys, and retains all duplicate witnesses as
competing candidates. A missing scale or artwork crop does not erase a visible
caption. Caption visibility or sheet-identity failures still prevent a key.
The source label is never promoted into a measurement or physical component.

The real-source run covers five checksum-pinned PDFs: shop elevations 26,
preshow elevations 30, maintenance plans/elevations 42, basement plan 22 and
roof plan 48. It retains 12 numbered elevation captions and freshly replays the
13 original roof markers. Results:

| Lookup | Result |
| --- | ---: |
| Exact caption links | 8 |
| Missing source captions | 0 |
| Competing caption links | 0 |
| Original reference visibility/identity holds | 5 |
| New caption links whose original measurement lookup remains missing | 2 |

Each link retains the prior measurement status and a next requirement. The two
new links require artwork assignment and scale. Existing measurement targets
still require physical correspondence and dimensions. Held original references
require their own visibility/identity evidence. No nearest caption, related
project, inferred bearing or numeric roof pitch is substituted.

The existing source-reference evidence, fascia meshes and all five marker holds
remain unchanged. The fascia evidence SHA-256 remains
`8f5af50fa495231b562de2ba98639f59c880833605ed3f38075206c092054466`.
This increment generates no geometry, shared-cap closure, accepted physical
component, world blocks or training labels.

## Additional original sources recovered

Seven known attachments were reacquired and verified against their historical
SHA-256 checksums: the revised site plan, all four revised site-section sheets,
maintenance sheet 42 and basement sheet 22. The application page also matches
its retained checksum and contains 89 observed attachment links. Two initial
section downloads timed out; both succeeded on a later attempt. The recovery
receipt retains those failures rather than rewriting the first observation.

Drawing 42 explicitly describes the maintenance building. It cannot supply a
preshow section merely because a roof marker points to it. The site sections
contain broad building/landscape constraints and overlapping extracted title
text. Existing visibility and physical-identity limitations apply. Four native
word witnesses for `191.5` are retained in three section sheets, including two
in CC/DD. They remain unassigned source text; numerical agreement with a roof
candidate does not establish its identity, datum or shared-cap geometry.

The next roof-interface work is to bind visible features and leader lines in
the revised sections to the same preshow component, then test whether the
shared-cap fascia/wall boundary is actually supported. Caption coverage alone
does not resolve that interface. The maintenance-layout failure is separately
identified and can be fixed without changing preshow measurements.

## Reproduce and inspect

The original PDFs must be placed in a source directory as `<sha256>.pdf` using
the literal URLs in the catalogue and recovery receipt. The reference JSON is
the unchanged output of the preceding source-reference pass.

```sh
python -m scripts.build_drawing_caption_coverage \
  --references ../roof-reference-evidence.json \
  --source-catalogue examples/wicker-caption-source-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --output ../wicker-caption-validation

python -m scripts.audit_drawing_caption_coverage \
  --evidence ../wicker-caption-validation/<contract-hash> \
  --references ../roof-reference-evidence.json \
  --source-catalogue examples/wicker-caption-source-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --output ../wicker-caption-validation/audit.json

python -m scripts.render_drawing_caption_coverage \
  --evidence ../wicker-caption-validation/<contract-hash> \
  --source-catalogue examples/wicker-caption-source-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --section-review docs/evidence/source-caption-coverage/section-inspection.json \
  --output ../drawing-source-coverage-review.html
```

The standalone review includes ten original full-sheet images, the 13 lookup
rows, all caption dispositions, section text limitations and an exact-byte JSON
download. The independent audit replays original markers and checks all 12
native caption/header witnesses and all 13 exact-key joins. Fifteen focused
tests cover real overpainting, failed caption/header screens, conflicting
headers, rotations, absent crops/scales, competing keys, work exhaustion,
source/cache tampering and changed inputs during processing.

Source size, page, caption and work limits are fixed. Budget failure clears all
partial page/link results. Inputs are rehashed after processing and retained
outputs must match fresh replay. Receipts are in
[`docs/evidence/source-caption-coverage`](evidence/source-caption-coverage).
