# Default rock boundaries around gaps

The saved reconstruction rule is: detected gaps are boundaries, with rock edging
assumed unless an explicit source claim or override says otherwise. This comes
from the user's instruction, not a claim that rock geometry was read from a plan.
The persistent policy is `voxel_mapper/data/planning-gap-boundary-policy.json`.

Area pilots now collect enclosed holes in the union of original paving fills.
Their existing contours supply the boundary. Grass, planting and other island
interiors remain untouched. No gap is filled with rock, no open corridor is
closed, and neither height nor width is invented. Legend display cutouts are
ignored: the detector uses original source paving, not the separate clipped
review geometry.

Every default record carries `classification_basis: user_default_assumption`,
`material: rock`, and a planning instruction to avoid crossing the boundary.
It remains physically unverified and ineligible as a training label. These
records do not add world blocks or update model weights.

## Exceptions

Explicit gap overrides identify the current gap ID, boundary kind and evidence.
Wall, fence, water edge, building and opening instructions override the default;
a whole-gap opening override removes the boundary restriction. Stale IDs fail
rather than applying an exception to a different source gap.

Same-page building-footprint proposals can override a gap they substantially
occupy. The detector also screens literal visible building labels and matches
them to original opaque white fills. These claims suppress rock assumptions;
they do not certify a building or infer wall materials or dimensions.

For a shared grass/building gap, only relevant boundary segments are excluded
from the rock default. A 0.5 native PDF-point association margin around a source
building claim allows conservative suppression at its interface. This margin
is neither a construction dimension nor a repair to the source boundary. The
complete source gap contour stays unchanged, and the assumed/explicit segments
are retained separately. Visible label proofs and source fill references remain
in the review evidence.

The source-label adapter currently handles literal building/shop/station/
maintenance/toilets/restaurant/kiosk labels. Other explicit boundary kinds can
be supplied through the override API; arbitrary notes are not automatically
interpreted as exceptions by this stage.

## Review and bounds

`review.html` links a separate gap overlay over the paving map. Brown lines are
assumed rock boundaries. Grey lines are explicit source building interfaces or
other overrides. Planting interiors and unspecified dimensions remain intact.
The implementation and effective policy participate in the desktop job contract.
The Windows package includes the policy JSON and checks its use in the frozen
planning smoke.

The Wicker replay applies the rule to 43 enclosed source gaps. One shared gap
also has explicit building-interface segments. It uses pinned paving evidence
and earlier building proposals from the same original page, plus current native
building-label screens; it does not rerun unrelated full building discovery.
This previously inspected source is not an unseen accuracy benchmark.

Lower-only limits bound paving inputs, native points, union work, gap count,
claim comparisons and output. Failure clears partial boundary records, and
cancellation propagates. Native tests cover default material, preserved island
interiors, explicit openings/fences/buildings, partial building interfaces,
legend cutouts, unchanged open corridors, stable IDs and quotas. Managed desktop
checks retain the previous world/export counts and add a saved-policy smoke.
