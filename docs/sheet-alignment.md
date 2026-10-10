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
The initial alignment implementation was validated on synthetic fixtures. The
corpus replay results are recorded separately in
`evidence/alton-sheet-replay-validation.json`.

## Replaying the retained Alton corpus

Use the saved expanded V4 and Mutiny Bay planning archives and the retained
`park-osm.json` from the foliage V15 evidence package:

```sh
python -m voxel_mapper.alton_sheet_replay \
  --expanded-archive /path/Alton_Towers_Expanded_Planning_Data_V4.zip \
  --mutiny-archive /path/Alton_Towers_Mutiny_Bay_Planning_Data.zip \
  --osm /path/park-osm.json --work-directory /path/alton-sheet-replay
```

The command pins both archives and the map to the original hashes, reconstructs
the exact 144-object named map reference feed (92 polygon references), and runs
offline acquisition, extraction, matching and sheet alignment. It does not
generate a Minecraft package. Repeated runs verify existing outputs and resume
completed extraction. Changed configuration or outputs require a fresh replay
directory. Use PyMuPDF 1.26.6 and pypdf 6.10.0 to reproduce this run's readers.

The Mutiny Bay archive's catalogue lists attachments absent from that archive.
`planning_archive --allow-partial --catalogue-member alton-planning-catalogue.json`
checks every retained PDF, imports absent catalogue entries as pending links,
and reports retained/deferred counts. Strict complete-archive import remains
the default. Missing files cannot acquire checksum-verified blob provenance.
The expanded archive subsequently supplies the other available PDFs; this
does not imply a fresh council download or complete planning history.

Version 2 rejects distant centroid associations in a vectorized prefilter
before transforming outlines. A one-micrometre margin prevents the prefilter
from making the final acceptance threshold stricter through rounding; the
original exact outline and centroid checks still decide every support. The
64-object synthetic dense-sheet test performed the same 2,000 trials in 0.624
seconds, compared with 2.614 seconds before this change. This is not a
whole-park throughput or feature-ceiling benchmark.

## Retained corpus result

The replay recovered 397 catalogue URL records referencing 309 distinct PDFs
and inspected 818 pages. The 211,831-candidate geometry feed (38,772 polygons,
173,059 lines) and the named reference/association feeds reproduced their
previous checksums exactly. Extraction resumed all 818 pages on verification.

Of 38,772 checked polygons, 14,113 had map shortlists across 196 sheets. The
default search made 221,645 pair trials; the extended 10,000-trial search made
760,571. Neither produced a qualifying three-object placement proposal. The
extended search selected 6,228 objects and explicitly deferred 7,885 objects;
58 sheets hit object selection limits and 51 still exhausted their trial
budget. Therefore this result is bounded, not an exhaustive rejection of every
possible sheet alignment. Fifty-one sheets also have ambiguous printed scales
and 101 lack a recognized scale label.

Both search receipts passed checksum/source-verified resume. Full decisions
from the extended search are retained in `evidence/alton-sheet-review.jsonl`;
the reproduction receipts and limits are in
`evidence/alton-sheet-replay-validation.json`. All 538 tests pass. No park
geometry was promoted or exported. The next useful work is identifying physical
outlines and separating viewports before seeking independently checked placement.
