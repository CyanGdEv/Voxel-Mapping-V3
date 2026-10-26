# Whole native annotation context

Planning drawings often emit one text show per word. The Wicker note
`Path lowered and ground graded down at 1:3 to reveal Deer Wall`, for example,
was read as separate `Path` and `ground` labels. A standalone-noun parser could
then treat an instruction, title, revision note or planting description as a
feature or material label.

The planning role and fine-surface stages now retain the complete connected
native text context before allowing a fragment to vote for a feature. The pass
uses an indexed, bounded same-baseline adjacency graph. It requires horizontal
text with matching font, colour, opacity and paint type, compatible sizes and
small native gaps. Every connected run is retained; competing neighbours are
marked ambiguous and never resolved by picking a nearest word. Rotated page
metadata is supported, but differently oriented text and incompatible typography
remain outside this initial grouping rule.

Each context records original text, trace and character identities, native
geometry and original glyph visibility for every part. Hidden or ambiguous
continuations remain uncertain evidence. They cannot supply a positive role,
finish, drawing state, width or geometry. Split literal compounds such as
`Existing` + `Path` are also withheld rather than silently discarding the prefix.
This stage does not infer a semantic interpretation for every grouped phrase.

Fragments remain in the evidence as `annotation_fragment_withheld`. Every
containing source enclosure is blocked from using other labels to turn the
excluded note into a building or paving candidate. This prevents a separate
`stone` label from authorising a floor after `Path lowered...` is excluded.
Nested boundaries, genuine conflicts, original holes and linework remain intact.
The prior building-name adapter still requires its own complete visibility and
same-enclosure evidence. Saved layout validation rejects annotation fragments
even if their status is removed while the context witness remains.

The new lower-only bounds are 20,000 native runs, 64,000 indexed comparisons,
32 runs per connected context and 512 characters per context. Existing glyph,
geometry, candidate, containment and output limits remain. Cancellation or a
quota stop withholds the complete analysis rather than returning a truncated
line as a successful feature. Implementation hashes invalidate analysis caches;
existing saved layouts remain reloadable and are not retroactively certified
against source text they do not contain.

## Wicker development replay

The unchanged original PDF now excludes **eight** surface/material fragments:
the two paving descriptions, a title fragment, a revision-note fragment, two
ground/planting notes and both the path and ground fragments of the grading
instruction. Five distinct contexts have complete original glyph support;
uncertain contexts retain their failed visibility or ambiguous adjacency flags.

Eligible surface labels fall from **45 to 37**; labels with no usable enclosure
fall from **41 to 33**. These are candidate-label counts, not a count of physical
paths. The semantic stage withholds nine role-label fragments in total.
The fine scan completes **11 regions**, using **7,293 native candidates**,
**15,422 points** and **1,029,557 scan-work units**, down from 14 regions,
9,902 candidates, 20,966 points and 1,310,936 scan-work units in the name-context
stage. No quota was increased.

All six previous proposals retain their original polygons, roles and finishes:
four building-footprint proposals and two tiny material patches. The flat export
still has eight material cells, no verified paths, no building heights or roofs
and no surveyed registration. No accepted park geometry, training labels or
neural updates are created. This original was previously inspected development
data, not an unseen accuracy benchmark.

Eleven regressions cover split notes and material fragments, enclosing-feature
fallbacks, hidden continuations, nested boundaries, typography/distance mismatch,
split states, competing continuations, quotas, rotation, replay, cancellation and saved evidence. The
managed/frozen desktop smoke adds a separate closed enclosure containing a split
instruction and a stone label. It must retain the original two buildings and
three paving proposals, 149 saved paving cells in two components, both complete
exports and persistent restart, without inventing an extra feature from the note.

See the [source-pinned receipt](evidence/planning-annotation-context/validation.json).
The next step is evidence-based recovery of genuine path/plaza boundaries,
including curved or open source edges that the straight-face adapter cannot
currently turn into complete physical surfaces.
