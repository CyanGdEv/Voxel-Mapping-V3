# Whole adjoining ridge and conditional shared-cap visibility

The section widths alone leave eight camera orientations per complete view.
This pass adds the original adjoining plan ridge as a second feature. In AA
and CC, its two projected endpoints match a whole lower roof stroke. Each view
then has two conditionally supported orientations, both showing the shared cap.
The reflection and physical building correspondence remain unresolved.

The GG view supplies no matching whole ridge in the checked source region. Its
eight parent cameras remain available. A missing match does not establish that
a camera is wrong: an adjoining roof can be obscured or represented differently.
The incomplete second CC/DD roof and the sheet without a requested numeric
source group retain their earlier holds.

## Evidence and recipe

The builder freshly replays the complete parent section projection pass. It
checks the source-reference report against the pyramid report's existing hash,
requires identical original plan lines, and replays the original shared-cap
junction. The adjoining ridge, both whole rails and shared cap also need exact
straight-item witnesses in the original roof-plan PDF. The existing rail tails
remain whole. Original PDFs and parent evidence are not modified.

Horizontal solid opaque source strokes are extracted before endpoint testing,
using fixed neighbourhoods defined by each original complete section base:
250 PDF points beyond each end and 80 points below it. Whole horizontal items
must be 12–250 points long and entirely inside that region. All such items are
retained with original path/item indices, coordinates, paint sequence, style
and path digest. Source windows and line bounds are diagnostic limits; absence
outside those bounds is not evidence of absence from the complete sheet.

For each unchanged parent camera, the original apex anchors the horizontal
projection of **both** original plan ridge endpoints:

```text
section_x = source_apex_x
          + dot(plan_ridge_endpoint - plan_apex, parent_unit_horizontal_camera)
            * original_plan_scale / original_section_scale
```

Both endpoint stations must agree with one whole original source line within
0.5 PDF points. There is no fitted translation, scale, height, trimmed source
line or residual-ranked choice. Every camera/line comparison survives in the
report. Geometrically compatible lines also undergo 31 original RGB
neighbourhood checks; failed source-colour support cannot support a camera.
Those samples are recorded diagnostics, not proof of complete visibility.

The face gate is explicitly **conditional on the same adjoining roof being
shown under the parent orthographic model**. It keeps the full parent report
intact. A consistent shared-cap visibility outcome does not establish physical
identity, cut direction, geographic bearing, vertical datum or a join surface.
No wall, fascia closure, accepted building, world geometry or training label is
authorized by this check. The earlier open vertical join remains unresolved.

The original-source run records four native plan witnesses, 642 whole section
strokes, 5,136 endpoint comparisons and two pixel-supported matching strokes.
The maximum supported endpoint residual is 0.055768 PDF points. Four camera
hypotheses pass this added check: two in AA and two in CC. All four show the
shared cap under the conditional model. The run uses 815,667 of its 2,000,000
checks. The exact report is retained as a reproducible gzip file under
`docs/evidence/section-adjoining-ridges/`; decompress it to inspect the JSON.

## Reproduce and inspect

Use the unchanged exported reports and checksum-pinned original PDFs from the
preceding passes. `roof-reference-evidence.json` is the report whose hash is
already stored in the pyramid contract, not a newly estimated plan model.

```sh
python -m scripts.build_section_adjoining_evidence \
  --projection-evidence ../section-projection-evidence.json \
  --section-evidence ../section-roof-evidence.json \
  --pyramid-evidence ../pyramidal-roof-evidence.json \
  --reference-evidence ../roof-reference-evidence.json \
  --section-catalogue examples/wicker-section-roof-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --fascia-evidence ../pyramid-fascia-evidence.json \
  --roof-plan-pdf ../wicker-interface-originals/6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047.pdf \
  --output ../wicker-adjoining-validation
```

`scripts.audit_section_adjoining_evidence` accepts those inputs, plus
`--evidence <result-directory>` and its own `--output <audit.json>`. It repeats
the fresh build and independently checks native plan conversion, original
section items and sampled RGB windows, projected ridge endpoints, every
comparison and the conditional face gates.

```sh
python -m scripts.render_section_adjoining_evidence \
  --evidence ../wicker-adjoining-validation/<contract-hash> \
  --projection-evidence ../section-projection-evidence.json \
  --section-evidence ../section-roof-evidence.json \
  --pyramid-evidence ../pyramidal-roof-evidence.json \
  --source-directory ../wicker-interface-originals \
  --output ../section-adjoining-review.html
```

The standalone review retains all 24 cameras, original full sheets/crops, all
retained horizontal-stroke choices and exact JSON export. It draws the original
adjoining ridge in the native plan. The projected ridge is displayed at the
selected original stroke's height **only to compare horizontal stations**;
that display does not infer a vertical ridge level. Changing selections cannot
change the report or authorize geometry.

Validation includes 62 targeted tests: 19 new adjoining-ridge tests, 20 parent
projection tests, 17 section-source tests and six original plan-topology tests.
The prior complete CI run passed. The new complete suite runs in GitHub CI.
The local source build and independent audit use actual original PDFs without
mocking. Small unit persistence fixtures explicitly mock only the expensive
parent replay. Early or late work-budget exhaustion clears every partial
source/projection field. Parent replay retains its separate original limits.
