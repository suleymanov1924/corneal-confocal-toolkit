"""Art.Suleimanov1924."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .algorithm import METRIC_COLUMNS, analyze_frame, format_stat, make_overlay, save_contact_sheet
from .inspect import inspect_study
from .io import discover_frames, extract_frame_index, load_grayscale_frame
from .models import FrameInfo, SelectionEntry


def _parse_bool(value: object) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "include"}


def load_selection_entries(path: Path) -> list[SelectionEntry]:
    entries: list[SelectionEntry] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            entries.append(
                SelectionEntry(
                    frame_index=int(row.get("frame_index") or 0),
                    filename=str(row.get("filename") or "").strip(),
                    include=_parse_bool(row.get("include", "")),
                    eye=str(row.get("eye") or "").strip().upper(),
                    confidence=str(row.get("confidence") or "").strip().lower(),
                    depth_um=str(row.get("depth_um") or "").strip(),
                    note=str(row.get("note") or "").strip(),
                )
            )
    return entries


def _group_summary(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        eye = str(row["eye"])
        grouped.setdefault(eye, {metric: [] for metric in METRIC_COLUMNS})
        for metric in METRIC_COLUMNS:
            value = row.get(metric)
            if isinstance(value, float) and not math.isnan(value):
                grouped[eye][metric].append(value)

    summary_rows: list[dict[str, str]] = []
    for eye in sorted(grouped.keys()):
        for metric in METRIC_COLUMNS:
            stats = format_stat(metric, grouped[eye][metric])
            stats["eye"] = eye
            summary_rows.append(stats)
    return summary_rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_excel(
    output_path: Path,
    inventory_rows: list[dict[str, object]],
    selected_rows: list[dict[str, object]],
    per_frame_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> None:
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(inventory_rows).to_excel(writer, index=False, sheet_name="inventory")
        pd.DataFrame(selected_rows).to_excel(writer, index=False, sheet_name="selected_frames")
        pd.DataFrame(per_frame_rows).to_excel(writer, index=False, sheet_name="per_frame_metrics")
        pd.DataFrame(summary_rows).to_excel(writer, index=False, sheet_name="summary_by_eye")


def _write_html_report(
    output_path: Path,
    study_dir: Path,
    selected_rows: list[dict[str, object]],
    per_frame_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> None:
    summary_html = pd.DataFrame(summary_rows).to_html(index=False, border=0)
    per_frame_html = pd.DataFrame(per_frame_rows).to_html(index=False, border=0)

    image_items = []
    for row in per_frame_rows:
        overlay_name = row["overlay_file"]
        image_items.append(
            "<div class='card'>"
            f"<img src='overlays/{overlay_name}' alt='{overlay_name}' />"
            f"<p>{row['eye']} | frame {row['frame_index']} | {row['confidence']}</p>"
            "</div>"
        )

    selected_df = pd.DataFrame(selected_rows)
    selected_html = selected_df.to_html(index=False, border=0)
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Confocal Analysis Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1d1d1d; background: #faf9f5; }}
    h1, h2 {{ margin: 0 0 12px 0; }}
    p {{ line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 24px 0; background: white; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 13px; text-align: left; }}
    th {{ background: #f0eadb; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 16px; }}
    .card {{ background: white; border: 1px solid #ddd; padding: 12px; }}
    .card img {{ width: 100%; height: auto; display: block; }}
    .note {{ background: #fff7db; border-left: 4px solid #d8b14a; padding: 12px 16px; margin: 16px 0 24px 0; }}
    code {{ background: #eee8db; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>Confocal Analysis Report</h1>
  <p>Study folder: <code>{study_dir}</code></p>
  <div class=\"note\">
    This MVP uses a semi-automatic proxy pipeline. It can open Heidelberg BMP and single-frame RAW exports,
    propose candidate subbasal frames, calculate nerve metrics, export to Excel, and generate a manuscript-friendly report.
    CNFD, CNBD, CTBD, CNFW, CNFracDim, and tortuosity remain proxy measures until validated against expert tracing or ACCMetrics.
  </div>
  <h2>Selected Frames</h2>
  {selected_html}
  <h2>Summary By Eye</h2>
  {summary_html}
  <h2>Per-frame Metrics</h2>
  {per_frame_html}
  <h2>Overlay Review</h2>
  <div class=\"grid\">
    {''.join(image_items)}
  </div>
</body>
</html>"""
    output_path.write_text(html, encoding="utf-8")


def _auto_select(rows: list[dict[str, object]], top_n: int) -> list[SelectionEntry]:
    ranked = sorted(rows, key=lambda row: float(row["auto_score"]), reverse=True)[:top_n]
    return [
        SelectionEntry(
            frame_index=int(row["frame_index"]),
            filename=str(row["filename"]),
            include=True,
            eye="ALL",
            confidence="auto",
            depth_um="",
            note="auto-selected from inspect score",
        )
        for row in ranked
    ]


def _resolve_selected_frames(
    frames: list[FrameInfo],
    entries: list[SelectionEntry],
) -> list[tuple[FrameInfo, SelectionEntry]]:
    by_filename = {frame.filename.lower(): frame for frame in frames}
    by_index = {frame.frame_index: frame for frame in frames}
    selected: list[tuple[FrameInfo, SelectionEntry]] = []
    for entry in entries:
        if not entry.include:
            continue
        frame = by_filename.get(entry.filename.lower()) if entry.filename else None
        if frame is None:
            frame = by_index.get(entry.frame_index)
        if frame is None:
            continue
        selected.append((frame, entry))
    return selected


def analyze_study(
    study_dir: Path,
    output_dir: Path,
    selection_file: Path | None = None,
    auto_select_count: int = 8,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir = output_dir / "overlays"
    overlay_dir.mkdir(exist_ok=True)

    frames = [
        FrameInfo(
            frame_index=extract_frame_index(path),
            filename=path.name,
            path=path,
            source_type=path.suffix.lower().lstrip("."),
        )
        for path in discover_frames(study_dir)
    ]
    _, inventory_rows = inspect_study(study_dir)

    if selection_file is not None and selection_file.exists():
        selection_entries = load_selection_entries(selection_file)
    else:
        selection_entries = _auto_select(inventory_rows, top_n=auto_select_count)

    selected_pairs = _resolve_selected_frames(frames, selection_entries)
    if not selected_pairs:
        raise ValueError("No frames selected for analysis. Check the selection file or auto-select settings.")

    selected_rows: list[dict[str, object]] = []
    per_frame_rows: list[dict[str, object]] = []
    overlay_entries = []

    for frame, entry in selected_pairs:
        selected_rows.append(
            {
                "frame_index": frame.frame_index,
                "filename": frame.filename,
                "source_type": frame.source_type,
                "include": 1,
                "eye": entry.eye or "ALL",
                "confidence": entry.confidence or "review",
                "depth_um": entry.depth_um,
                "note": entry.note,
            }
        )

        image = load_grayscale_frame(frame.path)
        metrics, mask, skeleton = analyze_frame(image)
        overlay = make_overlay(image, mask, skeleton)
        overlay_file = f"overlay_{entry.eye or 'ALL'}_{frame.frame_index}_{frame.source_type}.png"
        overlay.save(overlay_dir / overlay_file)
        overlay_entries.append((entry, overlay))

        row: dict[str, object] = {
            "eye": entry.eye or "ALL",
            "frame_index": frame.frame_index,
            "filename": frame.filename,
            "source_type": frame.source_type,
            "confidence": entry.confidence or "review",
            "depth_um": entry.depth_um,
            "note": entry.note,
            "overlay_file": overlay_file,
        }
        row.update(metrics)
        per_frame_rows.append(row)

    per_frame_rows.sort(key=lambda row: (str(row["eye"]), int(row["frame_index"])))
    summary_rows = _group_summary(per_frame_rows)

    per_frame_csv = output_dir / "per_frame_metrics.csv"
    selected_csv = output_dir / "selected_frames.csv"
    summary_csv = output_dir / "summary_by_eye.csv"
    workbook_path = output_dir / "confocal_report.xlsx"
    report_html = output_dir / "report.html"
    contact_sheet = output_dir / "selected_contact_sheet.png"

    _write_csv(per_frame_csv, per_frame_rows)
    _write_csv(selected_csv, selected_rows)
    _write_csv(summary_csv, summary_rows)
    _write_excel(workbook_path, inventory_rows, selected_rows, per_frame_rows, summary_rows)
    _write_html_report(report_html, study_dir, selected_rows, per_frame_rows, summary_rows)
    save_contact_sheet(
        [
            (
                type("FrameSpecProxy", (), {
                    "eye": entry.eye or "ALL",
                    "idx": frame.frame_index,
                    "depth_um": entry.depth_um or "?",
                    "confidence": entry.confidence or "review",
                })(),
                overlay,
            )
            for (frame, entry), (_, overlay) in zip(selected_pairs, overlay_entries)
        ],
        contact_sheet,
    )

    notes_path = output_dir / "run_notes.md"
    notes_path.write_text(
        "\n".join(
            [
                "# Confocal Analysis Run Notes",
                "",
                f"- Study folder: `{study_dir}`",
                f"- Selection source: `{selection_file}`" if selection_file else f"- Selection source: auto top {auto_select_count} frames by inspect score",
                "- BMP and single-frame RAW inputs are supported in this MVP.",
                "- Per-eye summary is only meaningful when the selection file contains correct eye labels.",
                "- CNFD, CNBD, CTBD, CNFW, CNFracDim, and tortuosity should currently be treated as proxy metrics pending validation.",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "per_frame_csv": per_frame_csv,
        "selected_csv": selected_csv,
        "summary_csv": summary_csv,
        "workbook": workbook_path,
        "report_html": report_html,
        "contact_sheet": contact_sheet,
        "notes": notes_path,
    }
