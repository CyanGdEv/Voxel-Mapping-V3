"""Evidence scoring and conflict-aware voxel selection for park mapping."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
import math


_EVIDENCE_PRIORS = {
    "as_built": 0.98,
    "survey": 0.96,
    "lidar": 0.94,
    "aerial": 0.86,
    "planning": 0.72,
    "osm": 0.58,
    "inference": 0.35,
}


def evidence_confidence(
    source: Mapping[str, object],
    *,
    assumptions: Iterable[str] = (),
    voxel_size_m: float = 1.0,
    today: date | None = None,
) -> dict[str, object]:
    """Score evidence quality without presenting the score as factual accuracy.

    Explicit source confidence can override the source-class prior. Accuracy
    values reduce confidence when they are coarse relative to output voxels;
    stale evidence is mildly discounted. Each penalty is returned for audit.
    """
    if not math.isfinite(voxel_size_m) or voxel_size_m <= 0:
        raise ValueError("voxel_size_m must be positive")
    kind = str(source.get("evidence_type", "inference")).lower()
    score = float(source.get("confidence", _EVIDENCE_PRIORS.get(kind, 0.5)))
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("source confidence must be between 0 and 1")
    penalties: list[str] = []
    for key in ("horizontal_accuracy_m", "vertical_accuracy_m"):
        accuracy = source.get(key)
        if accuracy is not None:
            accuracy = float(accuracy)
            if not math.isfinite(accuracy) or accuracy < 0:
                raise ValueError(f"{key} must be a finite non-negative number")
            if accuracy > voxel_size_m:
                factor = min(1.0, voxel_size_m / accuracy)
                score *= factor
                penalties.append(f"{key}={accuracy:g}m exceeds voxel size")
    assumptions = tuple(assumptions)
    if assumptions:
        score *= 0.8 ** len(assumptions)
        penalties.append(f"{len(assumptions)} geometry assumption(s)")
    observed = source.get("observed_date")
    if observed:
        try:
            observed_date = date.fromisoformat(str(observed)[:10])
        except ValueError as exc:
            raise ValueError("observed_date must use ISO date format") from exc
        reference = today or datetime.now(timezone.utc).date()
        age_years = max(0.0, (reference - observed_date).days / 365.2425)
        # Discount slowly; old surveyed masonry remains useful, but park paths
        # and temporary layouts can change and should carry their age forward.
        decay = float(source.get("annual_confidence_decay", 0.025))
        if not math.isfinite(decay) or not 0 <= decay < 1:
            raise ValueError("annual_confidence_decay must be in [0, 1)")
        if age_years:
            score *= (1.0 - decay) ** age_years
            penalties.append(f"evidence age {age_years:.1f} years")
    return {"score": round(max(0.0, min(1.0, score)), 4), "evidence_type": kind,
            "source_id": source.get("id"), "penalties": penalties}


def summarize_voxel_conflicts(
    records: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Summarize competing feature records at the same voxel, ranked by evidence."""
    grouped: dict[tuple[int, int, int], list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        key = (int(record["x"]), int(record["y"]), int(record["z"]))
        grouped[key].append(record)
    conflicts = []
    for (x, y, z), entries in grouped.items():
        if len(entries) < 2:
            continue
        ranked = sorted(entries, key=lambda item: float(item.get("confidence", 0)), reverse=True)
        conflicts.append({"voxel": [x, y, z], "feature_count": len(entries),
                          "winner": ranked[0].get("feature"),
                          "winner_confidence": ranked[0].get("confidence", 0),
                          "alternatives": [
                              {"feature": e.get("feature"), "kind": e.get("kind"),
                               "confidence": e.get("confidence", 0)} for e in ranked[1:]
                          ]})
    return {"overlap_voxels": len(conflicts), "conflicts": conflicts}
