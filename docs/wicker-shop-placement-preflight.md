# Shop placement preflight

The preflight samples the **rotated source mesh at 1:1**, including slabs,
fence details and trapdoors, against retained geographic hypotheses. It writes
diagnostics only and does not produce world rows or accept a registration.

```sh
python scripts/preflight_wicker_shop_placement.py \
  --model evidence/wicker-shop-projection-model.json \
  --lidar evidence/wicker-shop-model-lidar-review.json \
  --context evidence/wicker-shop-context-review.json \
  --terrain-config terrain-config.json \
  --output placement-preflight.json
```

The optional terrain configuration uses the normal `terrain` and `sources`
objects. Raster paths resolve relative to the configuration file; terrain must
be in metres with an explicit ODN datum. Omitting the configuration leaves the
terrain check unknown. The report pins the model and both retained reviews,
and records the raster checksum, CRS, sampling method and coverage requests.

## Retained evidence results

| Diagnostic | Context-preferred orientation | Opposite orientation |
| --- | ---: | ---: |
| Bearing | −154.755640° | 25.244360° |
| Rear direction to mapped station | 16.72° | 163.28° |
| Rotated block cells | 657 | 658 |
| Hypothetical native chunks at fitted BNG origin | 4 | 4 |
| Tested block columns | 263 | 263 |
| Missing columns in available terrain tile | 263 | 263 |

Both fits use a local origin near **407562.970, 343583.938 BNG**, approximately
1.023 m from the mapped shop centroid in the placement template. These represent
different candidate anchors; the mapped centroid must not be substituted for the
fitted local origin without reviewing its effect on the model.

The retained roof self-fit suggests approximately **182.647 m ODN**, snapping
to grid level 183 with a +0.353 m offset. The proposed drawing label 182.50 m
still has an unverified datum. Production uses Python nearest-integer rounding
(exact half values round to the even integer); consequently 182.50 would snap
to 182. This one-block difference makes an independent floor/grading check
necessary before choosing a park floor.

The only recovered DTM tile spans BNG 407064–407200 / 343298–343367, covering
the Smiler review area. It has **zero shop coverage**. Missing terrain is recorded
as a failed coverage check, never replaced with zero elevation or a fabricated
grass platform. The recorded zero intersecting columns means none could be
evaluated, not that the floor is clear.

`evidence/wicker-shop-placement-preflight.json` retains these results. Both
orientations, the poor-boundary flag, unresolved handedness/assembly identity,
and zero accepted controls/checkpoints remain explicit. Next obtain a terrain
crop covering the shop and independent horizontal/floor measurements; rerun
this preflight before enabling the real placement entry in a park job.

Follow-up: the [provisional terrain section](wicker-shop-terrain-section.md)
recovers the original dated rasters and supplies complete shop coverage. It
retains one wall/terrain conflict at candidate floor 183 and provides a separate
review world at explicitly provisional floor 184. The missing-coverage result
above remains a record of the earlier Smiler-tile check.
