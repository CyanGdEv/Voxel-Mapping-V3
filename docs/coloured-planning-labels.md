# Original-colour planning labels

The glyph screen accepts supported opaque RGB and grey text with sufficient
contrast. It keeps original font programs, native glyph codes and positions.
Black-text screening retains its existing grayscale path. Coloured text uses
the rendered RGB source and a reference made with the original glyphs.

Two checks are required: source pixels must support the original ink colour,
and the colour/coverage at each reference glyph must match within 12 RGB levels
and the existing one-pixel position tolerance. Uniform matching-colour paint
fails the surrounding-ink ring check. White or black covers, different colours,
lighter substitute ink and erased individual characters are tested separately.
The isolated-glyph fallback also checks reference colour, rather than accepting
any dark pixels. Opacity, layer, transform, font, character and raster budgets
remain enforced. Low-contrast text is withheld. Backgrounds or antialiasing that
do not fit the supported colour-over-white reference remain unresolved.

Both glyph-screen versions change so saved planning analyses are recomputed
under the new evidence contract. This is a deterministic source adapter; it
does not train neural weights or establish a label's physical meaning.

## Real Wicker development replay

The checksum-pinned original proposed woodland-path site plan
(`1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d`)
was rerun without supplied crops or polygon recipes. Among the same 134 selected
surface/material labels, supported glyph screens increase from **3 to 9**.
The 34-role-label inventory increases from **6 to 13** supported screens.
Ordinary coarse extraction retains **two unregistered surface candidates**,
labelled `ground` and `COURTYARD`, compared with zero in the earlier replay.
These are source hypotheses, not two accepted paths or plazas.

The first exploratory colour projection accepted more labels; it was replaced
before publication because ink chromaticity alone cannot distinguish lighter
substitute grey. Reported results use the stricter per-reference colour match.
There was no threshold tuning against the real source outcome.

Fine surface extraction remains incomplete and no usable common area frame is
established. Physical boundary roles, heights, levels, geographic alignment and
current construction state remain unresolved. Accepted park geometry, generated
buildings and trained weights remain zero. This previously inspected drawing is
development evidence, not an unseen-source accuracy benchmark.

The packaged full-plan smoke now uses grey, brown and red labels, then checks
the same two footprint markers, three paving regions, source spacing, saved
blocks, disconnected paving and persistent restart. Synthetic success remains
separate from the real-source result. See the source-pinned
[replay receipt](evidence/coloured-planning-labels/validation.json).
