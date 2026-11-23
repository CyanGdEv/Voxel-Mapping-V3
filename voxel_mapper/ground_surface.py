"""Evidence-aware ground-surface classification and material resolution.

This module deliberately does not infer material from RGB thresholds. Aerial
colour varies with shadows, season, moisture and image processing; class labels
must come from reviewed training masks or a calibrated model. LiDAR is used to
identify ground returns and terrain shape, not to guess the surface material.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math


IGNORE = 255
SURFACE_CLASSES = {
    1: "grass_unspecified",
    2: "worn_grass",
    3: "dry_soil",
    4: "mud",
    5: "gravel",
    6: "stone_paving",
    7: "brick_paving",
    8: "asphalt",
    9: "paving_unspecified",
    10: "unknown_ground",
    IGNORE: "ignore_unlabelled",
}

# Suggested Minecraft material targets. Keeping this table separate from
# classification allows a park palette to change without relabelling imagery.
DEFAULT_BLOCKS = {
    "grass_unspecified": "minecraft:grass_block",
    "worn_grass": "minecraft:coarse_dirt",
    "dry_soil": "minecraft:dirt",
    "mud": "minecraft:mud",
    "gravel": "minecraft:gravel",
    "stone_paving": "minecraft:stone_bricks",
    "brick_paving": "minecraft:bricks",
    "asphalt": "minecraft:gray_concrete",
}


@dataclass(frozen=True)
class SurfaceEvidence:
    """One model or reviewed-label vote for a ground cell."""

    label: str
    confidence: float
    source_id: str
    source_type: str
    is_ground: bool = True


def resolve_surface(
    votes: Iterable[SurfaceEvidence],
    *,
    minimum_confidence: float = 0.65,
    minimum_margin: float = 0.12,
) -> dict[str, object]:
    """Fuse labelled/model votes; return unknown when evidence is weak or tied.

    Non-ground votes (for example LiDAR canopy/building returns) are excluded.
    Scores are weighted by confidence and evidence type. Direct reviewed masks,
    calibrated imagery predictions and planning context have different weights;
    LiDAR ground classification only gates whether a cell is a ground candidate.
    """
    if not 0 <= minimum_confidence <= 1 or not 0 <= minimum_margin <= 1:
        raise ValueError("confidence thresholds must be between 0 and 1")
    type_weights = {"reviewed_mask": 1.0, "calibrated_imagery": 0.85,
                    "planning_context": 0.45, "lidar_ground": 0.0}
    totals: dict[str, float] = defaultdict(float)
    sources: dict[str, list[str]] = defaultdict(list)
    raw_confidence: dict[str, float] = defaultdict(float)
    vote_count: dict[str, int] = defaultdict(int)
    ground_evidence = False
    for vote in votes:
        if not math.isfinite(vote.confidence) or not 0 <= vote.confidence <= 1:
            raise ValueError("vote confidence must be between 0 and 1")
        if not vote.is_ground:
            continue
        ground_evidence = True
        if vote.label not in DEFAULT_BLOCKS:
            # A LiDAR ground flag may establish that the cell is terrain, but it
            # cannot establish whether it is mud, grass, gravel or paving.
            continue
        weight = type_weights.get(vote.source_type, 0.0)
        if weight:
            totals[vote.label] += vote.confidence * weight
            raw_confidence[vote.label] += vote.confidence
            vote_count[vote.label] += 1
            sources[vote.label].append(vote.source_id)
    if not ground_evidence:
        return {"label": "unknown_ground", "confidence": 0.0,
                "block": None, "reason": "no ground evidence"}
    if not totals:
        return {"label": "unknown_ground", "confidence": 0.0,
                "block": None, "reason": "LiDAR/geometry confirms ground, material unlabelled"}
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    total_weight = sum(totals.values())
    best_label, best_weight = ranked[0]
    agreement = best_weight / total_weight
    quality = raw_confidence[best_label] / vote_count[best_label]
    confidence = agreement * quality
    margin = (best_weight - (ranked[1][1] if len(ranked) > 1 else 0.0)) / total_weight
    if confidence < minimum_confidence or margin < minimum_margin:
        return {"label": "unknown_ground", "confidence": round(confidence, 4),
                "block": None, "reason": "conflicting or low-confidence material evidence",
                "candidates": [{"label": label, "weight": round(weight, 4)} for label, weight in ranked]}
    return {"label": best_label, "confidence": round(confidence, 4),
            "block": DEFAULT_BLOCKS[best_label], "reason": "evidence threshold passed",
            "sources": sorted(set(sources[best_label]))}


def lidar_is_ground(classification: int) -> bool:
    """Return whether an ASPRS LiDAR class is a terrain-ground return (class 2)."""
    return int(classification) == 2


def validate_label_codes(labels: Iterable[int]) -> dict[str, object]:
    """Summarize label coverage and flag classes with no reviewed examples."""
    counts: dict[int, int] = defaultdict(int)
    for raw in labels:
        value = int(raw)
        if value not in SURFACE_CLASSES:
            raise ValueError(f"unknown ground-surface label code: {value}")
        counts[value] += 1
    present = {code for code, count in counts.items() if count and code != IGNORE}
    required = set(SURFACE_CLASSES) - {IGNORE, 10}
    return {
        "class_counts": {str(code): counts.get(code, 0) for code in SURFACE_CLASSES},
        "missing_reviewed_classes": [SURFACE_CLASSES[code] for code in sorted(required - present)],
        "ignored_cells": counts.get(IGNORE, 0),
        "material_inference_policy": "unlabelled and low-confidence cells remain unknown",
    }
