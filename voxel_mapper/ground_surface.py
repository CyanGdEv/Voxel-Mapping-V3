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


def assess_lawn_column(cell, *, surface_offset_m, max_surface_height_m=.05,
                       max_vertical_residual_m=.1, allow_paving_roof_only=False, point_evidence=None):
    """Propose a bounded repair from reviewed lawn + measured heights.

    No evidence is accepted here. Native observations must cover the complete
    column above terrain; trees, walls, fluids and uncertain geometry survive.
    """
    def reject(reason):return {"status":"withheld","reason":reason,"edits":[]}
    if cell.get('label') not in ((1,9) if allow_paving_roof_only else (1,)) or not cell.get('safe_interior'):
        return reject('outside_reviewed_surface_interior' if allow_paving_roof_only else 'outside_reviewed_lawn_interior')
    if cell.get('block_entities') or not cell.get('supported_storage',False):
        return reject('protected_or_unsupported_native_column')
    dtm,dsm=cell.get('dtm'),cell.get('dsm')
    same_cell=(point_evidence is not None and (point_evidence.get('x'),point_evidence.get('z'))==(cell['x'],cell['z']))
    if same_cell:
        classes={int(k) for k,v in point_evidence.get('class_counts',{}).items() if v}
        if classes & {6,9,17}:return reject('classified_structure_or_water')
        maximum=point_evidence.get('all_z_max')
        if dtm is not None and maximum is not None and math.isfinite(dtm) and math.isfinite(maximum) and maximum-dtm>.15+1e-9:
            return reject('observed_elevated_returns')
    point_supported=same_cell and direct_ground_support(point_evidence)
    if point_supported:
        median=point_evidence['ground_z_median']
        if dtm is not None and math.isfinite(dtm) and abs(dtm-median)>.15+1e-9:
            return reject('conflicting_terrain_evidence')
        if dsm is not None and math.isfinite(dsm) and dsm-median>.15+1e-9:
            return reject('conflicting_elevated_raster_surface')
        dtm=median
        surface=point_evidence['all_z_max']
    else:
        if dtm is None or dsm is None or not all(math.isfinite(v) for v in (dtm,dsm)):
            return reject('missing_height_evidence')
        if dsm<dtm:return reject('negative_surface_height_unknown')
        if dsm-dtm>max_surface_height_m:return reject('measured_above_ground_geometry')
        surface=dsm
    y=int(math.floor(dtm+.5))-int(surface_offset_m)-1
    if surface_offset_m!=int(surface_offset_m) or abs(y+1+surface_offset_m-dtm)>max_vertical_residual_m:
        return reject('vertical_quantization_residual')
    profile={int(k):v for k,v in cell.get('native_profile',{}).items()}
    top=cell.get('native_top_y')
    if type(top) is not int or not y<=top<=y+4 or any(k not in profile for k in range(y-1,top+2)):
        return reject('incomplete_or_high_native_geometry')
    if profile[top+1]!='minecraft:air':return reject('stale_native_top')
    paving={'minecraft:stone_bricks','minecraft:mossy_stone_bricks','minecraft:cracked_stone_bricks'}
    roof={'minecraft:deepslate_tiles','minecraft:cracked_deepslate_tiles'}
    accepted_floor=(paving|{'minecraft:brick_block','minecraft:stone','minecraft:smooth_stone','minecraft:andesite','minecraft:polished_andesite','minecraft:gray_concrete'}) if cell['label']==9 else paving|{'minecraft:grass_block'}
    if profile[y] not in accepted_floor:
        return reject('unverified_ground_material')
    if profile[y-1] not in paving|{'minecraft:dirt','minecraft:dirt_with_roots','minecraft:coarse_dirt','minecraft:stone','minecraft:grass_block'}:
        return reject('unsupported_ground_support')
    if any(profile[k] not in roof|{'minecraft:air'} for k in range(y+1,top+1)):
        return reject('retained_structure_vegetation_or_water')
    x,z=cell['x'],cell['z'];edits=[]
    if cell['label']==1 and profile[y]!='minecraft:grass_block':
        edits.append({'xyz':[x,y,z],'before':profile[y],'after':'minecraft:grass_block','source_type':'reviewed_mask'})
    for k in range(y+1,top+1):
        if profile[k] in roof:
            edits.append({'xyz':[x,k,z],'before':profile[k],'after':'minecraft:air','source_type':'measured_surface_conflict'})
    return {'status':'candidate' if edits else 'already_matches','reason':'reviewed_paving_and_low_measured_surface' if cell['label']==9 else 'reviewed_lawn_and_low_measured_surface',
            'edits':edits,'height_update':{'xz':[x,z],'before':top+1,'after':y+1},
            'height_evidence_basis':'classified_cell_returns' if point_supported else 'raster_pair',
            'before_surface_evidence_residual_m':abs(top+1+surface_offset_m-surface),
            'after_surface_evidence_residual_m':abs(y+1+surface_offset_m-surface),
            'before_dsm_residual_m':None if point_supported else abs(top+1+surface_offset_m-dsm),
            'after_dsm_residual_m':None if point_supported else abs(y+1+surface_offset_m-dsm)}


def direct_ground_support(record):
    """Strict observed-return support, not a calibrated absence probability."""
    try:
        classes={int(k):v for k,v in record['class_counts'].items()}
        counts=[record[k] for k in ('unique_returns','ground_returns','first_ground_returns','excluded_points')]
        if any(type(v) is not int or v<0 for v in counts):return False
        if any(type(v) is not int or v<0 for v in classes.values()):return False
        total,ground,first,excluded=counts
        heights=[record[k] for k in ('ground_z_median','ground_z_range','all_z_min','all_z_max')]
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in heights):return False
        median,spread,minimum,maximum=heights
        return (excluded==0 and 4<=first<=ground<=total and ground==classes.get(2,0)
                and sum(classes.values())==total and set(classes)<={1,2}
                and sorted(set(record['first_ground_quadrants']))==[0,1,2,3]
                and .5-1e-9<=record['first_ground_x_span_m']<=1
                and .5-1e-9<=record['first_ground_z_span_m']<=1
                and 0<=spread<=.15+1e-9 and minimum<=median<=maximum
                and maximum-median<=.15+1e-9 and median-minimum<=.15+1e-9)
    except (KeyError,TypeError,ValueError):return False
