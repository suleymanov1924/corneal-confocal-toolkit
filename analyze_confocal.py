"""Art.Suleimanov1924."""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi


FIELD_SIZE_UM = 400.0
IMAGE_SIZE_PX = 384
PIXEL_SIZE_UM = FIELD_SIZE_UM / IMAGE_SIZE_PX
FULL_AREA_MM2 = (FIELD_SIZE_UM / 1000.0) ** 2


@dataclass(frozen=True)
class FrameSpec:
    idx: int
    eye: str
    depth_um: float
    confidence: str


FRAME_SPECS = [
    FrameSpec(2, "OD", 99, "high"),
    FrameSpec(3, "OD", 99, "high"),
    FrameSpec(11, "OD", 91, "medium"),
    FrameSpec(12, "OD", 97, "high"),
    FrameSpec(13, "OD", 97, "high"),
    FrameSpec(14, "OD", 97, "high"),
    FrameSpec(15, "OD", 84, "high"),
    FrameSpec(16, "OD", 96, "high"),
    FrameSpec(19, "OD", 84, "medium"),
    FrameSpec(20, "OD", 100, "high"),
    FrameSpec(36, "OS", 31, "high"),
    FrameSpec(37, "OS", 17, "high"),
    FrameSpec(42, "OS", 4, "high"),
    FrameSpec(43, "OS", 4, "medium"),
]


def natural_index(path: Path) -> int:
    match = re.search(r"\((\d+)\)", path.name)
    if not match:
        raise ValueError(f"Cannot parse index from {path.name}")
    return int(match.group(1))


def load_frame(path: Path) -> np.ndarray:
    image = Image.open(path).convert("L")
    data = np.asarray(image, dtype=np.float32)
    return data[:IMAGE_SIZE_PX, :IMAGE_SIZE_PX]


def rescale01(image: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(image, [1, 99.7])
    if hi <= lo:
        return np.zeros_like(image, dtype=np.float32)
    out = (image - lo) / (hi - lo)
    return np.clip(out, 0.0, 1.0)


def frangi_like(image: np.ndarray, sigmas=(1.2, 1.8, 2.5, 3.2)) -> np.ndarray:
    img = rescale01(image)
    vesselness = np.zeros_like(img, dtype=np.float32)

    for sigma in sigmas:
        ixx = ndi.gaussian_filter(img, sigma=sigma, order=(0, 2)) * sigma * sigma
        ixy = ndi.gaussian_filter(img, sigma=sigma, order=(1, 1)) * sigma * sigma
        iyy = ndi.gaussian_filter(img, sigma=sigma, order=(2, 0)) * sigma * sigma

        tmp = np.sqrt((ixx - iyy) ** 2 + 4.0 * (ixy ** 2))
        l1 = 0.5 * (ixx + iyy + tmp)
        l2 = 0.5 * (ixx + iyy - tmp)

        swap = np.abs(l1) > np.abs(l2)
        lam1 = np.where(swap, l2, l1)
        lam2 = np.where(swap, l1, l2)

        rb = np.divide(np.abs(lam1), np.abs(lam2) + 1e-6)
        s2 = lam1 * lam1 + lam2 * lam2
        beta = 0.5
        c = max(np.percentile(np.sqrt(s2), 90), 1e-3)
        plate = np.exp(-(rb * rb) / (2.0 * beta * beta))
        blob = 1.0 - np.exp(-(s2) / (2.0 * c * c))
        score = plate * blob
        score[lam2 > 0] = 0.0
        vesselness = np.maximum(vesselness, score.astype(np.float32))

    vesselness = ndi.gaussian_filter(vesselness, 0.8)
    return rescale01(vesselness)


def otsu_threshold(image: np.ndarray) -> float:
    hist, bins = np.histogram(image.ravel(), bins=256, range=(0.0, 1.0))
    hist = hist.astype(np.float64)
    prob = hist / max(hist.sum(), 1.0)
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    mu_t = mu[-1]

    sigma_b = (mu_t * omega - mu) ** 2 / (omega * (1.0 - omega) + 1e-12)
    idx = int(np.nanargmax(sigma_b))
    return bins[min(idx + 1, len(bins) - 1)]


def remove_small_objects(mask: np.ndarray, min_size: int) -> np.ndarray:
    labels, count = ndi.label(mask)
    if count == 0:
        return mask
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_size
    keep[0] = False
    return keep[labels]


def thin_zhang_suen(binary: np.ndarray) -> np.ndarray:
    img = binary.astype(np.uint8).copy()
    changed = True
    while changed:
        changed = False
        to_zero: list[tuple[int, int]] = []
        rows, cols = img.shape
        for i in range(1, rows - 1):
            for j in range(1, cols - 1):
                p1 = img[i, j]
                if p1 != 1:
                    continue
                p2 = img[i - 1, j]
                p3 = img[i - 1, j + 1]
                p4 = img[i, j + 1]
                p5 = img[i + 1, j + 1]
                p6 = img[i + 1, j]
                p7 = img[i + 1, j - 1]
                p8 = img[i, j - 1]
                p9 = img[i - 1, j - 1]
                neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                transitions = sum(
                    (neighbors[k] == 0 and neighbors[(k + 1) % 8] == 1)
                    for k in range(8)
                )
                count = sum(neighbors)
                if not (2 <= count <= 6):
                    continue
                if transitions != 1:
                    continue
                if p2 * p4 * p6 != 0:
                    continue
                if p4 * p6 * p8 != 0:
                    continue
                to_zero.append((i, j))
        if to_zero:
            changed = True
            for i, j in to_zero:
                img[i, j] = 0

        to_zero = []
        for i in range(1, rows - 1):
            for j in range(1, cols - 1):
                p1 = img[i, j]
                if p1 != 1:
                    continue
                p2 = img[i - 1, j]
                p3 = img[i - 1, j + 1]
                p4 = img[i, j + 1]
                p5 = img[i + 1, j + 1]
                p6 = img[i + 1, j]
                p7 = img[i + 1, j - 1]
                p8 = img[i, j - 1]
                p9 = img[i - 1, j - 1]
                neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                transitions = sum(
                    (neighbors[k] == 0 and neighbors[(k + 1) % 8] == 1)
                    for k in range(8)
                )
                count = sum(neighbors)
                if not (2 <= count <= 6):
                    continue
                if transitions != 1:
                    continue
                if p2 * p4 * p8 != 0:
                    continue
                if p2 * p6 * p8 != 0:
                    continue
                to_zero.append((i, j))
        if to_zero:
            changed = True
            for i, j in to_zero:
                img[i, j] = 0
    return img.astype(bool)


def prune_spurs(skeleton: np.ndarray, iterations: int = 6) -> np.ndarray:
    result = skeleton.copy()
    kernel = np.array(
        [
            [1, 1, 1],
            [1, 10, 1],
            [1, 1, 1],
        ],
        dtype=np.uint8,
    )
    for _ in range(iterations):
        conv = ndi.convolve(result.astype(np.uint8), kernel, mode="constant", cval=0)
        endpoints = result & (conv == 11)
        result = result & ~endpoints
    return result


def neighbor_count(binary: np.ndarray) -> np.ndarray:
    kernel = np.ones((3, 3), dtype=np.uint8)
    return ndi.convolve(binary.astype(np.uint8), kernel, mode="constant", cval=0) - binary


def box_counting_dimension(binary: np.ndarray) -> float:
    pixels = binary.astype(bool)
    if pixels.sum() < 8:
        return float("nan")

    sizes = [2, 4, 8, 16, 32, 64]
    counts = []
    valid_sizes = []
    for size in sizes:
        h = int(math.ceil(pixels.shape[0] / size))
        w = int(math.ceil(pixels.shape[1] / size))
        pad_h = h * size - pixels.shape[0]
        pad_w = w * size - pixels.shape[1]
        padded = np.pad(pixels, ((0, pad_h), (0, pad_w)), mode="constant")
        blocks = padded.reshape(h, size, w, size).any(axis=(1, 3))
        count = int(blocks.sum())
        if count > 0:
            counts.append(count)
            valid_sizes.append(size)

    if len(counts) < 2:
        return float("nan")

    x = np.log(1.0 / np.asarray(valid_sizes, dtype=np.float64))
    y = np.log(np.asarray(counts, dtype=np.float64))
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def trace_segments(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    coords = list(map(tuple, np.argwhere(skeleton)))
    pixel_set = set(coords)

    def neighbors(node: tuple[int, int]) -> list[tuple[int, int]]:
        i, j = node
        out = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                nxt = (i + di, j + dj)
                if nxt in pixel_set:
                    out.append(nxt)
        return out

    degrees = {node: len(neighbors(node)) for node in coords}
    nodes = {node for node, degree in degrees.items() if degree != 2}
    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    segments: list[list[tuple[int, int]]] = []

    def walk(start: tuple[int, int], nxt: tuple[int, int]) -> list[tuple[int, int]]:
        segment = [start, nxt]
        prev = start
        curr = nxt
        while curr not in nodes:
            next_candidates = [p for p in neighbors(curr) if p != prev]
            if not next_candidates:
                break
            prev, curr = curr, next_candidates[0]
            segment.append(curr)
        return segment

    for node in nodes:
        for nxt in neighbors(node):
            edge = tuple(sorted((node, nxt)))
            if edge in visited_edges:
                continue
            segment = walk(node, nxt)
            for a, b in zip(segment, segment[1:]):
                visited_edges.add(tuple(sorted((a, b))))
            segments.append(segment)

    return segments


def path_length_px(points: list[tuple[int, int]]) -> float:
    if len(points) < 2:
        return 0.0
    pts = np.asarray(points, dtype=np.float32)
    steps = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(axis=1))
    return float(steps.sum())


def skeleton_length_px(skeleton: np.ndarray) -> float:
    total = 0.0
    rows, cols = skeleton.shape
    for i in range(rows):
        for j in range(cols):
            if not skeleton[i, j]:
                continue
            if j + 1 < cols and skeleton[i, j + 1]:
                total += 1.0
            if i + 1 < rows and skeleton[i + 1, j]:
                total += 1.0
            if i + 1 < rows and j + 1 < cols and skeleton[i + 1, j + 1]:
                total += math.sqrt(2.0)
            if i + 1 < rows and j - 1 >= 0 and skeleton[i + 1, j - 1]:
                total += math.sqrt(2.0)
    return total / 2.0


def segment_tortuosity(segments: list[list[tuple[int, int]]]) -> float:
    values = []
    weights = []
    for seg in segments:
        if len(seg) < 5:
            continue
        pts = np.asarray(seg, dtype=np.float32)
        steps = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(axis=1))
        path_length = float(steps.sum())
        chord = float(np.sqrt(((pts[-1] - pts[0]) ** 2).sum()))
        if chord < 3.0:
            continue
        values.append(path_length / chord)
        weights.append(path_length)
    if not values:
        return float("nan")
    return float(np.average(values, weights=weights))


def analyze_frame(image: np.ndarray) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    vessel = frangi_like(image)
    threshold = max(otsu_threshold(vessel) * 0.82, float(np.percentile(vessel, 78)))
    mask = vessel >= threshold
    mask = ndi.binary_dilation(mask, structure=np.ones((2, 2)), iterations=1)
    mask = ndi.binary_closing(mask, structure=np.ones((3, 3)), iterations=2)
    mask = ndi.binary_opening(mask, structure=np.ones((2, 2)), iterations=1)
    mask = remove_small_objects(mask, min_size=16)

    skeleton = thin_zhang_suen(mask)
    skeleton = prune_spurs(skeleton, iterations=2)

    labels, count = ndi.label(skeleton)
    if count:
        sizes = np.bincount(labels.ravel())
        keep = sizes >= 12
        keep[0] = False
        skeleton = keep[labels]

    if skeleton.sum() == 0:
        return {}, mask.astype(bool), skeleton.astype(bool)

    counts = neighbor_count(skeleton)
    endpoint_map = skeleton & (counts == 1)
    branch_map = skeleton & (counts >= 3)
    branch_labels, _ = ndi.label(branch_map)
    endpoint_labels, _ = ndi.label(endpoint_map)

    dist = ndi.distance_transform_edt(mask) * PIXEL_SIZE_UM
    widths = 2.0 * dist[skeleton]

    area_mm2 = FULL_AREA_MM2
    length_mm = skeleton_length_px(skeleton) * PIXEL_SIZE_UM / 1000.0
    nerve_area_mm2 = mask.sum() * (PIXEL_SIZE_UM / 1000.0) ** 2

    component_labels, n_comp = ndi.label(skeleton)
    long_components = 0
    long_component_branches = 0
    for comp_idx in range(1, n_comp + 1):
        comp = component_labels == comp_idx
        if comp.sum() < 12:
            continue
        comp_length_px = skeleton_length_px(comp)
        if comp_length_px >= 45.0:
            long_components += 1
            branch_ids = np.unique(branch_labels[comp & branch_map])
            branch_ids = branch_ids[branch_ids > 0]
            long_component_branches += int(branch_ids.size)

    segments = trace_segments(skeleton)
    long_segments = [seg for seg in segments if path_length_px(seg) >= 20.0]
    metrics = {
        "cnfd_fibers_per_mm2_proxy": long_components / area_mm2,
        "cnfl_mm_per_mm2": length_mm / area_mm2,
        "cnbd_branches_per_mm2_proxy": long_component_branches / area_mm2,
        "ctbd_branches_per_mm2_proxy": int(branch_labels.max()) / area_mm2,
        "cnfa_mm2_per_mm2": nerve_area_mm2 / area_mm2,
        "cnfw_mean_um_proxy": float(np.mean(widths)) if widths.size else float("nan"),
        "cnfracdim_proxy": box_counting_dimension(skeleton),
        "tortuosity_ratio_proxy": segment_tortuosity(long_segments),
        "endpoints_count": int(endpoint_labels.max()),
        "branchpoints_count": int(branch_labels.max()),
    }
    return metrics, mask.astype(bool), skeleton.astype(bool)


def make_overlay(image: np.ndarray, mask: np.ndarray, skeleton: np.ndarray) -> Image.Image:
    base = rescale01(image)
    rgb = np.dstack([base, base, base])
    rgb[..., 1] = np.maximum(rgb[..., 1], mask.astype(np.float32) * 0.7)
    rgb[..., 2] = np.maximum(rgb[..., 2], skeleton.astype(np.float32))
    rgb = (np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")


def save_contact_sheet(entries: list[tuple[FrameSpec, Image.Image]], out_path: Path) -> None:
    thumb_w = 260
    thumb_h = 260
    label_h = 44
    cols = 3
    rows = math.ceil(len(entries) / cols)
    canvas = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), color=(15, 15, 15))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for n, (spec, image) in enumerate(entries):
        thumb = image.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x = (n % cols) * thumb_w
        y = (n // cols) * (thumb_h + label_h)
        canvas.paste(thumb, (x, y))
        label = f"{spec.eye} idx {spec.idx} | {spec.depth_um} um | {spec.confidence}"
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=(0, 0, 0))
        draw.text((x + 6, y + thumb_h + 8), label, fill=(240, 240, 240), font=font)

    canvas.save(out_path)


def summarize(values: list[float]) -> tuple[float, float, float, float]:
    arr = np.asarray([v for v in values if not math.isnan(v)], dtype=np.float64)
    if arr.size == 0:
        return (float("nan"),) * 4
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    median = float(np.median(arr))
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    return mean, sd, median, (q1, q3)


def format_stat(name: str, values: list[float]) -> dict[str, str]:
    mean, sd, median, iqr = summarize(values)
    if math.isnan(mean):
        return {
            "metric": name,
            "mean_sd": "",
            "median_iqr": "",
        }
    q1, q3 = iqr
    return {
        "metric": name,
        "mean_sd": f"{mean:.2f} +/- {sd:.2f}",
        "median_iqr": f"{median:.2f} ({q1:.2f}-{q3:.2f})",
    }


def write_summary_csv(path: Path, rows: list[dict[str, object]], summary_metrics: list[str]) -> None:
    grouped: dict[str, defaultdict[str, list[float]]] = {
        "OD": defaultdict(list),
        "OS": defaultdict(list),
    }
    for row in rows:
        eye = str(row["eye"])
        for metric in summary_metrics:
            value = row.get(metric)
            if isinstance(value, float):
                grouped[eye][metric].append(value)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["eye", "metric", "mean_sd", "median_iqr"])
        writer.writeheader()
        for eye in ("OD", "OS"):
            for metric in summary_metrics:
                stat_row = format_stat(metric, grouped[eye][metric])
                stat_row["eye"] = eye
                writer.writerow(stat_row)


def main() -> None:
    root = Path(__file__).resolve().parent
    output_dir = root / "analysis_output"
    output_dir.mkdir(exist_ok=True)

    all_frames = {natural_index(path): path for path in root.glob("*.bmp")}

    per_frame_rows: list[dict[str, object]] = []
    overlays: list[tuple[FrameSpec, Image.Image]] = []

    for spec in FRAME_SPECS:
        image = load_frame(all_frames[spec.idx])
        metrics, mask, skeleton = analyze_frame(image)
        overlay = make_overlay(image, mask, skeleton)
        overlay.save(output_dir / f"overlay_{spec.eye}_{spec.idx}.png")
        overlays.append((spec, overlay))

        row: dict[str, object] = {
            "eye": spec.eye,
            "frame_idx": spec.idx,
            "depth_um": spec.depth_um,
            "confidence": spec.confidence,
        }
        row.update(metrics)
        per_frame_rows.append(row)

    per_frame_rows.sort(key=lambda row: (row["eye"], int(row["frame_idx"])))

    with (output_dir / "per_frame_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_frame_rows[0].keys()))
        writer.writeheader()
        writer.writerows(per_frame_rows)

    summary_metrics = [
        "cnfd_fibers_per_mm2_proxy",
        "cnfl_mm_per_mm2",
        "cnbd_branches_per_mm2_proxy",
        "ctbd_branches_per_mm2_proxy",
        "cnfa_mm2_per_mm2",
        "cnfw_mean_um_proxy",
        "cnfracdim_proxy",
        "tortuosity_ratio_proxy",
    ]

    write_summary_csv(output_dir / "per_eye_summary_all_selected.csv", per_frame_rows, summary_metrics)
    high_conf_rows = [row for row in per_frame_rows if row["confidence"] == "high"]
    write_summary_csv(output_dir / "per_eye_summary_high_confidence.csv", high_conf_rows, summary_metrics)

    save_contact_sheet(overlays, output_dir / "overlay_contact_sheet.png")

    with (output_dir / "analysis_notes.md").open("w", encoding="utf-8") as handle:
        handle.write("# Confocal analysis notes\n\n")
        handle.write(f"- Study date visible in export: 2026-04-03.\n")
        handle.write("- This folder contains one examination only; no longitudinal timepoints were available.\n")
        handle.write("- Metrics were calculated from manually selected nerve-rich frames, using an in-house proxy pipeline rather than ACCMetrics.\n")
        handle.write("- The main summary file is per_eye_summary_high_confidence.csv; the all_selected version is included as a sensitivity check.\n")
        handle.write("- CNFD, CNBD, CTBD, CNFW, CNFracDim, and tortuosity are reported as proxy values and should not be merged with publication-grade ACCMetrics results without validation.\n")
        handle.write("- Field size assumed to be 400 x 400 um (Heidelberg Rostock standard frame).\n")


if __name__ == "__main__":
    main()
