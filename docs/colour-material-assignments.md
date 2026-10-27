# Colour-based material assignments

The aerial job can now assign a draft material and block palette from RGB appearance, as requested. Set `material_mode` to `colour_appearance`; the updated Wicker and adaptive-cycle examples enable it. Omitted mode retains the earlier `suggest_only` behavior.

Green cells receive a grass/moss vegetation proxy. Blue cells receive a water proxy. Other non-shadow cells receive the nearest existing user-guided paving/timber palette in CIELAB colour space. Within a palette, the primary block is the visually closest constituent; the full block mix and its weights are retained. Dark/shadow cells and insufficient opaque samples stay unassigned.

These are actual **provisional material assignments**, rather than just a ranked candidate list. They are colour-based guesses: roofs, paving, gravel, timber and bare ground can look alike, and green tree canopy is not distinguished from green ground. There is no claim of independently verified material identity. The user-authorized appearance rule does not turn its own guesses into neural training labels.

Run the desktop **Aerial RGB / material research** job with the updated example, or:

```sh
python -m voxel_mapper.aerial_material_research --config request.json --output material-run-001 --cache web-cache
```

Outputs:

- `materials.html`: source RGB beside the assigned material preview.
- `material-map.png`: colour-coded assigned palettes, with a legend and unassigned shadows hatched.
- `material-assignments.geojson`: WGS84 sampling-cell material layer, with block IDs, weights, source image hash and assignment basis.
- `material-assignments.csv` and `.jsonl`: portable assignment tables.

The original `material-candidates.jsonl` and RGB observations remain unchanged. Assignment geometry is explicitly a sample grid, not extracted path or building boundaries. No Minecraft blocks are written by this job. Physical registration and the existing reviewed-material acceptance remain separate; `material_verified` and `training_eligible` stay false.

The desktop remembers the assignment summary/hash. The adaptive cycle retains the material result alongside its aerial source observations. Existing verified source-pair data still controls neural fitting; changing the appearance mode does not retrain the checkpoint.

On the retained Wicker-area image, the run assigned 237 cells and withheld 19 shadow cells: 78 vegetation, 65 gravel, 56 asphalt, 19 paving stones, 12 concrete, 3 compacted ground, 3 setts and 1 sand. The original RGB observation hash is unchanged. This is the same Esri imagery documented in the previous stage, not newly acquired Bing imagery. The assignments were produced offline.

The source update is not a rebuilt Windows EXE. See `evidence/colour-material-assignment-validation.json` for source pins, test results and the real research-cycle checkpoint check.
