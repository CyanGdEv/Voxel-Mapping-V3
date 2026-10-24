# Source section profiles

Planning reviews now retain nominal horizontal and vertical spans for a labelled
component enclosure inside one inferred section view. The vertical span is a
measurement of a source polygon, not an assigned physical building height.

Open `section-profiles.html` in a planning pilot or collection output. Its JSON
receipt identifies the original PDF/page, exact source polygon and paint
references, visible component label, section caption, nominal scale affine and
the source-page evidence hash. Blue outlines in the original-page overlays mark
these unassigned profiles. Desktop job details show the profile count.

The layout correction intersects an existing composited white corridor with the
interval between adjacent captions. Previously a genuine white run was rejected
when its far end extended beyond a caption's horizontal start. The receipt now
keeps both the original white run and the interval actually used. The white
threshold and minimum eight-point corridor width are unchanged. Nothing erases
annotation ink, and source primitives are never clipped at a view edge.

Profile extraction uses a complete, separately retained coarse source-outline
inventory and visible whole-label containment. It does not substitute incomplete
fine regional linework. Shared/nested enclosures, holes, conflicting printed
states, ambiguous or crossing view scopes, missing/conflicting scales, hidden
labels, nondefault PDF units, cropped pages and mismatching printed paper sizes
withhold profile measurements. Unknown section state also withholds measurements.
No nearest caption or smallest enclosure is selected. Raster elevation artwork
is not interpreted by this feature.

Each retained profile includes the unchanged original polygon, section-axis
affine, horizontal/vertical nominal spans and evidence for the coarse enclosure.
The coarse extraction omits short source edges; an enclosure is therefore a
diagnostic hypothesis. Exterior wall role, paint visibility, physical view scope
and scale application remain unverified. Nominal profile spans never populate a
building's height, identify a floor-plan component or create a local 3D shell.

Per-page defaults are at most 32 profiles, 8,192 scope comparisons and eight MB
of evidence; callers may only reduce them. Upstream source extraction and label
association budgets remain in force. Relevant incomplete inventories and work,
count or byte exhaustion clear all profile results. Review indexes deduplicate
identical source pages, reject conflicting/stale receipts and withhold their
profile list on the 128-profile/eight-MB output bound. Cancellation propagates.
The new implementation is pinned in pilot and durable collection contracts;
restart cannot reuse earlier drawing-analysis results under changed code.

The Woodcutters development replay is recorded in
[the source-pinned receipt](evidence/section-profiles/woodcutters-development-validation.json).
It uses previously inspected cached sources for SMD/2024/0136, not an unseen-source
or independent accuracy benchmark. The proposed section sheet now supplies six
view-region hypotheses and one Container-labelled source profile in Section A–A,
approximately 2.4003 m across by 2.4511 m vertically at the printed 1:100 scale.
The profile remains unassigned to a floor-plan component. Original raster views,
deferred section linework, physical heights, finished ground levels and current
as-built state still require evidence.

The next blocker is source-supported section-to-plan component correspondence.
The two size-consistent plan hypotheses remain separate from the section span;
size similarity alone cannot establish that either is the same physical object.
This feature creates no accepted world geometry, reviewed training labels or
model weight updates.
