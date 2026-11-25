"""Train an optional cross-park ground-surface segmentation baseline.

Input datasets are ZIP bundles produced by prepare_ground_training.py or the
park annotation chip pack. All-ignore masks are skipped; they never become
false background examples. Requires the optional train dependencies.
"""
from __future__ import annotations

import argparse
import csv
import io
import hashlib
import json
import random
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


IGNORE = 255
DEFAULT_LABEL_MAP = {
    1: "grass_unspecified",
    2: "worn_grass_unlabelled",
    3: "dry_soil_unlabelled",
    4: "mud_unlabelled",
    5: "gravel_unlabelled",
    6: "stone_paving",
    7: "brick_paving",
    8: "asphalt",
    9: "paving_unspecified",
}


@dataclass
class Sample:
    sample_id: str
    park_id: str
    split_group: str
    image: np.ndarray
    labels: np.ndarray
    context: np.ndarray | None = None


def _decode_rgb(blob: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(blob)) as image:
        # The training contract is RGB. Four-band NAIP source chips keep their
        # raw 4-band image in the archive; the first three channels are used
        # here until all parks have comparable reviewed NIR inputs.
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _decode_labels(blob: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(blob)) as image:
        return np.asarray(image.convert("L"), dtype=np.uint8)


def _manifest_from_zip(archive: zipfile.ZipFile) -> dict:
    names = set(archive.namelist())
    if "manifest.json" not in names:
        raise ValueError("dataset ZIP needs a root manifest.json")
    return json.loads(archive.read("manifest.json"))


def _read_samples(dataset_path: Path, *, use_context=False) -> tuple[list[Sample], dict, dict]:
    samples: list[Sample] = []
    skipped_all_ignore = 0
    skipped_bad_shape = 0
    with zipfile.ZipFile(dataset_path) as archive:
        manifest = _manifest_from_zip(archive)
        label_map = {int(k): str(v) for k, v in
                     manifest.get("label_map", manifest.get("ground_surface_classes", DEFAULT_LABEL_MAP)).items()}
        # Ignore is a mask value, never a model output class.
        label_map.pop(IGNORE, None)
        park_default = manifest.get("park_id", manifest.get("park", "unknown_park"))
        if isinstance(park_default, dict):
            park_default = park_default.get("id", "unknown_park")
        records = manifest.get("samples")
        if records is None and "chip_index.csv" in archive.namelist():
            with archive.open("chip_index.csv") as stream:
                records = list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8")))
        if records is None:
            raise ValueError(f"{dataset_path}: manifest has no samples or chip_index.csv")

        for index, record in enumerate(records):
            image_name = record.get("image")
            label_name = record.get("labels")
            if not image_name or not label_name:
                continue
            try:
                rgb = _decode_rgb(archive.read(image_name))
                labels = _decode_labels(archive.read(label_name))
            except KeyError as exc:
                raise ValueError(f"{dataset_path}: missing sample file {exc}") from exc
            if rgb.shape[:2] != labels.shape:
                skipped_bad_shape += 1
                continue
            valid = labels != IGNORE
            if not np.any(valid):
                skipped_all_ignore += 1
                continue
            invalid = sorted(set(np.unique(labels[valid]).tolist()) - set(label_map))
            if invalid:
                raise ValueError(f"{dataset_path}: sample has labels absent from label_map: {invalid}")
            park_id = str(record.get("park_id") or park_default)
            group = str(record.get("split_group") or record.get("source_group") or
                        manifest.get("source_tile") or record.get("sample_id") or index)
            sample_id = str(record.get("sample_id") or f"{dataset_path.stem}:{index}")
            context = None
            if use_context and record.get("context"):
                from .multisource_chips import decode, CHANNELS
                if manifest.get("context_schema") != "voxel-multisource-v1" or tuple(manifest.get("context_channels", [])) != CHANNELS:
                    raise ValueError("Unsupported multisource manifest")
                if not record.get("georef") or not record.get("context_provenance"):
                    raise ValueError("Context sample requires georeference and provenance")
                context = decode(archive.read(record["context"]), *labels.shape)
            samples.append(Sample(sample_id, park_id, group, rgb, labels, context))
    return samples, label_map, {
        "source_zip": dataset_path.name,
        "labelled_samples": len(samples),
        "skipped_all_ignore": skipped_all_ignore,
        "skipped_shape_mismatch": skipped_bad_shape,
        "context_samples": sum(s.context is not None for s in samples),
    }


def _split(samples: list[Sample], validation_fraction: float, seed: int,
           holdout_park: str | None, validation_groups=None) -> tuple[list[Sample], list[Sample], dict]:
    parks = sorted({s.park_id for s in samples})
    if validation_groups:
        if holdout_park or len(parks) != 1:
            raise ValueError("Explicit validation groups require one park and no park holdout")
        selected = set(validation_groups)
        available = {s.split_group for s in samples}
        if selected - available or selected == available:
            raise ValueError("Validation groups must exist and leave training groups")
        return ([s for s in samples if s.split_group not in selected],
                [s for s in samples if s.split_group in selected],
                {"mode":"explicit_group", "validation_groups":sorted(selected)})
    if holdout_park:
        if holdout_park not in parks:
            raise ValueError(f"holdout park {holdout_park!r} has no reviewed labelled samples")
        train = [s for s in samples if s.park_id != holdout_park]
        valid = [s for s in samples if s.park_id == holdout_park]
        if not train:
            raise ValueError("park holdout leaves no training samples")
        return train, valid, {"mode": "whole_park", "holdout_park": holdout_park}

    if len(parks) >= 2:
        # Deterministic default: hold out the lexicographically last park ID.
        chosen = parks[-1]
        train = [s for s in samples if s.park_id != chosen]
        valid = [s for s in samples if s.park_id == chosen]
        return train, valid, {"mode": "whole_park", "holdout_park": chosen}

    groups = sorted({s.split_group for s in samples})
    if len(groups) < 2:
        raise ValueError("need at least two independent split_group values for leakage-safe validation")
    rng = random.Random(seed)
    rng.shuffle(groups)
    n_valid = max(1, min(len(groups) - 1, round(len(groups) * validation_fraction)))
    valid_groups = set(groups[:n_valid])
    train = [s for s in samples if s.split_group not in valid_groups]
    valid = [s for s in samples if s.split_group in valid_groups]
    return train, valid, {"mode": "source_group", "validation_groups": sorted(valid_groups)}


def _tile(rgb: np.ndarray, labels: np.ndarray, size: int, training: bool, context=None):
    height, width = labels.shape
    if height < size or width < size:
        ph,pw = max(0,size-height),max(0,size-width)
        rgb = np.pad(rgb,((0,ph),(0,pw),(0,0)),mode="edge")
        labels = np.pad(labels,((0,ph),(0,pw)),constant_values=IGNORE)
        if context is not None:
            context = np.pad(context,((0,ph),(0,pw),(0,0)),constant_values=0)
        height, width = labels.shape
    if training:
        top = random.randint(0, height - size)
        left = random.randint(0, width - size)
        if not np.any(labels[top:top + size, left:left + size] != IGNORE):
            valid_y, valid_x = np.where(labels != IGNORE)
            chosen = random.randrange(len(valid_y))
            top = min(max(0, int(valid_y[chosen]) - random.randrange(size)), height - size)
            left = min(max(0, int(valid_x[chosen]) - random.randrange(size)), width - size)
    else:
        top = max(0, (height - size) // 2)
        left = max(0, (width - size) // 2)
    rgb, labels = rgb[top:top + size, left:left + size], labels[top:top + size, left:left + size]
    if context is not None:
        context = context[top:top + size, left:left + size]
    if training:
        if random.random() < 0.5:
            rgb, labels = rgb[:, ::-1], labels[:, ::-1]
            if context is not None: context = context[:, ::-1]
        if random.random() < 0.5:
            rgb, labels = rgb[::-1, :], labels[::-1, :]
            if context is not None: context = context[::-1, :]
        turns = random.randrange(4)
        if turns:
            rgb, labels = np.rot90(rgb, turns), np.rot90(labels, turns)
            if context is not None: context = np.rot90(context, turns)
    rgb = np.ascontiguousarray(rgb)
    labels = np.ascontiguousarray(labels)
    return (rgb, labels) if context is None else (rgb, labels, np.ascontiguousarray(context))


def build_model(input_channels: int, num_classes: int):
    """Shared training/inference architecture; state-dict keys stay compatible."""
    import torch
    from torch import nn
    import torch.nn.functional as F
    if input_channels not in (3, 28) or not 1 <= num_classes <= 256:
        raise ValueError("Unsupported ground model dimensions")
    class ConvBlock(nn.Module):
        def __init__(self, in_ch: int, out_ch: int):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
                nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            )
        def forward(self, x):
            return self.layers(x)

    class SmallUNet(nn.Module):
        def __init__(self, output_classes: int):
            super().__init__()
            self.e1 = ConvBlock(input_channels, 16)
            self.e2 = ConvBlock(16, 32)
            self.e3 = ConvBlock(32, 64)
            self.mid = ConvBlock(64, 128)
            self.pool = nn.MaxPool2d(2)
            self.u3 = ConvBlock(128 + 64, 64)
            self.u2 = ConvBlock(64 + 32, 32)
            self.u1 = ConvBlock(32 + 16, 16)
            self.out = nn.Conv2d(16, output_classes, 1)
        def forward(self, x):
            a = self.e1(x)
            b = self.e2(self.pool(a))
            c = self.e3(self.pool(b))
            d = self.mid(self.pool(c))
            d = F.interpolate(d, size=c.shape[-2:], mode="bilinear", align_corners=False)
            d = self.u3(torch.cat([d, c], dim=1))
            d = F.interpolate(d, size=b.shape[-2:], mode="bilinear", align_corners=False)
            d = self.u2(torch.cat([d, b], dim=1))
            d = F.interpolate(d, size=a.shape[-2:], mode="bilinear", align_corners=False)
            return self.out(self.u1(torch.cat([d, a], dim=1)))

    return SmallUNet(num_classes)


def train(args: argparse.Namespace) -> dict:
    try:
        import torch
        from torch import nn
        import torch.nn.functional as F
    except ImportError as exc:
        raise SystemExit("Install optional dependencies with: pip install 'voxel-mapper[train]'") from exc

    from .multisource_chips import CHANNELS, GROUPS, empty, drop_groups, select_groups
    use_context = getattr(args,"multisource",False)
    context_groups = getattr(args,"context_group",None) or [name for name, _ in GROUPS]
    if set(context_groups) - {name for name, _ in GROUPS}:
        raise ValueError("Unknown context group")
    dropout = getattr(args,"context_dropout",0.2)
    if not 0 <= dropout <= 1:
        raise ValueError("Context dropout must be in [0,1]")
    input_names = ("red","green","blue") + (CHANNELS if use_context else ())
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output / "model.pt").exists():
        raise ValueError("Use a fresh output directory; refusing stale checkpoint reuse")
    context_rng = random.Random(args.seed+1001)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)

    samples, label_map, source_reports = [], None, []
    for path in args.dataset:
        current, current_map, report = _read_samples(path,use_context=use_context)
        with path.open("rb") as stream:
            report["dataset_sha256"] = hashlib.file_digest(stream,"sha256").hexdigest()
        if label_map is None:
            label_map = current_map
        elif current_map != label_map:
            raise ValueError("all datasets must use the same label_map IDs and names")
        samples.extend(current)
        source_reports.append(report)
    if use_context:
        for sample in samples:
            if sample.context is not None:
                sample.context = select_groups(sample.context, context_groups)
    if not samples:
        skipped = sum(item["skipped_all_ignore"] for item in source_reports)
        raise ValueError(f"no reviewed labels found; {skipped} all-ignore samples were skipped")

    train_samples, valid_samples, split_report = _split(
        samples, args.validation_fraction, args.seed, args.holdout_park,
        getattr(args,"validation_group",None)
    )
    if not valid_samples:
        raise ValueError("validation split is empty")
    if use_context and not all(any(s.context is not None and np.any(s.context[s.labels != IGNORE]) for s in split) for split in (train_samples,valid_samples)):
        raise ValueError("Multisource training requires nonempty context in both training and validation splits")
    if max(label_map) >= args.num_classes:
        raise ValueError("--num-classes must be greater than the largest label ID")

    counts = np.zeros(args.num_classes, dtype=np.int64)
    for sample in train_samples:
        hist = np.bincount(sample.labels[sample.labels != IGNORE], minlength=args.num_classes)
        counts += hist[:args.num_classes]
    weights = np.ones(args.num_classes, dtype=np.float32)
    present = counts > 0
    weights[present] = (counts[present].sum() / counts[present]) ** 0.25
    weights[present] /= weights[present].mean()

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model = build_model(len(input_names), args.num_classes).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.CrossEntropyLoss(
        weight=torch.tensor(weights, dtype=torch.float32, device=device),
        ignore_index=IGNORE,
    )

    def to_batch(items, training):
        xs, ys = [], []
        for sample in items:
            if use_context:
                context = sample.context if sample.context is not None else empty(*sample.labels.shape)
                rgb, mask, context = _tile(sample.image, sample.labels, args.patch_size, training, context)
                if training: context = drop_groups(context,context_rng,dropout)
                values = np.concatenate((rgb.astype(np.float32)/255,context),axis=2)
            else:
                rgb, mask = _tile(sample.image, sample.labels, args.patch_size, training)
                values = rgb.astype(np.float32)/255
            xs.append(torch.from_numpy(values.copy()).permute(2, 0, 1))
            ys.append(torch.from_numpy(mask.copy()).long())
        return torch.stack(xs).to(device), torch.stack(ys).to(device)

    def confusion_for(items):
        matrix = np.zeros((args.num_classes, args.num_classes), dtype=np.int64)
        model.eval()
        with torch.no_grad():
            for sample in items:
                h, w = sample.labels.shape
                # Keep edge pixels at their original scale. Pad RGB by repeating
                # edge pixels and ignore-pad labels so padding never enters metrics.
                for y in range(0, h, args.patch_size):
                    for x in range(0, w, args.patch_size):
                        rgb = sample.image[y:y + args.patch_size, x:x + args.patch_size]
                        mask = sample.labels[y:y + args.patch_size, x:x + args.patch_size]
                        pad_h = args.patch_size - rgb.shape[0]
                        pad_w = args.patch_size - rgb.shape[1]
                        if pad_h or pad_w:
                            rgb = np.pad(rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
                            mask = np.pad(mask, ((0, pad_h), (0, pad_w)), mode="constant",
                                          constant_values=IGNORE)
                        values = rgb.astype(np.float32)/255
                        if use_context:
                            context = (sample.context[y:y+args.patch_size,x:x+args.patch_size] if sample.context is not None else empty(min(args.patch_size,h-y),min(args.patch_size,w-x)))
                            if pad_h or pad_w:
                                context = np.pad(context,((0,pad_h),(0,pad_w),(0,0)),constant_values=0)
                            values = np.concatenate((values,context),axis=2)
                        xb = torch.from_numpy(values.copy()).permute(2, 0, 1).unsqueeze(0).to(device)
                        pred = model(xb).argmax(1).squeeze(0).cpu().numpy()
                        valid = mask != IGNORE
                        if np.any(valid):
                            pairs = mask[valid].astype(np.int64) * args.num_classes + pred[valid].astype(np.int64)
                            matrix += np.bincount(pairs, minlength=args.num_classes**2).reshape(args.num_classes, args.num_classes)
        return matrix

    best_validation_mean_iou = -1.0
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = list(range(len(train_samples)))
        random.shuffle(order)
        train_loss_sum, steps = 0.0, 0
        for start in range(0, len(order), args.batch_size):
            batch = [train_samples[i] for i in order[start:start + args.batch_size]]
            xb, yb = to_batch(batch, True)
            if not torch.any(yb != IGNORE):
                continue
            optimizer.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            optimizer.step()
            train_loss_sum += float(loss.detach().cpu())
            steps += 1
        cm = confusion_for(valid_samples)
        valid_pixels = int(cm.sum())
        valid_loss = None
        if valid_pixels:
            pixel_accuracy = float(cm.trace() / valid_pixels)
            intersections = np.diag(cm).astype(np.float64)
            unions = cm.sum(axis=0) + cm.sum(axis=1) - intersections
            # Compare the same reviewed classes regardless of predicted classes.
            defined = cm.sum(axis=1) > 0
            mean_iou = float(np.mean(intersections[defined] / unions[defined])) if np.any(defined) else None
        else:
            pixel_accuracy = None
            mean_iou = None
        if steps == 0:
            raise ValueError("training yielded no labelled patches; verify the masks and split")
        record = {
            "epoch": epoch,
            "train_loss": train_loss_sum / max(steps, 1),
            "validation_labelled_pixels": valid_pixels,
            "validation_pixel_accuracy": pixel_accuracy,
            "validation_mean_iou": mean_iou,
        }
        history.append(record)
        # Without reviewed validation pixels, do not select a checkpoint.
        if valid_pixels and mean_iou is not None and mean_iou > best_validation_mean_iou:
            best_validation_mean_iou = mean_iou
            torch.save({"state_dict": model.state_dict(), "num_classes": args.num_classes,
                        "class_map": label_map, "input_channels": len(input_names), "input_names": input_names,
                        "context_groups":context_groups if use_context else [],
                        "context_schema": "voxel-multisource-v1" if use_context else None}, args.output / "model.pt")

    checkpoint = args.output / "model.pt"
    best_metric = None
    if checkpoint.exists():
        saved = torch.load(checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(saved["state_dict"])
        best_metric = best_validation_mean_iou
    final_cm = confusion_for(valid_samples)
    per_class = {}
    for class_id, name in sorted(label_map.items()):
        tp = int(final_cm[class_id, class_id])
        fp = int(final_cm[:, class_id].sum() - tp)
        fn = int(final_cm[class_id, :].sum() - tp)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        iou = tp / (tp + fp + fn) if tp + fp + fn else None
        per_class[str(class_id)] = {"name": name, "precision": precision, "recall": recall,
                                    "iou": iou, "labelled_pixels": int(final_cm[class_id, :].sum())}
    report = {
        "schema": "voxel-ground-segmentation-training-v1",
        "status": "trained" if final_cm.sum() else "no_validation_labels_checkpoint_not_saved",
        "device": str(device),
        "class_map": {str(k): v for k, v in sorted(label_map.items())},
        "split": split_report,
        "input_names": list(input_names),
        "mode": "multisource" if use_context else "rgb",
        "seed": args.seed,
        "context_dropout": dropout if use_context else 0,
        "context_groups": context_groups if use_context else [],
        "train_ids": [[s.park_id,s.split_group,s.sample_id] for s in train_samples],
        "validation_ids": [[s.park_id,s.split_group,s.sample_id] for s in valid_samples],
        "train_samples": len(train_samples),
        "validation_samples": len(valid_samples),
        "sources": source_reports,
        "training": {"epochs": args.epochs, "batch_size": args.batch_size,
                     "patch_size": args.patch_size, "learning_rate": args.learning_rate,
                     "best_validation_mean_iou": best_validation_mean_iou if best_metric is not None else None,
                     "best_validation_pixel_accuracy": float(final_cm.trace()/final_cm.sum()) if final_cm.sum() else None},
        "history": history,
        "validation_confusion_matrix": final_cm.tolist(),
        "per_class": per_class,
        "limitations": [
            "This baseline learns ground-surface labels only; semantic object classes need a separate reviewed label map.",
            "GIS and LiDAR are context only; reviewed masks remain the targets. Missing context uses zero validity. Fourth NAIP band is not used.",
            "A park holdout measures transfer only for classes represented by reviewed pixels in that held-out park.",
            "No model is trained from all-ignore samples.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "training-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, action="append", required=True,
                        help="Dataset ZIP; repeat for multiple parks/datasets")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-park", help="Evaluate transfer to this park ID")
    parser.add_argument("--validation-group", action="append", help="Fixed held-out source/area group; repeat as needed. Caller must verify geographic separation.")
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--num-classes", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--patch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--multisource", action="store_true", help="Use aligned GIS and LiDAR context chips")
    parser.add_argument("--context-dropout", type=float, default=0.2)
    parser.add_argument("--context-group", action="append", help="Retain only these contextual groups for ablation; repeat as needed")
    args = parser.parse_args()
    if not 0 < args.validation_fraction < 1:
        parser.error("--validation-fraction must be between 0 and 1")
    if args.patch_size < 64 or args.patch_size % 16:
        parser.error("--patch-size must be at least 64 and divisible by 16")
    args.output.mkdir(parents=True, exist_ok=True)
    report = train(args)
    print(json.dumps({"status": report["status"], "device": report["device"],
                      "train_samples": report["train_samples"],
                      "validation_samples": report["validation_samples"],
                      "report": str(args.output / "training-report.json")}))


if __name__ == "__main__":
    main()
