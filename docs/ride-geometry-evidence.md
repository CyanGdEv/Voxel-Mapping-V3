# Source-linked ride geometry evidence

This stage links the retained Wicker Man plan's printed levels to original
crosshairs, ordered track visits and dated LiDAR context. It creates a portable
review package, not new model weights, accepted 3D targets or world blocks.

## Reproduced source facts

All fourteen HP/LP labels and numeric levels are replayed from original PDF text.
Their circle/crosshair geometry, vector sequence and coordinates are checked
against the pinned retained profile. No display interpolation, estimated closure,
terrain correction or generated world geometry supplies a height label.

The original 428-vertex route stays open. Each marker is projected onto original
segments, retaining distinct route visits separated by more than eight nominal
metres of chainage. Candidate visits are retained within four nominal metres;
the nearest is a candidate only within 0.15 m and with at least 0.75 m distance
margin from another visit. These thresholds are explicit drawing-link rules,
not surveyed uncertainty or physical accuracy guarantees.

Thirteen markers meet the rule. **HP7 is held** because another track visit is
too close to select safely. All alternatives remain in the evidence, with
original segment index, chainage, projected XY and source distance. No crossing
stations are averaged and no height is silently moved to another branch.

## Datum and alignment limits

The printed source labels do not establish the source vertical datum or what
physical running surface the level references. The package therefore records
`printed_level_datum: not_established` and keeps every marker ineligible for
surveyed XYZ training. The thirteen branch candidates are source-plan links,
not accepted as-built height controls.

The unchanged 56,568-return EA January 2022 cloud is pinned in BNG/ODN. Two-metre
queries around each nominally aligned marker retain return counts, raw classes
and five height quantiles. They do not classify those returns as track or infer
hidden structures. The retained map alignment uses related OSM building
references and is not independently surveyed. Printed-level-minus-LiDAR
accuracy errors remain null rather than comparing unverified datums/identities.

Every marker has a review task for its vertical datum and running-surface
meaning; HP7 also requires branch resolution. Original data, provisional map fit
and source/capture dates remain separate. The model still needs independently
verified plan/section/support relationships before learning accurate 3D assembly.

## Additional source acquisition

Two retained catalogue entries were requested as possible survey/section
evidence: the topographical survey attachment `302160` and existing site sections
attachment `175677`. Both returned HTTP 503 in this session. Neither response
was a verified original PDF; no new survey data or datum confirmation is claimed.
The acquisition receipt retains their catalogue checksums and official URLs so
these sources can be retried later. No alternate portal access or credentials
were used.

## Replay and validation

```sh
python -m voxel_mapper.ride_geometry_evidence \
  --request PATH/replay-request.json --output FRESH-EVIDENCE-DIRECTORY
```

The request pins the original PDF, source markings, retained profile, raw cloud,
cloud receipt and alignment. Changed bytes, altered printed levels/crosshairs,
incompatible coordinates and incomplete inputs fail before publication. Output
is fresh and atomic, with source copies and a portable replay request. The
review delivery also contains original-source marker close-ups and a nominal
route/branch diagram; neither changes the original PDF.

Sixty-eight focused local engineering tests pass. Synthetic tests cover crossing
ambiguity, distant markers, changed source/printed labels, datum safeguards,
cancellation and portable replay. A separate numerical audit recomputes actual
segment projections, chainages, branch margins, cloud counts and quantiles.
Source/render replay checks establish reproducibility, not physical accuracy.

The next missing evidence is a verified survey datum/control relationship and
reviewed running-surface/section correspondence. Those should be acquired before
using these printed levels as supervised world-height targets. Other-park ride
component learning remains the separate 96-example development task described in
[ride reconstruction training](ride-reconstruction-training.md).
