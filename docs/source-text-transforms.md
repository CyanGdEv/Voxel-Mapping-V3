# Original PDF glyph transforms

Glyph reference rasters now preserve the original direct-page text-show matrix,
font size, horizontal scale and graphics matrix when a unique original binding
is available. CAD can stretch individual words horizontally while leaving their
vertical size unchanged. Redrawing those words with one uniform trace-reported
font size loses their original ink geometry, particularly in the colour check.
No pixel acceptance threshold changed: the existing per-glyph 1% unsupported
core allowance, one-pixel position tolerance, RGB coverage check and paint-over
ring check still apply.

The binding requires a complete original native trace and exactly one matching
original show operator, encoded glyph sequence and original font resource.
Native glyph identifiers and each original character origin are retained.
`TJ` kerning keeps those measured origins; no font advance is inferred. The
reference uses the same supported embedded font program or already-bound
original resource. No substitute font, image fit, ratio search or dimension
residual supplies a transform.

The new adapter supports finite, positive-determinant orthogonal bases with
1–40 point axis magnitudes and at most 2:1 anisotropy. It requires ordinary
uncropped zero-origin pages. Forms, implicit text advance, nonzero rise, shear,
ambiguous shows and partial traces do not receive this adapter. Unbound sources
retain the previous glyph-screen path; they are not newly promoted by a guessed
matrix. The overall source-font and raster eligibility guards remain in force.

Parsing is bounded to 16 MB decoded content, 500,000 operators, 20,000 show
operators, 200,000 native characters and 64 graphics-state stack levels. Any
incomplete or over-budget inventory publishes no transform bindings. An
in-memory weak page cache is bound to unchanged content bytes, font resource
mapping and page frame, and is invalidated when those change. No persistent
learned memory or training weight is created.

The glyph screen versions are now `source-font-glyph-raster-screen-v8` and
`source-font-isolated-glyph-screen-v6`. The planning job implementation contract
also pins the transform resolver, so previous analyses must rerun. Saved
standalone source-local layouts remain subject to their existing validators.

## Wicker development replay

On the previously inspected woodland-path site plan, the complete original
`Site Plan Proposed showing Woodland Path` title now passes its fragment
screens. The red `showing` and `Path` fragments preserve their original word
matrices. Both paper scale rows pass, and the single source title plus original
A1 page select the nominal printed 1:250 scale. The A3 1:500 alternative is
retained unchanged. This is paper interpretation, not verified physical scale.

Supported surface labels rise from **9 to 46 out of 134**. The coarse source
adapter retains three building-role enclosure hints; these are not reconstructed
buildings. The added supported evidence exposes the next blocker: 46 regional
windows exceed the unchanged 32-region limit. The fine stage withholds all
boundaries with `surface_region_budget_exceeded`; the area stage remains held on
`complete_fine_boundary_discovery_required`. The prior two fine surface proposals
are therefore not emitted by this full-sheet replay. No real area frame, world,
registered path, accepted building, training label or neural update is produced.

The next stage needs bounded recovery across the larger supported inventory,
such as shared source indexing and carefully scoped regional batches. Raising
limits or dropping inconvenient labels is not evidence of complete recovery.
This source is development data, not an unseen park-accuracy benchmark.

The packaged desktop smoke separately verifies an original embedded two-glyph
font under nonuniform scaling, then retains the managed A1/A3 area export,
149 saved paving cells, two paving components and restart checks. Its buildings
remain synthetic footprint markers.

The [source-pinned development receipt](evidence/source-text-transforms/validation.json)
retains the original word matrices, encoded-glyph and runtime pins, before/after
label counts, independent nominal context check and actual recovery hold.
