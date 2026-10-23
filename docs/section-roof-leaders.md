# Original section leaders and roof height diagnostics

The recovered revised sections contain four exact `191.5` words across three
sheets. This pass links those words to their original arrow leaders and roof
strokes, retaining both complete and incomplete outline alternatives. It adds
source evidence for the existing preshow roof hypothesis; physical building
identity, section bearing and shared-cap geometry remain unresolved.

## Original coloured text

Each word is split into two native text runs (`191` and `.5`) with slightly
different printed font sizes. The original brown text is outside the existing
black-text visibility recipe. That recipe and all earlier holds are unchanged.

A complementary RGB screen copies the original PDF font resources into a
temporary inspection page and replays the original Identity-H CID identifiers,
origins, sizes and colour. It requires the embedded CID CFF font and validates
its CID charset and font matrix. It never re-encodes the text as Unicode or
substitutes another font. Both original text runs are retained.

The screen renders the unchanged source and reference at six pixels per PDF
point. Reference core pixels must be within eight RGB levels of the original
paint colour; source support uses 16 levels and one pixel of position tolerance.
Every non-space glyph needs at least three core pixels and at most 1% missing
support. An outer ring permits at most 1% unexpected matching-colour ink, so a
solid brown cover cannot pass merely by supplying the same colour. White and
black overpainting also fail. All eight original source runs pass this separate
screen. Glyph consistency remains a candidate, not verified physical semantics.

## Whole original leaders and outlines

All four revised section PDFs are checksum-verified and scanned within fixed
source/work budgets. Exact printed numeric words define bounded search windows;
these windows are search scope, not physical boundaries. Only whole original
straight, solid, opaque strokes are retained. Nothing is clipped, extended,
snapped or completed. PDF coordinates are explicitly unrotated points with Y
downward, separate from the roof plan's native Y-up frame.

A candidate leader starts below the source word, has a nearly vertical original
shaft and a two-sided arrow head. All eligible roof slope pairs at the arrow tip
are retained. A closed triangle requires exact original apex endpoints and a
whole original base stroke with exactly the two original slope endpoints. A
nearby endpoint does not become connected. A longer foreground line is not cut
down to supply a missing base.

Four leaders yield eight slope-pair alternatives: three closed outline
candidates and five held alternatives. AA/BB, CC/DD and GG/HH each contain one
closed outline. The second CC/DD apex is partly obscured by a longer foreground
roof line and has no matching whole base. EE/FF has no exact requested word;
that does not imply the sheet lacks other useful information.

The retained 27 original line items have 31 fixed RGB neighbourhood samples
along each whole segment. The audit independently checks all 837 neighbourhoods
against the unchanged source. These are pixel-consistency witnesses, not proof
that a particular stroke is a physical wall or roof edge.

## Conditional height comparisons

Printed `1/200` sheet-scale word witnesses are retained. Applying that nominal
scale and interpreting the `191.5` label as metres gives:

| Revised section sheet | Roof rise candidate | Eave value candidate | Projected base width |
| --- | ---: | ---: | ---: |
| AA/BB, 373/95/11A | 2.55693 m | 188.94307 m | 9.27946 m |
| CC/DD, 373/95/13A | 2.54000 m | 188.96000 m | 9.27946 m |
| GG/HH, 373/95/17A | 2.54000 m | 188.96000 m | 9.29640 m |

Every closed outline is compared with all 42 earlier roof variants. Absolute
model candidates use each variant's own printed level and relative geometry;
no source frame or orientation is selected by residual. All 126 comparisons
agree within the fixed 0.1 nominal metre tolerance. The largest apex/eave
residual is approximately 0.021287 nominal metres. These values describe
source consistency under shared-datum and same-roof assumptions, not surveyed
accuracy or three independent observations of an as-built building.

The source section widths differ from the roughly 7.844 m plan edge width.
Section cut direction, projection, revision correspondence and the physical
roof assignment have not been established. Height agreement cannot resolve
those questions. No projection angle is fitted to make the widths agree.

The shared-cap face remains unidentified. This pass does not transfer the east
fascia depth, close a wall or modify earlier meshes. Accepted physical
components, world geometry and training labels remain zero. Next, bind the
section cut and visible adjoining roof/wall boundary to the same original plan
component before authorizing an interface surface.

## Reproduce and review

The catalogue names the four previously recovered original PDFs. Place each
verified file in the source directory as `<sha256>.pdf`.

```sh
python -m scripts.build_section_roof_evidence \
  --source-catalogue examples/wicker-section-roof-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --fascia-evidence ../pyramid-fascia-evidence.json \
  --output ../wicker-section-validation

python -m scripts.audit_section_roof_evidence \
  --evidence ../wicker-section-validation/<contract-hash> \
  --source-catalogue examples/wicker-section-roof-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --fascia-evidence ../pyramid-fascia-evidence.json \
  --output ../wicker-section-validation/audit.json

python -m scripts.render_section_roof_evidence \
  --evidence ../wicker-section-validation/<contract-hash> \
  --source-directory ../wicker-interface-originals \
  --fascia-evidence ../pyramid-fascia-evidence.json \
  --output ../section-roof-review.html
```

The standalone review includes four original full sheets, four unchanged detail
renders, original stroke overlays, all eight alternatives, all 126 comparisons
and exact-byte evidence download. The independent audit freshly replays the
build and separately checks original word/trace identities, embedded font
hashes/CIDs, whole path items, original RGB samples, triangle closure and height
calculations. Seventeen focused tests cover overpainting, source glyphs,
fragmented words, unmodified source state, exact endpoint topology, hidden base
holds, disagreeing heights, input/cache changes and early/late work exhaustion.
