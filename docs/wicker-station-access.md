# Station access and basement source review

This revision replaces the previous entrance flight's 1 m cardinal rise with a bounded approach from the preshow review opening to actual retained source paving. It keeps all building shells, roofs, shop landings and terrain unchanged. Only 18 voxel records differ from the earlier station/preshow export, all at the entrance steps and rails.

The estimated display route is 4 cardinal metres long and one block wide, descending from upper floor 184 m to the retained paving at 182 m. All five walking columns connect with at most 0.5 m rise. Native bottom slabs supply intermediate half steps; six oak-fence columns sit outside the walking route. The narrower-than-four-block fence rule is preserved. No source paving, rock, building marker, terrain or existing protected object is removed to make the route fit.

The generator searches a maximum 12 m radius and 20,000 states, rejects object collisions, checks two whole air blocks above every walking surface, and withholds export if no route reaches retained source paving. It does not treat building-marker colours or arbitrary grass as a paving endpoint. This is an estimated circulation aid, not a measured staircase, complete queue route, passenger-access certificate or accessibility design. The exact queue lane connection and other entrances remain unresolved.

## Basement drawing findings

The checksum-pinned original [2967-22 P1 basement drawing](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=163936) yields an inner clear envelope approximately **8.598 × 14.952 m**. Ten visible outline strokes are replayed and two wall gaps measure approximately **3.450 m** each. Their source strokes and native coordinates are retained with an annotated original-page preview. Purple fill rectangles alone bridge these gaps, so they cannot be treated as visible closed walls.

The printed undercroft **178.00**, station inspection **181.25** and maintenance **181.50** levels remain separate roles. Neither gap is automatically labelled a passenger queue entrance. The sheet does not establish an internal staircase. Its own-sheet coordinates cannot be passed through the roof-page transform without a new correspondence review. Therefore the extracted basement remains unplaced evidence; the existing provisional undercroft is preserved, rather than silently replaced by a misaligned floor or invented stairs. No accepted training labels are added.

## Replay and validation

Use the same portable inputs and command as [the station/preshow world](wicker-station-preshow-world.md). The new world has the distinct level name `Wicker STATION ACCESS - half-step paving connection`; fresh output is mandatory. The saved report pins both the shell generator and access implementation. Outputs add `basement-source-review.json` and `basement-source-review.png`.

Twenty-two focused tests cover route slope, actual paving contact, collision/protected-column refusal, cancellation/budget limits, existing multi-part shells, shop geometry and native slab/facade states. The exported archive is cold reopened across 187 chunks, including five actual stair surfaces and ten stair headroom samples. Independent archive extraction rechecks all 576 corrected shop blocks and 11 shop landings. Minecraft import/gameplay remains untested.
