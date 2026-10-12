# Automatic element reconstruction

Automatic recipe contract v5 runs [survey landmark discovery](survey-landmark-discovery.md)
and a separate [registration qualification](registration-qualification.md)
preflight before component reconstruction. Both supported drawing adapters use
the same source-bound frame checks, and ordinary registrations now retain their
combined error budgets for contextual matching. Fresh controller work directories
are required on upgrade; an existing configured evidence store remains reusable.

The resort runner can now create area recipes and discovered component IDs from drawing PDFs without a hand-written recipe or per-object binding. It uses the existing explicit drawing registration bridge, compiler and ten-worker native cycle pipeline. Enable this once in the resort job:

```json
{
  "automatic_reconstruction": {
    "enabled": true,
    "manifest": "inputs/manifest.json",
    "references": "inputs/survey-landmarks.json",
    "terrain_config": "inputs/terrain.json",
    "max_pages": 10000,
    "max_features": 2500000
  }
}
```

Existing acquisition configuration, initial baseline and each area's accepted `bounds` and `bounds_crs` still apply. These are shared setup inputs, not per-element reconstruction instructions. Explicit `reconstruction_job` settings take precedence.

The shared manifest contains pinned planning sources and source policies; references contain independently surveyed landmarks. This mode currently supports the bridge's explicit PATH, PLAZA, WALL and ROOF annotation convention: exact CP identifiers, unique leader attachments, printed scale, three controls and two independent checkpoints. Ordinary contained surface labels now have a separate adapter; see [ordinary planning surfaces](ordinary-planning-surfaces.md). Other arbitrary planning annotations remain unsupported. Do not mark ordinary drawings as using this convention to force publication. Existing/as-built source state and roof vertical datum remain checked.

For each area the runner selects only checksum-matching acquired planning PDFs, registers and identifies supported objects, excludes whole objects outside the area boundary, and generates `automatic-reconstruction/recipe.json` and `features.jsonl`. No estimates are enabled. The compiler checks terrain, retained chunks, source provenance and material conflicts before the normal native cycle machinery runs. Registration, semantic and boundary failures are retained in reports rather than becoming geometry.

Shared inputs are pinned in both controller and area contracts. The bridge checks cached PDF and output hashes. Edited derived features or recipes fail resume instead of silently changing a dispatched cycle. Use a fresh work directory when intentionally changing inputs.

A discovered list cannot prove that every element in an area was identified. With no independent `required_component_ids`, a successfully exported automatic area stays `partial_area_preview`; its world is retained for subsequent areas. Supplying an established inventory permits the existing completeness checks to compare all required IDs and families. There are no interactive per-element approval prompts.

Run through the existing `voxel-resort-cycles` stages or `python -m voxel_mapper.area_cycles local --job job.json --max-cycles 20`. The existing Actions workflow needs no separate worker mode: automatic preparation feeds the same ten workers.

## Verified scope

Tests use a native fixture PDF containing explicit control marks and path, wall and roof callouts. They exercise automatic recipe creation, the real compiler, ten worker payloads, native assembly and a cold Bedrock block read. Missing independent checkpoints, unmatched area documents, proposed sheets, invalid boundaries and edited outputs are also tested.

This is supported-element automation, not full autonomous interpretation of the real park corpus. The actual Alton job has no accepted automatic source manifest, survey-landmark bundle or area boundaries wired in yet; no new Alton world is claimed. The ordinary surface adapter has audited two real Mutiny Bay sheets; independent placement and surface scope are still unresolved. Further ordinary-drawing adapters are needed for buildings and other components.

## Missing-evidence planning

When architectural interpretation is enabled, the area runner now prepares a
source-pinned reconstruction requirement queue before automatic recipe preparation.
See [reconstruction-evidence-queue.md](reconstruction-evidence-queue.md) for
dependencies, targeted source search terms, unchanged-input reuse and the real
Mutiny perimeter replay. The queue does not itself satisfy compiler evidence gates.
