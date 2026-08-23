"""Art.Suleimanov1924."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageOps
from scipy import ndimage as ndi

from .algorithm import frangi_like, otsu_threshold, remove_small_objects
from .io import discover_frames, extract_frame_index, load_grayscale_frame
from .models import FrameInfo


def _component_elongation(coords: np.ndarray) -> float:
    if coords.shape[0] < 3:
        return 1.0
    centered = coords.astype(np.float32) - coords.mean(axis=0, keepdims=True)
    cov = np.cov(centered, rowvar=False)
    eigvals = np.linalg.eigvalsh(cov)
    major = float(max(eigvals[-1], 1e-6))
    minor = float(max(eigvals[0], 1e-6))
    return math.sqrt(major / minor)


def _global_orientation_ratio(mask: np.ndarray) -> float:
    coords = np.argwhere(mask)
    if coords.shape[0] < 5:
        return 1.0
    return _component_elongation(coords)


def quick_candidate_features(image: np.ndarray) -> dict[str, float]:
    vessel = frangi_like(image)
    threshold = max(otsu_threshold(vessel) * 0.82, float(np.percentile(vessel, 78)))
    mask = vessel >= threshold
    mask = ndi.binary_dilation(mask, structure=np.ones((2, 2)), iterations=1)
    mask = ndi.binary_closing(mask, structure=np.ones((3, 3)), iterations=2)
    mask = ndi.binary_opening(mask, structure=np.ones((2, 2)), iterations=1)
    mask = remove_small_objects(mask, min_size=16)

    labels, count = ndi.label(mask)
    elongated_components = 0
    elongated_pixels = 0
    component_count = 0
    top_elongation = 1.0

    for label_id in range(1, count + 1):
        coords = np.argwhere(labels == label_id)
        if coords.shape[0] < 16:
            continue
        component_count += 1
        elongation = _component_elongation(coords)
        top_elongation = max(top_elongation, elongation)
        if coords.shape[0] >= 35 and elongation >= 3.0:
            elongated_components += 1
            elongated_pixels += int(coords.shape[0])

    area_fraction = float(mask.mean())
    elongated_fraction = float(elongated_pixels / mask.size)
    orientation_ratio = _global_orientation_ratio(mask)
    score = (
        elongated_fraction * 120.0
        + max(orientation_ratio - 1.0, 0.0) * 4.0
        + elongated_components * 1.5
        - area_fraction * 30.0
        - component_count * 0.05
    )

    return {
        "auto_score": score,
        "mask_area_fraction": area_fraction,
        "elongated_fraction": elongated_fraction,
        "elongated_components": float(elongated_components),
        "component_count": float(component_count),
        "orientation_ratio": orientation_ratio,
        "top_component_elongation": top_elongation,
    }


def inspect_study(study_dir: Path) -> tuple[list[FrameInfo], list[dict[str, object]]]:
    frame_paths = discover_frames(study_dir)
    frames: list[FrameInfo] = []
    rows: list[dict[str, object]] = []

    for path in frame_paths:
        info = FrameInfo(
            frame_index=extract_frame_index(path),
            filename=path.name,
            path=path,
            source_type=path.suffix.lower().lstrip("."),
        )
        frames.append(info)
        image = load_grayscale_frame(path)
        features = quick_candidate_features(image)
        row: dict[str, object] = {
            "frame_index": info.frame_index,
            "filename": info.filename,
            "source_type": info.source_type,
        }
        row.update(features)
        rows.append(row)

    rows.sort(key=lambda row: float(row["auto_score"]), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["suggested_rank"] = rank
        row["suggested_use"] = "candidate_subbasal" if rank <= 12 else "review"

    return frames, rows


def write_inventory(rows: list[dict[str, object]], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "study_inventory.csv"
    xlsx_path = output_dir / "study_inventory.xlsx"

    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="inventory")

    return csv_path, xlsx_path


def write_selection_template(rows: list[dict[str, object]], output_dir: Path, top_n: int) -> Path:
    template_rows: list[dict[str, object]] = []
    ranked = sorted(rows, key=lambda row: float(row["auto_score"]), reverse=True)
    include_names = {row["filename"] for row in ranked[:top_n]}

    for row in ranked:
        template_rows.append(
            {
                "frame_index": row["frame_index"],
                "filename": row["filename"],
                "include": 0,
                "eye": "",
                "confidence": "",
                "depth_um": "",
                "suggested_rank": row["suggested_rank"],
                "note": "candidate_subbasal_review" if row["filename"] in include_names else row["suggested_use"],
                "auto_score": round(float(row["auto_score"]), 4),
            }
        )

    path = output_dir / "selection_template.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(template_rows[0].keys()))
        writer.writeheader()
        writer.writerows(template_rows)
    return path


def write_contact_sheet(frames: list[FrameInfo], rows: list[dict[str, object]], output_dir: Path, top_n: int = 18) -> Path:
    score_by_name = {str(row["filename"]): row for row in rows}
    top_frames = sorted(
        [frame for frame in frames if frame.filename in score_by_name],
        key=lambda frame: float(score_by_name[frame.filename]["auto_score"]),
        reverse=True,
    )[:top_n]

    thumb_w = 210
    thumb_h = 210
    label_h = 40
    cols = 3
    rows_n = max(1, math.ceil(len(top_frames) / cols))
    canvas = Image.new("L", (cols * thumb_w, rows_n * (thumb_h + label_h)), color=20)
    draw = ImageDraw.Draw(canvas)

    for idx, frame in enumerate(top_frames):
        image = Image.fromarray(load_grayscale_frame(frame.path).astype(np.uint8), mode="L")
        thumb = ImageOps.fit(image, (thumb_w, thumb_h), method=Image.Resampling.LANCZOS)
        x = (idx % cols) * thumb_w
        y = (idx // cols) * (thumb_h + label_h)
        canvas.paste(thumb, (x, y))
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=0)
        score = float(score_by_name[frame.filename]["auto_score"])
        label = f"idx {frame.frame_index} | {frame.source_type} | score {score:.2f}"
        draw.text((x + 6, y + thumb_h + 10), label, fill=255)

    path = output_dir / "inspect_contact_sheet.png"
    canvas.save(path)
    return path
