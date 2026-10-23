# Compound-roof correspondence to the original site plan

The architectural roof now has a conditional correspondence to a roof drawn
on the original revised site plan. Both four-corner roof shapes and the whole
adjoining ridge agree at their original nominal scales. One rotation and one
reflection survive. This advances alignment to the park drawing, while physical
identity, section cut direction, geographic placement and wall closure remain
unresolved.

## Source extraction

The source is attachment 163929, drawing `373/95/7A`, with SHA-256
`3a8a18eb3959a39e7559309046b0815469b9f9baa52a5d1364a0cc4aa2cbb279`.
The catalogue preserves its original URL and nominal 1/250 scale. Printed scale
words and both exact `Station` word witnesses are retained. Each word must
pass the existing original-font glyph screen before it can define a source
search region. The original architectural roof, adjoining ridge, source section
cameras and all preceding holds are freshly replayed against their original
pinned inputs.

Regions extend 350 original PDF points around each supported word. Every
eligible whole straight primitive edge in those regions is inventoried before
registration. A nearby label supplies context only; it does not identify the
physical role of the small roof. In particular, the Station label is not inside
the detected pyramid, so proximity must not reclassify it as the ride station.

The extractor accepts opaque solid strokes, including stroked filled paths.
It supports original straight `l` items and explicit perimeter edges of `qu`
and `re` primitives. MuPDF's quad order is upper-left, upper-right, lower-left,
lower-right; the perimeter is therefore 0→1→3→2→0. No diagonal, implicit closing
stroke, clipped line, snapped point or curve approximation is invented. All
original primitive/item/edge indices, path digests, paint order, colours and
coordinates survive. Duplicate paints retain separate identities.

The literal four-spoke topology recipe then runs on the complete source-only
inventory. It finds one closed roof graph. The two source neighbourhoods also
retain unrelated lines; source windows and 1–40 nominal metre line bounds are
diagnostic limits, not a claim of exhaustive site-wide roof recognition.

## Registration and results

For every architectural/site roof pair, all four starting corners and both
orders are tested. The original apex pair anchors translation. One original
edge direction proposes an orthogonal rotation or reflection. The original
plan scales fix the scale ratio; there is no fitted scale, averaged anchor,
least-squares translation or residual-ranked selection.

Every original corner and both whole adjoining-ridge endpoints must agree
within 0.1 nominal metres. Both original endpoint orders are retained for each
site line, including failures. A source line cannot supply a subinterval or an
extension. Compatible roof edges and ridge lines additionally need original RGB
sample support. Each roof edge needs at least one passing original paint;
failed duplicate paints, if present, remain in the evidence.

| Original-source result | Count |
| --- | ---: |
| Source context words | 2 |
| Original straight site edges | 798 |
| Original closed four-spoke roof candidates | 1 |
| Original whole-edge pixel checks | 18 |
| Registration alternatives retained | 8 |
| Supported compound registrations | 2 |
| Whole ridge endpoint-order comparisons | 12,768 |
| Conditional section-camera/site-registration combinations | 8 |

The supported alternatives have maximum corner errors of approximately 2.29 cm
and 2.70 cm. Their whole ridge endpoint error is approximately 2.46 cm. Both
match two separately retained original ridge paints. All 18 original edge pixel
checks pass. One supported registration is reflected; the other is a rotation.
The six alternatives without compound support remain reviewable.

Each supported registration is combined with the four preceding section-camera
hypotheses that passed the whole adjoining-ridge check. This produces eight
conditional camera combinations in the site's native PDF axes. These are not
geographic bearings. No original section camera or previous source hold is
deleted, no new roof or wall mesh is made, and no accepted physical component,
world block or training label is produced.

## Reproduce and inspect

```sh
python -m scripts.build_site_roof_evidence \
  --adjoining-evidence ../section-adjoining-evidence.json \
  --projection-evidence ../section-projection-evidence.json \
  --section-evidence ../section-roof-evidence.json \
  --pyramid-evidence ../pyramidal-roof-evidence.json \
  --reference-evidence ../roof-reference-evidence.json \
  --section-catalogue examples/wicker-section-roof-catalogue.json \
  --site-catalogue examples/wicker-site-roof-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --fascia-evidence ../pyramid-fascia-evidence.json \
  --roof-plan-pdf ../wicker-interface-originals/6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047.pdf \
  --output ../wicker-site-roof-validation
```

`scripts.audit_site_roof_evidence` accepts the same inputs, `--evidence
<result-directory>`, and its own `--output <audit.json>`. It freshly replays the
complete pass, then checks original primitive edges, source words and RGB
windows independently. Native coordinates are checked with independent y-up
arithmetic using MuPDF's original float32 point representation. Rotations and
reflections are independently reconstructed using angles; every corner, ridge
endpoint order, support gate and section-camera transform is checked.

```sh
python -m scripts.render_site_roof_evidence \
  --evidence ../wicker-site-roof-validation/<contract-hash> \
  --pyramid-evidence ../pyramidal-roof-evidence.json \
  --adjoining-evidence ../section-adjoining-evidence.json \
  --source-directory ../wicker-interface-originals \
  --roof-plan-pdf ../wicker-interface-originals/6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047.pdf \
  --output ../site-roof-review.html
```

The standalone HTML contains original full sheets and detail crops, unchanged
original edges, projected compound roofs, both supported handednesses, held
registrations, conditional section cameras and exact JSON export. No original
PDF is redistributed in the review pack. The exact report is retained as gzip
under `docs/evidence/site-roof-correspondence/`.

Validation includes 82 targeted tests: 20 new correspondence tests, 19 adjoining
ridge tests, 20 section projection tests, 17 section-source tests and six plan
topology tests. The complete base CI run passed; the complete new suite runs
separately in GitHub CI. Actual-source build/audit do not mock parent replay.
Small persistence unit fixtures explicitly mock only that expensive parent.
Source work is capped at 200,000 checks, separately from the unchanged parent
limits. The original run uses 147,039 checks. Early or late exhaustion clears
all partial source, registration and camera fields. Inputs are rehashed after
processing, and any changed cache is rejected.
