"""Art.Suleimanov1924."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageOps
from scipy import ndimage as ndi

from .inspect import quick_candidate_features


GENERIC_PATIENT_TOKENS = {
    "Section",
    "Topography",
    "Topographic",
    "Change",
    "Analysis",
    "3D-Image",
    "Image",
    "Macula",
    "Map",
    "Cornea",
    "Retina",
    "HRT",
    "Rostock",
    "D-Image",
}

MODALITY_PATTERNS = [
    ("confocal_section", "Section"),
    ("topographic_change_analysis", "Topographic Change Analysis"),
    ("topography", "Topography"),
    ("macula_map", "Macula Map"),
    ("three_d_image", "3D-Image"),
]


def _is_human_like_name(text: str) -> bool:
    parts = re.split(r"[ -]+", text.strip())
    if not parts:
        return False
    for part in parts:
        if not part:
            return False
        if not re.fullmatch(r"[A-Za-zА-Яа-я']{4,40}", part):
            return False
        if part.isupper():
            return False
        if not (part[0].isupper() and part[1:].islower()):
            return False
    return True


@dataclass(frozen=True)
class HeyexExam:
    patient_folder: str
    exam_id: str
    edb_path: Path
    dates: list[str]
    raw_strings: list[str]
    modality: str
    likely_confocal: bool


@dataclass(frozen=True)
class PreviewFeatures:
    width: int
    height: int
    jpeg_count: int
    mean: float
    std: float
    center_mean: float
    center_std: float
    lap_var: float
    grad_mean: float
    hf_std: float
    dark_frac: float
    bright_frac: float
    coherence: float


def _decode_utf16_strings(data: bytes) -> list[str]:
    text = data.decode("utf-16le", errors="ignore")
    strings = re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9 /._:-]{2,80}", text)
    return [s.strip().strip("\x00") for s in strings if s.strip()]


def _decode_latin_strings(data: bytes) -> list[str]:
    text = data.decode("latin1", errors="ignore")
    strings = re.findall(r"[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9 /._:-]{2,80}", text)
    return [s.strip().strip("\x00") for s in strings if s.strip()]


def _clean_strings(strings: list[str]) -> list[str]:
    cleaned: list[str] = []
    for text in strings:
        text = re.sub(r"\s+", " ", text).strip(" .-_")
        if not text:
            continue
        if text in {"CMDb", "MDbMDir", "MDbData", "xVMDbDir", "VMDbDir", "yVMDbDir", "zV4"}:
            continue
        cleaned.append(text)
    return cleaned


def _extract_dates(strings: list[str]) -> list[str]:
    dates = sorted(set(re.findall(r"20\d{2}/\d{2}/\d{2}", " | ".join(strings))))
    return dates


def _infer_modality(strings: list[str]) -> str:
    joined = " | ".join(strings)
    for modality, token in MODALITY_PATTERNS:
        if token in joined:
            return modality
    return "unknown"


def _collect_name_candidates(strings: list[str]) -> list[str]:
    candidates: list[str] = []
    for text in strings:
        if any(token in text for token in GENERIC_PATIENT_TOKENS):
            continue
        if re.fullmatch(r"20\d{2}/\d{2}/\d{2}", text):
            continue
        if re.fullmatch(r"\d+", text):
            continue
        if len(text) < 3:
            continue
        if not re.search(r"[A-Za-zА-Яа-я]", text):
            continue
        if not _is_human_like_name(text):
            continue
        candidates.append(text)
    return candidates


def _best_patient_label(pdb_strings: list[str], edb_strings: list[str], folder_name: str) -> str:
    candidates = _collect_name_candidates(edb_strings)
    filtered = []
    for item in candidates:
        if item.startswith("JFIF"):
            continue
        if len(item) > 40:
            continue
        if re.search(r"[0-9]{4}", item):
            continue
        filtered.append(item)
    if not filtered:
        return folder_name
    counts = Counter(filtered)
    return counts.most_common(1)[0][0]


def _patient_sort_key(folder_name: str) -> int:
    match = re.search(r"(\d+)", folder_name)
    if not match:
        return 0
    return int(match.group(1))


def parse_exam_metadata(edb_path: Path) -> HeyexExam:
    data = edb_path.read_bytes()
    utf16_strings = _clean_strings(_decode_utf16_strings(data))
    latin_strings = _clean_strings(_decode_latin_strings(data))
    combined = []
    for item in utf16_strings + latin_strings:
        if item not in combined:
            combined.append(item)
    dates = _extract_dates(combined)
    modality = _infer_modality(combined)
    likely_confocal = modality == "confocal_section"
    return HeyexExam(
        patient_folder=edb_path.parent.name,
        exam_id=edb_path.stem,
        edb_path=edb_path,
        dates=dates,
        raw_strings=combined,
        modality=modality,
        likely_confocal=likely_confocal,
    )


def _extract_preview_jpegs(data: bytes, limit: int | None = None) -> list[Image.Image]:
    images: list[Image.Image] = []
    starts: list[int] = []
    ends: list[int] = []
    for idx in range(len(data) - 1):
        if data[idx] == 0xFF and data[idx + 1] == 0xD8:
            starts.append(idx)
        elif data[idx] == 0xFF and data[idx + 1] == 0xD9:
            ends.append(idx + 2)
    for start in starts:
        end = next((candidate for candidate in ends if candidate > start), None)
        if end is None:
            continue
        try:
            image = Image.open(io.BytesIO(data[start:end]))
            image.load()
            images.append(image.copy())
            if limit is not None and len(images) >= limit:
                break
        except Exception:
            continue
    return images


def _count_jpegs(data: bytes) -> int:
    count = 0
    for idx in range(len(data) - 1):
        if data[idx] == 0xFF and data[idx + 1] == 0xD8:
            count += 1
    return count


def _first_preview_image(sdb_path: Path) -> tuple[Image.Image | None, int]:
    data = sdb_path.read_bytes()
    jpeg_count = _count_jpegs(data)
    previews = _extract_preview_jpegs(data, limit=1)
    if not previews:
        return None, jpeg_count
    return previews[0], jpeg_count


def _preview_features(image: Image.Image, jpeg_count: int) -> PreviewFeatures:
    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
    h, w = gray.shape
    center = gray[int(h * 0.3):int(h * 0.7), int(w * 0.3):int(w * 0.7)]
    lap = ndi.laplace(gray)
    gx = ndi.sobel(gray, axis=1)
    gy = ndi.sobel(gray, axis=0)
    grad = np.hypot(gx, gy)
    hf = gray - ndi.gaussian_filter(gray, sigma=3)

    jxx = float((gx * gx).mean())
    jyy = float((gy * gy).mean())
    jxy = float((gx * gy).mean())
    tmp = ((jxx - jyy) ** 2 + 4.0 * jxy * jxy) ** 0.5
    l1 = 0.5 * (jxx + jyy + tmp)
    l2 = 0.5 * (jxx + jyy - tmp)
    coherence = 0.0 if (l1 + l2) == 0 else float((l1 - l2) / (l1 + l2))

    return PreviewFeatures(
        width=w,
        height=h,
        jpeg_count=jpeg_count,
        mean=float(gray.mean()),
        std=float(gray.std()),
        center_mean=float(center.mean()),
        center_std=float(center.std()),
        lap_var=float(lap.var()),
        grad_mean=float(grad.mean()),
        hf_std=float(hf.std()),
        dark_frac=float((gray < 0.18).mean()),
        bright_frac=float((gray > 0.82).mean()),
        coherence=coherence,
    )


def _classify_preview(features: PreviewFeatures) -> tuple[str, float]:
    cornea_score = 0.0

    if features.dark_frac > 0.75 and features.lap_var < 0.01:
        return "retina_fundus_like", 0.05

    if features.hf_std > 0.05:
        cornea_score += 0.35
    elif features.hf_std > 0.035:
        cornea_score += 0.15

    if features.lap_var > 0.04:
        cornea_score += 0.25
    elif features.lap_var > 0.02:
        cornea_score += 0.10

    if features.dark_frac < 0.45:
        cornea_score += 0.20
    elif features.dark_frac < 0.65:
        cornea_score += 0.08

    if 0.20 < features.mean < 0.55:
        cornea_score += 0.10

    if features.bright_frac < 0.03:
        cornea_score += 0.10
    elif features.bright_frac > 0.08:
        cornea_score -= 0.10

    if features.coherence > 0.22:
        return "anterior_segment_slitlamp_like", max(cornea_score, 0.30)

    if cornea_score >= 0.70:
        return "cornea_confocal_like", cornea_score
    if cornea_score >= 0.45:
        return "cornea_surface_or_slitlamp_like", cornea_score
    if features.dark_frac > 0.70:
        return "dark_surface_or_low_signal", cornea_score
    return "unclear", cornea_score


def _confocal_crop_array(image: Image.Image) -> np.ndarray:
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    if gray.shape[1] >= 384:
        gray = gray[:, :384]
    if gray.shape[0] >= 384:
        gray = gray[:384, :]
    return gray


def _build_patient_preview_contact_sheet(items: list[tuple[str, Image.Image]], out_path: Path) -> None:
    if not items:
        return
    thumb_w = 180
    thumb_h = 180
    label_h = 36
    cols = 4
    rows = math.ceil(len(items) / cols)
    canvas = Image.new("L", (cols * thumb_w, rows * (thumb_h + label_h)), color=20)
    draw = ImageDraw.Draw(canvas)
    for idx, (label, image) in enumerate(items):
        thumb = ImageOps.fit(image.convert("L"), (thumb_w, thumb_h), method=Image.Resampling.LANCZOS)
        x = (idx % cols) * thumb_w
        y = (idx // cols) * (thumb_h + label_h)
        canvas.paste(thumb, (x, y))
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=0)
        draw.text((x + 4, y + thumb_h + 5), label[:26], fill=255)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def extract_sdb_previews(sdb_path: Path, output_dir: Path, limit: int = 12) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    images = _extract_preview_jpegs(sdb_path.read_bytes(), limit=limit)
    saved: list[Path] = []
    for idx, image in enumerate(images):
        out = output_dir / f"{sdb_path.stem}_preview_{idx:03d}.jpg"
        image.save(out, quality=95)
        saved.append(out)

    if images:
        thumb_w = 220
        thumb_h = 180
        label_h = 26
        cols = 3
        rows = math.ceil(len(images) / cols)
        canvas = Image.new("L", (cols * thumb_w, rows * (thumb_h + label_h)), color=20)
        draw = ImageDraw.Draw(canvas)
        for idx, image in enumerate(images):
            thumb = ImageOps.fit(image.convert("L"), (thumb_w, thumb_h), method=Image.Resampling.LANCZOS)
            x = (idx % cols) * thumb_w
            y = (idx // cols) * (thumb_h + label_h)
            canvas.paste(thumb, (x, y))
            draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=0)
            draw.text((x + 6, y + thumb_h + 5), f"{idx} {image.size}", fill=255)
        contact = output_dir / f"{sdb_path.stem}_contact_sheet.png"
        canvas.save(contact)
        saved.append(contact)

    return saved


def build_cohort_registry(heyex_dir: Path, output_dir: Path) -> dict[str, Path]:
    patients_dir = heyex_dir / "patients"
    if not patients_dir.exists():
        raise FileNotFoundError(f"Missing patients directory under {heyex_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = output_dir / "previews"
    contact_dir = output_dir / "patient_contact_sheets"
    preview_dir.mkdir(exist_ok=True)
    contact_dir.mkdir(exist_ok=True)

    patient_metadata: dict[str, dict[str, object]] = {}
    confocal_patients: list[str] = []

    for patient_dir in sorted(patients_dir.glob("*.pat"), key=lambda p: _patient_sort_key(p.name)):
        edbs = sorted(patient_dir.glob("*.edb"))
        sdbs = sorted(patient_dir.glob("*.sdb"))
        exam_rows = [parse_exam_metadata(edb) for edb in edbs]
        likely_confocal = [exam for exam in exam_rows if exam.likely_confocal]
        if not likely_confocal:
            continue
        confocal_patients.append(patient_dir.name)
        all_exam_strings: list[str] = []
        dates: list[str] = []
        for exam in exam_rows:
            all_exam_strings.extend(exam.raw_strings)
            dates.extend(exam.dates)
        patient_metadata[patient_dir.name] = {
            "patient_folder": patient_dir.name,
            "patient_label_guess": _best_patient_label([], all_exam_strings, patient_dir.name),
            "confocal_exam_ids": " | ".join(exam.exam_id for exam in likely_confocal),
            "confocal_exam_count": len(likely_confocal),
            "first_exam_date": min(dates) if dates else "",
            "last_exam_date": max(dates) if dates else "",
            "sdb_files": len(sdbs),
        }

    sdb_rows: list[dict[str, object]] = []
    patient_rows: list[dict[str, object]] = []

    for patient_folder in confocal_patients:
        patient_dir = patients_dir / patient_folder
        sdbs = sorted(patient_dir.glob("*.sdb"))
        contact_items: list[tuple[str, Image.Image]] = []
        class_counter = Counter()
        max_subbasal_score = float("-inf")
        max_subbasal_file = ""

        for sdb in sdbs:
            preview, jpeg_count = _first_preview_image(sdb)
            row: dict[str, object] = {
                "patient_folder": patient_folder,
                "patient_label_guess": patient_metadata[patient_folder]["patient_label_guess"],
                "sdb_file": sdb.name,
                "sdb_size_bytes": sdb.stat().st_size,
                "size_profile": "small_single_frame_candidate" if sdb.stat().st_size <= 500000 else "large_multiframe_container",
                "jpeg_count": jpeg_count,
                "preview_class": "no_preview",
                "preview_score": 0.0,
                "subbasal_candidate_score": "",
                "subbasal_mask_area_fraction": "",
                "preview_saved_path": "",
            }

            if preview is not None:
                feats = _preview_features(preview, jpeg_count)
                preview_class, preview_score = _classify_preview(feats)
                row.update(
                    {
                        "preview_width": feats.width,
                        "preview_height": feats.height,
                        "preview_mean": feats.mean,
                        "preview_std": feats.std,
                        "center_mean": feats.center_mean,
                        "lap_var": feats.lap_var,
                        "hf_std": feats.hf_std,
                        "dark_frac": feats.dark_frac,
                        "bright_frac": feats.bright_frac,
                        "coherence": feats.coherence,
                        "preview_class": preview_class,
                        "preview_score": round(preview_score, 4),
                    }
                )

                patient_preview_dir = preview_dir / patient_folder
                patient_preview_dir.mkdir(parents=True, exist_ok=True)
                preview_path = patient_preview_dir / f"{sdb.stem}_preview0.jpg"
                preview.save(preview_path, quality=92)
                row["preview_saved_path"] = str(preview_path)

                if preview_class in {"cornea_confocal_like", "cornea_surface_or_slitlamp_like"}:
                    try:
                        candidate = quick_candidate_features(_confocal_crop_array(preview))
                        row["subbasal_candidate_score"] = round(float(candidate["auto_score"]), 4)
                        row["subbasal_mask_area_fraction"] = round(float(candidate["mask_area_fraction"]), 6)
                        if float(candidate["auto_score"]) > max_subbasal_score:
                            max_subbasal_score = float(candidate["auto_score"])
                            max_subbasal_file = sdb.name
                    except Exception:
                        row["subbasal_candidate_score"] = ""
                        row["subbasal_mask_area_fraction"] = ""

                if preview_class in {"cornea_confocal_like", "cornea_surface_or_slitlamp_like"}:
                    label = f"{sdb.stem} {preview_class[:10]}"
                    contact_items.append((label, preview))

                class_counter[preview_class] += 1
            else:
                class_counter["no_preview"] += 1

            sdb_rows.append(row)

        meta = patient_metadata[patient_folder]
        patient_row = {
            "patient_folder": patient_folder,
            "patient_label_guess": meta["patient_label_guess"],
            "confocal_exam_ids": meta["confocal_exam_ids"],
            "confocal_exam_count": meta["confocal_exam_count"],
            "first_exam_date": meta["first_exam_date"],
            "last_exam_date": meta["last_exam_date"],
            "sdb_files": meta["sdb_files"],
            "small_single_frame_sdb_count": sum(1 for sdb in sdbs if sdb.stat().st_size <= 500000),
            "cornea_confocal_like_count": class_counter["cornea_confocal_like"],
            "cornea_surface_or_slitlamp_like_count": class_counter["cornea_surface_or_slitlamp_like"],
            "retina_fundus_like_count": class_counter["retina_fundus_like"],
            "dark_surface_or_low_signal_count": class_counter["dark_surface_or_low_signal"],
            "unclear_count": class_counter["unclear"],
            "no_preview_count": class_counter["no_preview"],
            "max_subbasal_candidate_score": "" if max_subbasal_score == float("-inf") else round(max_subbasal_score, 4),
            "max_subbasal_candidate_sdb": max_subbasal_file,
            "review_include_patient": "",
            "review_cohort_group": "",
            "review_timepoints": "",
            "review_notes": "",
        }
        patient_rows.append(patient_row)

        if contact_items:
            _build_patient_preview_contact_sheet(
                contact_items[:24],
                contact_dir / f"{patient_folder}_cornea_candidates.png",
            )

    patient_rows.sort(key=lambda row: (
        row["first_exam_date"] or "9999/99/99",
        _patient_sort_key(str(row["patient_folder"])),
    ))
    sdb_rows.sort(key=lambda row: (
        str(row["patient_folder"]),
        0 if str(row["preview_class"]) == "cornea_confocal_like" else 1,
        -float(row["preview_score"]),
        str(row["sdb_file"]),
    ))

    patient_csv = output_dir / "cohort_patients.csv"
    sdb_csv = output_dir / "cohort_sdb_frames.csv"
    workbook = output_dir / "cohort_registry.xlsx"
    summary_md = output_dir / "cohort_summary.md"

    pd_patients = pd.DataFrame(patient_rows)
    pd_sdb = pd.DataFrame(sdb_rows)
    pd_patients.to_csv(patient_csv, index=False)
    pd_sdb.to_csv(sdb_csv, index=False)
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd_patients.to_excel(writer, index=False, sheet_name="patients")
        pd_sdb.to_excel(writer, index=False, sheet_name="sdb_frames")

    summary_md.write_text(
        "\n".join(
            [
                "# Confocal Cohort Registry",
                "",
                f"- HEYEX root: `{heyex_dir}`",
                f"- Patients with at least one `Section` exam: **{len(patient_rows)}**",
                f"- SDB containers scanned inside those patients: **{len(sdb_rows)}**",
                f"- `cornea_confocal_like` previews: **{sum(1 for row in sdb_rows if row['preview_class'] == 'cornea_confocal_like')}**",
                f"- `cornea_surface_or_slitlamp_like` previews: **{sum(1 for row in sdb_rows if row['preview_class'] == 'cornea_surface_or_slitlamp_like')}**",
                f"- `retina_fundus_like` previews: **{sum(1 for row in sdb_rows if row['preview_class'] == 'retina_fundus_like')}**",
                "",
                "## Output files",
                "",
                f"- Patients table: `{patient_csv.name}`",
                f"- SDB frame table: `{sdb_csv.name}`",
                f"- Workbook: `{workbook.name}`",
                f"- Preview folder: `{preview_dir.name}`",
                f"- Patient contact sheets: `{contact_dir.name}`",
                "",
                "## Notes",
                "",
                "- `patient_label_guess` is heuristic and should not be treated as a verified identifier.",
                "- `preview_class` is a triage label to accelerate manual review, not a final medical annotation.",
                "- `max_subbasal_candidate_score` is a ranking score to help find promising confocal corneal frames before detailed morphometry.",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "patient_csv": patient_csv,
        "sdb_csv": sdb_csv,
        "workbook": workbook,
        "summary_md": summary_md,
        "preview_dir": preview_dir,
        "contact_dir": contact_dir,
    }


def scan_heyex_tree(heyex_dir: Path, output_dir: Path) -> dict[str, Path]:
    patients_dir = heyex_dir / "patients"
    if not patients_dir.exists():
        raise FileNotFoundError(f"Missing patients directory under {heyex_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    patient_rows: list[dict[str, object]] = []
    exam_rows: list[dict[str, object]] = []

    for patient_dir in sorted(patients_dir.glob("*.pat")):
        pdbs = sorted(patient_dir.glob("*.pdb"))
        edbs = sorted(patient_dir.glob("*.edb"))
        sdbs = sorted(patient_dir.glob("*.sdb"))

        pdb_strings: list[str] = []
        for pdb in pdbs:
            data = pdb.read_bytes()
            pdb_strings.extend(_clean_strings(_decode_utf16_strings(data)))
            pdb_strings.extend(_clean_strings(_decode_latin_strings(data)))

        all_exam_strings: list[str] = []
        modalities = Counter()
        dates: list[str] = []
        likely_confocal_count = 0

        for edb in edbs:
            exam = parse_exam_metadata(edb)
            all_exam_strings.extend(exam.raw_strings)
            modalities[exam.modality] += 1
            dates.extend(exam.dates)
            likely_confocal_count += int(exam.likely_confocal)
            exam_rows.append(
                {
                    "patient_folder": patient_dir.name,
                    "exam_id": exam.exam_id,
                    "edb_file": edb.name,
                    "modality": exam.modality,
                    "likely_confocal": int(exam.likely_confocal),
                    "exam_date": exam.dates[0] if exam.dates else "",
                    "all_dates": " | ".join(exam.dates),
                    "sample_strings": " | ".join(exam.raw_strings[:12]),
                    "sdb_files_in_patient_folder": len(sdbs),
                    "pdb_files_in_patient_folder": len(pdbs),
                }
            )

        patient_label = _best_patient_label(pdb_strings, all_exam_strings, patient_dir.name)
        patient_rows.append(
            {
                "patient_folder": patient_dir.name,
                "patient_label_guess": patient_label,
                "pdb_files": len(pdbs),
                "edb_files": len(edbs),
                "sdb_files": len(sdbs),
                "first_exam_date": min(dates) if dates else "",
                "last_exam_date": max(dates) if dates else "",
                "likely_confocal_exam_count": likely_confocal_count,
                "modalities_seen": " | ".join(f"{k}:{v}" for k, v in modalities.items() if v),
            }
        )

    patient_csv = output_dir / "heyex_patients.csv"
    exam_csv = output_dir / "heyex_exams.csv"
    workbook = output_dir / "heyex_inventory.xlsx"
    summary_md = output_dir / "heyex_summary.md"

    pd_patients = pd.DataFrame(patient_rows)
    pd_exams = pd.DataFrame(exam_rows)

    pd_patients.to_csv(patient_csv, index=False)
    pd_exams.to_csv(exam_csv, index=False)
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd_patients.to_excel(writer, index=False, sheet_name="patients")
        pd_exams.to_excel(writer, index=False, sheet_name="exams")

    modality_counts = Counter(row["modality"] for row in exam_rows)
    likely_confocal_total = sum(int(row["likely_confocal"]) for row in exam_rows)
    summary_md.write_text(
        "\n".join(
            [
                "# HEYEX Inventory Summary",
                "",
                f"- HEYEX root: `{heyex_dir}`",
                f"- Patient folders: **{len(patient_rows)}**",
                f"- PDB files: **{sum(int(row['pdb_files']) for row in patient_rows)}**",
                f"- EDB files: **{len(exam_rows)}**",
                f"- SDB files: **{sum(int(row['sdb_files']) for row in patient_rows)}**",
                f"- Likely confocal `Section` exams: **{likely_confocal_total}**",
                "",
                "## Modalities",
                "",
            ]
            + [f"- `{name}`: {count}" for name, count in modality_counts.most_common()]
        ),
        encoding="utf-8",
    )

    return {
        "patient_csv": patient_csv,
        "exam_csv": exam_csv,
        "workbook": workbook,
        "summary_md": summary_md,
    }
