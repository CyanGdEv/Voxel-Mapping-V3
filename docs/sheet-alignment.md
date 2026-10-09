# Multi-object sheet alignment

Enable `sheet_alignment: {"enabled": true, "max_pair_fits": 2000}` alongside
`footprint_matching` in a park job, or run `python -m voxel_mapper.sheet_alignment`
with the candidate feed, matching directory, reference file/CRSs, corpus and output.

The stage checks the original PDF and exact retained extraction, pins all input
hashes, and groups associations by PDF/page in SQLite. Each page requires at least
three distinct, noncollinear polygon correspondences under one orientation
preserving similarity transform. Pair centroid fits propose placements; all
supporting centroids are then refitted and every original outline must retain
at least 85% IoU and at most two metres centroid error. These are configurable
function arguments for experimentation, not measures of survey accuracy.

Printed scale labels are compared with the fitted scale; missing, ambiguous or
disagreeing labels remain review flags, and viewport scale is never assumed.

Repeated reference assignments and nested outlines cannot count as several landmarks. Multiple
placements, competing identities and exhausted fit budgets remain explicit
review flags. Dense sheets select at most 64 objects, prioritizing interior name
matches, then shape agreement and stable ID. Every deferred object is counted
and the sheet is flagged `object_selection_truncated`; the result is a partial
search rather than an exhaustive placement. Maximum 2,000 pair trials per page (configurable up to
10,000), three reference associations per object, 12 reported hypotheses and
2.5 million input records bound the work; this stage has not been benchmarked
at the feature ceiling. Multipart shapes remain comparison hypotheses.

`sheet-hypotheses.jsonl` records support identities, overlap/error, transform and
source binding. `sheet-report.json` binds outputs for checksum-verified resume.
Incomplete output directories require removal before retrying. The SQLite index
is intermediate data; output hashes and source contracts govern reuse.

These placements do not establish object identity, independent registration,
current built state, reuse rights, vertical measurements or materials. Existing
independent registration and feature promotion reviews remain required. No
world geometry is added by this stage. Boundary self-fits and centroid matches
must never be copied into the independent checkpoint list.

The retained Alton report contains Crooked Spoon and Alton Towers Hotel on PDF
`651184f3ebb345468cb1f397f3d2231227220dd097875479f8b252173ca75e86`, page 1.
Both name associations have shape-disagreement flags. They are a review lead,
and two associations alone cannot satisfy the new three-object requirement.
This change's validation uses synthetic fixtures; the full retained planning
corpus has not been replayed through this new stage.
