# Section projection and shared-cap ambiguity

The section outlines are compatible with an oblique view of the original roof
plan. Their full projected widths must not be treated as single plan-edge
lengths. The original third roof spoke supplies an interior base contact and
two adjacent projected spans. This pass tests those spans against the original
plan without changing source coordinates or choosing a preferred orientation.

## Original evidence and projection recipe

The original section pass is freshly replayed against all four checksum-pinned
PDFs, its catalogue and the unchanged fascia evidence. The original four-spoke
plan graph is separately replayed. All eight plan perimeter/spoke lines must
also match whole straight items in the original roof-plan PDF. The audit checks
their native coordinate conversion independently.

Each eligible section group needs three distinct original spoke endpoints on
one unchanged, whole base line. The interior contact does not split that base
into invented source segments. It does not override the preceding incomplete
triangle alternative. Missing bases, missing or extra contacts and failed
source-pixel support remain held. The three complete section groups qualify;
the partly obscured second CC/DD roof remains held.

For every group, the recipe enumerates four possible front plan corners and
both possible left/right neighbour orders: eight correspondences. Two original
section-span differences and two original plan-edge vectors determine a raw
horizontal projection vector by a two-equation solve. The vector is normalized
to propose an orthographic unit camera. No scale is fitted: the original plan
and printed section scales remain fixed. The original roof apex anchors the
horizontal translation; original corners and apex are never moved.

All three unchanged section stations then test the unit-camera prediction.
The fixed acceptance threshold for this diagnostic is 0.5 original PDF points.
Raw vector length, unit vector, all predicted original corners and all signed
station residuals are retained. No residual ranking, averaging, selected pose
or preferred physical face is produced.

## Results

| Result | Count |
| --- | ---: |
| Original plan line witnesses | 8 |
| Section spoke groups | 4 |
| Supported section groups | 3 |
| Retained and supported projection candidates | 24 |
| Shared cap visible under a candidate camera | 12 |
| Shared cap hidden under a candidate camera | 12 |

All eight orientations for each complete source group agree within the fixed
projection tolerance. Maximum source-station residuals are approximately
0.079 PDF points for AA/BB and CC/DD and 0.226 PDF points for GG/HH. The earlier
width discrepancy is therefore compatible with orthographic projection of the
original rectangle. This is a conditional model consistency check, not verified
physical correspondence, geographic bearing or source accuracy.

Candidate depth ordering and outward perimeter normals determine which two
edges would face the observer. Each visible source interval retains its original
plan edge IDs. In each source group, four hypotheses show the shared cap and
four hide it. The face-assignment gate explicitly retains both sets. A user
selecting a camera in the review does not change the evidence or resolve that
ambiguity.

The remaining requirement is a section cut/view direction or an adjoining
feature tied to the same original plan component. Neither height agreement nor
the smallest projection residual supplies that evidence. The existing east
fascia depth is not transferred to the shared cap. No wall closure, new mesh,
accepted physical component, world geometry or training label is generated.

## Reproduce and inspect

The source PDFs are the originals already recovered by the preceding passes.
Input evidence filenames below refer to the unchanged exported reports.

```sh
python -m scripts.build_section_projection_evidence \
  --section-evidence ../section-roof-evidence.json \
  --pyramid-evidence ../pyramidal-roof-evidence.json \
  --section-catalogue examples/wicker-section-roof-catalogue.json \
  --source-directory ../wicker-interface-originals \
  --fascia-evidence ../pyramid-fascia-evidence.json \
  --roof-plan-pdf ../wicker-building-originals/files/6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047.pdf \
  --output ../wicker-projection-validation
```

`scripts.audit_section_projection_evidence` accepts the same source arguments
plus `--evidence <result-directory>` and `--output <audit.json>`. It freshly
replays the parent and projection pass, then independently checks original PDF
items, the two-equation camera solve, all 72 station residuals, all 24 visible
face sets and all four ambiguity gates.

```sh
python -m scripts.render_section_projection_evidence \
  --evidence ../wicker-projection-validation/<contract-hash> \
  --section-evidence ../section-roof-evidence.json \
  --pyramid-evidence ../pyramidal-roof-evidence.json \
  --source-directory ../wicker-interface-originals \
  --output ../section-projection-review.html
```

The standalone review includes original section images, whole-source and
projected overlays, the original plan coordinates and every camera alternative.
The blue arrow points from the roof toward the candidate observer, in native
plan axes. It is not a geographic bearing. The exact exported JSON retains all
alternatives regardless of the displayed selection.

Validation runs 63 targeted tests: 20 new projection tests, 37 existing section
and original-font tests, and six original plan-topology tests. The base PR's
1,823-test GitHub run passed; the new complete suite runs separately in GitHub
CI. The new tests cover all symmetries, reflected/rotated plans, failed scales,
incomplete groups, source immutability, exact original plan witnesses,
parent/cache tampering and early/late work exhaustion. Projection work is capped
at 100,000 checks; the unchanged parent replay has its separate 2,000,000-check
ceiling. Budget failure clears all partial geometry/pose fields.
