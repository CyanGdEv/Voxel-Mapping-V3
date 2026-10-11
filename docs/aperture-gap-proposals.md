# Explicit aperture gap proposals

Local-wing area reviews now prepare `aperture_gap_proposals` after their native
inventory and strict boundary review. This additional discovery stage preserves
the original PDF geometry and evaluates the original network, followed by one
explicit connector per independent trial. Competing connectors never coexist
in a trial. It does not search multiple-connector cycles or all possible cycles.

The opt-in `isolate_open_stroked_subpaths` extraction option retains valid open
subpaths when their stroked paint group also contains a deferred closed subpath
or a separately rejected short/clipped component. Original paint ordinal,
subpath index, source coordinates and extraction contracts remain attached.
Filled groups and holes keep the existing topology treatment. Existing extraction
defaults and their contracts remain unchanged.

Only complete, solid, straight, original source components supply the network.
The seed's 12-pixel neighbourhood is a discovery window; whole source segments
are retained and exact intersections are noded without snapping. Every positive
endpoint gap of at most two pixels has its own hypothesis identity and original
native endpoints. Candidate faces need at least 85% IoU and a boundary distance
of at most 12 pixels for review discovery. This does not relax the separate
two-pixel trace-fidelity check or authorize mesh changes. Multiple-ring faces
and candidates filling protected source holes remain withheld.

Each proposed boundary carries original segment interval proofs and separate
connector interval proofs. The 1e-7-pixel provenance comparison allowance never
enters network construction. Geometry identities distinguish shape from support
variants; exact duplicate proofs are suppressed, while different provenance is
retained. Bounded work exhaustion discards all partial proposals and gaps.
Recipe, original PDF, native inventory and output bytes are pinned on replay.

The new native-to-render transform uses the uniform width scale used by PyMuPDF.
Rounded pixmap height is not a separate Y scale. The earlier `pixel_to_native`
helper remains unchanged for resampled images and reproducibility of earlier
audits. The transform distinction is explicit in the proposal receipt.

## Mutiny archway 3

The real existing CTD elevation retains 3,451 components in this optional mode.
All 16 apertures complete the bounded pass, but only archway 3 has proposals:
two provenance variants of one inner-arch shape. One 0.181293-pixel connector
(about 4.24 mm at nominal scale) closes the right spring. Each variant retains
32 original boundary interval proofs and one connector proof. The head is
original straight linework, not an invented Bézier curve or outer masonry band.

The outline has 95.889% IoU with the previous trace but a 3.524-pixel boundary
distance, exceeding its original two-pixel fidelity allowance. Therefore the
original seed remains unchanged. A separate explicitly reviewed derivative,
`evidence/mutiny-north-wing-arch-proposal-review-seed.json`, records the visual
source review, both support variants, failed parent fidelity comparison and
connector hypothesis. Physical identity and park placement remain unverified.

That derivative also refines the floor datum to the continuous original source
line. Six manually reviewed door-bottom vertices follow the new drawn floor,
moving 0.08052 pixels. This is an explicit trace revision, not source snapping.
No absolute elevation is inferred, and boarded w3.13 remains uncarved.
The partial local mesh has 142 courtyard-wall triangles, four roof triangles
and 16 openings. The 15 other opening outlines retain their manual traces.
The isolated one-block-per-nominal-metre Bedrock preview has 281 surface cells
and 5,681 composed blocks in eight chunks. Native readback verifies all written
blocks and unwritten air. This export retains the connector hypothesis, omitted
outer/end walls and provisional cross-date roof assembly; park additions stay zero.

```sh
python scripts/propose_aperture_gaps.py \
  --recipe evidence/mutiny-north-wing-source-label-corrected-seed.json \
  --source /path/to/original-elevation.pdf --output /path/to/fresh-proposals
python scripts/render_aperture_gap_review.py \
  --source /path/to/original-elevation.pdf \
  --report /path/to/fresh-proposals/aperture-gap-proposals.json \
  --recipe evidence/mutiny-north-wing-source-label-corrected-seed.json \
  --output /path/to/source-review.png
python scripts/build_local_wing_review.py \
  --recipe evidence/mutiny-north-wing-arch-proposal-review-seed.json \
  --sources /path/to/three-original-pdfs --output /path/to/fresh-model \
  --isolated-world
```

Next: establish the remaining physical aperture outlines, source-backed outer
and end-wall traces, roof junctions and plan/elevation correspondence. Geographic
controls, physical identity and an accepted datum are still required for park
placement. Gap discovery does not resolve these production requirements.
