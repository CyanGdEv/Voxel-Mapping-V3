# Smiler track: first visible pass

Run after the corrected one-block Oblivion park:

```bash
python -m voxel_mapper.smiler_reconstruction \
  --park-output /absolute/path/oblivion-one-block-track \
  --datum-grid /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output /absolute/path/smiler-lifts
```

This pass emits the inclined lift, the vertical lift, their short approaches and
crest approaches, plus simple supports and a vertical tower. It does not emit a
closed full course or claim to reconstruct all fourteen inversions. The retained
park, Wicker Man and corrected Oblivion are copied and preserved outside the
Smiler overlay. Existing outputs are never overwritten. All cells of changed
chunk sections and total chunk coverage are checked after Bedrock readback.

The reviewed manufacturer perspective labels Station, Brake 1, Brake 2, Lift 1
and Lift 2:
https://www.gerstlauer-rides.de/fileadmin/Daten/Bilder/Produkte/Achterbahnen/Infinity_Coaster/IC_Layouts/2128_AltonTowers/IC_2128_AltonTowers_02_0001.jpg

The associated Infinity Coaster 1140 example lists 35 m height and 1,140 m
length. The finished park's published figures are 30 m and 1,170 m, so this is
qualitative design evidence, not a surveyed as-built model. The older proposed
planning images do not establish every finished inversion. Global official
figures cannot resolve branch elevations at the 34 mapped crossings.

Bindings are explicit hypotheses on the retained OSM snapshot: segment 55 for
the inclined lift, and the end of segment 113 for the vertical-lift foot. Way
IDs and geometry ranges are guarded against changed mapping. The inclined lift
rises thirty metres over approximately thirty horizontal metres. The vertical
span repeats its x/z coordinates while rising thirty metres; 3D arc-length
sampling at <=0.2 m retains every intervening level. A one-dimensional height
function over plan distance would lose that span.

Both feet are estimated two metres below the ground-median station slab;
crests are thirty metres above the feet. These are explicitly estimated ODN
levels, not measured track heights. Composite ground can lie above the estimated
construction level, so the overlay includes local clearance/excavation and
records below-ground samples. Crest/approach shape, tower/support forms and
materials remain generic. Track uses a single black-concrete centreline as a
schematic representation, not a claim about exact manufacturer gauge.

Next: identify the loading/indoor-roll path, bind both drop/corkscrew sequences,
then assign branch-specific heights and roll through dive loops, batwing,
sea-serpent and cobra-roll sections. Inversion-count labels alone cannot define
those three-dimensional shapes; a flat connected loop would be misleading.
