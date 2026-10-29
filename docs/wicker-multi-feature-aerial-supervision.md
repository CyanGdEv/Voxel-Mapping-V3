# Wicker Man tunnel, theming, track, queue and paving reference

The pinned 836 × 1,280 user image has five confirmed, image-local roles:

| Mark | Sparse target | Named feature |
| --- | --- | --- |
| Green | `sound_tunnel_trace` (12) | Wicker Man sound tunnel |
| Blue/cyan | `theming_structure` (3) | Big Bob |
| Red/light red | `paving_trace` (11) | Path and plaza boundaries |
| Yellow | `roller_coaster_track` (2) | Wicker Man track |
| Purple | `queue_line_trace` (13) | Wicker Man queue |

Earlier green tree/grass and purple structure/barrier/track legends remain
unchanged. Named feature strings and site/ride tags accompany the new guides.
Ink windows constrain automatic extraction around the small named features and
exclude the blue screenshot border; these windows are not measured footprints.
A clean-image colour residual rejects natural colour candidates. Unmarked pixels
remain unknown, rather than negative/background labels.

The complete reference uses the pinned cached park-wide 2,048 × 1,024 Esri RGB
export. Two primary-host and one public mirror export requests timed out. The
finer cached locating crop clipped Wicker Man guides and was retired. The
accepted crop contains all 21,417 extracted positive source pixels. Its 290
unpainted SIFT/RANSAC inliers have a p95 residual of 0.716 clean pixels. This is
coarser source sampling and image agreement, not independent physical accuracy
or a claim of improved optical resolution.

The native clean grid retains 70 tunnel, 5 Big Bob, 1,160 paving, 355 track and 5
queue pixels. Source-coordinate/BNG guide points also retain the original sparse
evidence: 142 tunnel, 8 Big Bob, 2,348 paving, 829 track and 12 queue points.
The tiny theme/queue targets are insufficient for dense-class accuracy claims.
Fine user marks do not make the clean imagery or native height survey finer.

Height context comes from the matched EA 5 January 2022 native one-metre DTM/DSM
in BNG/ODN, using the pinned OSTN15 transform. It is raster-derived context, not
raw-return classifications, measured track heights or proof of ground below a
tunnel. Gaps remain gaps. The annotations do not establish filled polygons,
widths, vertical profiles, physical connections or junctions at XY crossings.

Twenty-one relevant tests pass. Source and registered masks, named BNG points
and height arrays reproduce exactly. An independent native raster sample checks
4,096 pixels for each height field. Three previous image-local source masks are
unchanged. The Alton Towers v2 world SHA256 remains
`24aba8e12509817964be2af9bbc2421899a44fe79e6b23f7fe0e49afec557138`.

The reference is prepared for training and review. No model weights are fitted
or promoted, and this intake adds no world blocks. The download includes the
original annotation, separate clean RGB, sparse targets, named BNG points,
registration/source receipts, native heights, datum grid and an offline numeric
replay. Install the full repository at this revision, then run `python replay.py
FRESH_OUTPUT` from the extracted package. Replay relocates only the datum-grid
file path; source masks, BNG coordinates and height values remain exact, while
the frame-path metadata checksum changes. To keep the download compact, the
derived height NPZ is regenerated from the included native rasters; canonical
numeric checksums verify every height array.

Attribution: user-provided guides; Esri World Imagery and its providers;
Environment Agency information, OGL-UK-3.0. Source dates differ, extraction
thresholds remain assistant settings, and physical registration has not been
independently surveyed.
