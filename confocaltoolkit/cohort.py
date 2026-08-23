"""Art.Suleimanov1924."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .algorithm import analyze_frame, make_overlay, save_contact_sheet
from .io import load_grayscale_frame

PROXY_METRICS: list[tuple[str, str, str]] = [
    ("cnfd_fibers_per_mm2_proxy", "CNFD_proxy_n_per_mm2", "CNFD proxy"),
    ("cnfl_mm_per_mm2", "CNFL_mm_per_mm2", "CNFL"),
    ("cnbd_branches_per_mm2_proxy", "CNBD_proxy_n_per_mm2", "CNBD proxy"),
    ("ctbd_branches_per_mm2_proxy", "CTBD_proxy_n_per_mm2", "CTBD proxy"),
    ("cnfa_mm2_per_mm2", "CNFA_mm2_per_mm2", "CNFA"),
    ("cnfw_mean_um_proxy", "CNFW_proxy_um", "CNFW proxy"),
    ("cnfracdim_proxy", "CNFracDim_proxy", "CNFracDim proxy"),
    ("tortuosity_ratio_proxy", "Tortuosity_proxy", "Tortuosity proxy"),
]


def _fmt_mean_sd(values: list[float]) -> str:
    if not values:
        return ""
    arr = np.asarray(values, dtype=float)
    mean = float(np.nanmean(arr))
    if len(arr) > 1:
        sd = float(np.nanstd(arr, ddof=1))
        return f"{mean:.3f} ± {sd:.3f}"
    return f"{mean:.3f}"


def _fmt_median_iqr(values: list[float]) -> str:
    if not values:
        return ""
    arr = np.asarray(values, dtype=float)
    median = float(np.nanmedian(arr))
    q1 = float(np.nanpercentile(arr, 25))
    q3 = float(np.nanpercentile(arr, 75))
    return f"{median:.3f} ({q1:.3f}-{q3:.3f})"


def _stats(values: list[float]) -> dict[str, float | str | int]:
    if not values:
        return {
            "n_frames_used": 0,
            "mean": float("nan"),
            "sd": float("nan"),
            "median": float("nan"),
            "q1": float("nan"),
            "q3": float("nan"),
            "mean_sd_text": "",
            "median_iqr_text": "",
        }
    arr = np.asarray(values, dtype=float)
    mean = float(np.nanmean(arr))
    sd = float(np.nanstd(arr, ddof=1)) if len(arr) > 1 else float("nan")
    median = float(np.nanmedian(arr))
    q1 = float(np.nanpercentile(arr, 25))
    q3 = float(np.nanpercentile(arr, 75))
    return {
        "n_frames_used": int(len(arr)),
        "mean": mean,
        "sd": sd,
        "median": median,
        "q1": q1,
        "q3": q3,
        "mean_sd_text": _fmt_mean_sd(values),
        "median_iqr_text": _fmt_median_iqr(values),
    }


def _bucket_from_interval(days: int) -> str:
    if days <= 0:
        return "baseline_candidate"
    if days <= 7:
        return "early_followup_candidate"
    if days <= 45:
        return "month1_like_candidate"
    if days <= 120:
        return "month3_like_candidate"
    if days <= 240:
        return "month6_like_candidate"
    return "late_followup_candidate"


def _safe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _series_values(records: list[dict[str, object]], column: str) -> list[float]:
    values = []
    for record in records:
        value = record.get(column)
        if isinstance(value, (int, float)) and not math.isnan(float(value)):
            values.append(float(value))
    return values


def build_proxy_cohort(
    analysis_dir: Path,
    output_dir: Path,
    top_n_frames: int = 5,
    min_total_confocal_frames: int = 20,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir = output_dir / "overlays"
    overlay_dir.mkdir(exist_ok=True)

    study_patients = pd.read_csv(analysis_dir / "study_patients.csv")
    study_visits = pd.read_csv(analysis_dir / "study_visits.csv")
    top_frames = pd.read_csv(analysis_dir / "analysis_top_frames.csv")

    all_multivisit = study_patients[study_patients["estimated_visit_count"].fillna(0) >= 2].copy()
    excluded_rows: list[dict[str, object]] = []
    for row in all_multivisit.itertuples(index=False):
        total_confocal = int(getattr(row, "total_confocal_like_frames") or 0)
        likely_longitudinal = str(getattr(row, "likely_longitudinal_candidate") or "")
        reason = ""
        if likely_longitudinal == "yes":
            continue
        if total_confocal < min_total_confocal_frames:
            reason = f"low confocal frame count (<{min_total_confocal_frames})"
        else:
            reason = "did not pass longitudinal candidate rule"
        excluded_rows.append(
            {
                "patient_folder": row.patient_folder,
                "patient_label_guess": row.patient_label_guess,
                "estimated_visit_count": int(getattr(row, "estimated_visit_count") or 0),
                "total_confocal_like_frames": total_confocal,
                "priority_flag": getattr(row, "priority_flag") or "",
                "exclusion_reason": reason,
            }
        )

    candidate_patients = study_patients[
        (study_patients["likely_longitudinal_candidate"] == "yes")
        & (study_patients["total_confocal_like_frames"].fillna(0) >= min_total_confocal_frames)
    ].copy()
    candidate_patients = candidate_patients.sort_values("patient_folder")

    frame_rows: list[dict[str, object]] = []
    visit_rows: list[dict[str, object]] = []
    pair_rows: list[dict[str, object]] = []
    contact_sheet_items = []

    for patient in candidate_patients.itertuples(index=False):
        patient_visits = study_visits[study_visits["patient_folder"] == patient.patient_folder].copy()
        patient_visits["visit_date_est"] = pd.to_datetime(patient_visits["visit_date_est"], errors="coerce")
        patient_visits = patient_visits.sort_values(["visit_seq", "visit_date_est"])
        if len(patient_visits) < 2:
            continue

        baseline_visit = patient_visits.iloc[0]
        followup_visit = patient_visits.iloc[-1]
        baseline_date = pd.to_datetime(baseline_visit["visit_date_est"]).date()
        per_patient_visit_rows: list[dict[str, object]] = []

        for visit in [baseline_visit, followup_visit]:
            visit_id = str(visit["visit_id_est"])
            visit_date = pd.to_datetime(visit["visit_date_est"]).date()
            interval_days = int((visit_date - baseline_date).days)
            role = "baseline_candidate" if interval_days == 0 else "followup_candidate"
            interval_bucket = _bucket_from_interval(interval_days)

            visit_top = top_frames[
                (top_frames["patient_folder"] == patient.patient_folder)
                & (top_frames["visit_id_est"] == visit_id)
                & (top_frames["preview_class"] == "cornea_confocal_like")
            ].copy()
            visit_top = visit_top.sort_values(["rank_within_visit", "subbasal_candidate_score"], ascending=[True, False]).head(top_n_frames)

            current_contact_items = []
            metric_records_for_visit: list[dict[str, object]] = []
            for frame in visit_top.itertuples(index=False):
                preview_path = Path(str(frame.preview_abs_path))
                image = load_grayscale_frame(preview_path)
                metrics, mask, skeleton = analyze_frame(image)
                overlay = make_overlay(image, mask, skeleton)
                overlay_name = f"{patient.patient_folder}_{visit_id}_rank{int(frame.rank_within_visit):02d}_{Path(frame.sdb_file).stem}.png"
                overlay.save(overlay_dir / overlay_name)

                metric_row: dict[str, object] = {
                    "patient_folder": patient.patient_folder,
                    "patient_label_guess": patient.patient_label_guess,
                    "visit_id_est": visit_id,
                    "visit_seq": int(visit["visit_seq"]),
                    "visit_date_est": str(visit_date),
                    "candidate_role": role,
                    "interval_days_from_first_visit": interval_days,
                    "interval_bucket_candidate": interval_bucket,
                    "frame_rank_within_visit": int(frame.rank_within_visit),
                    "sdb_file": frame.sdb_file,
                    "preview_path": str(preview_path),
                    "subbasal_candidate_score": _safe_float(frame.subbasal_candidate_score),
                    "overlay_file": overlay_name,
                }
                for source_name, export_name, _ in PROXY_METRICS:
                    metric_row[export_name] = metrics[source_name]
                    metric_row[source_name] = metrics[source_name]
                frame_rows.append(metric_row)
                metric_records_for_visit.append(metric_row)

                current_contact_items.append(
                    (
                        type(
                            "FrameSpecProxy",
                            (),
                            {
                                "eye": patient.patient_folder,
                                "idx": int(frame.rank_within_visit),
                                "depth_um": str(interval_days),
                                "confidence": role,
                            },
                        )(),
                        overlay,
                    )
                )

            visit_summary: dict[str, object] = {
                "patient_folder": patient.patient_folder,
                "patient_label_guess": patient.patient_label_guess,
                "visit_id_est": visit_id,
                "visit_seq": int(visit["visit_seq"]),
                "visit_date_est": str(visit_date),
                "candidate_role": role,
                "interval_days_from_first_visit": interval_days,
                "interval_bucket_candidate": interval_bucket,
                "available_confocal_like_frames": int(visit["cornea_confocal_like"]),
                "selected_top_frames": int(len(metric_records_for_visit)),
                "best_subbasal_candidate_score": _safe_float(visit["best_subbasal_candidate_score"]),
                "best_sdb_file": visit["best_sdb_file"],
            }
            for _, export_name, _ in PROXY_METRICS:
                values = _series_values(metric_records_for_visit, export_name)
                summary = _stats(values)
                visit_summary[f"{export_name}_n"] = summary["n_frames_used"]
                visit_summary[f"{export_name}_mean"] = summary["mean"]
                visit_summary[f"{export_name}_sd"] = summary["sd"]
                visit_summary[f"{export_name}_median"] = summary["median"]
                visit_summary[f"{export_name}_q1"] = summary["q1"]
                visit_summary[f"{export_name}_q3"] = summary["q3"]
                visit_summary[f"{export_name}_mean_sd"] = summary["mean_sd_text"]
                visit_summary[f"{export_name}_median_iqr"] = summary["median_iqr_text"]
            visit_rows.append(visit_summary)
            per_patient_visit_rows.append(visit_summary)

            if current_contact_items:
                contact_sheet_path = output_dir / f"{patient.patient_folder}_{visit_id}_contact.png"
                save_contact_sheet(current_contact_items, contact_sheet_path)
                contact_sheet_items.extend(current_contact_items)

        if len(per_patient_visit_rows) < 2:
            continue
        baseline_summary = per_patient_visit_rows[0]
        followup_summary = per_patient_visit_rows[-1]
        pair_row: dict[str, object] = {
            "patient_folder": patient.patient_folder,
            "patient_label_guess": patient.patient_label_guess,
            "baseline_visit_id": baseline_summary["visit_id_est"],
            "baseline_visit_date": baseline_summary["visit_date_est"],
            "followup_visit_id": followup_summary["visit_id_est"],
            "followup_visit_date": followup_summary["visit_date_est"],
            "followup_interval_days": int(followup_summary["interval_days_from_first_visit"]),
            "followup_interval_bucket_candidate": followup_summary["interval_bucket_candidate"],
            "baseline_frames_used": int(baseline_summary["selected_top_frames"]),
            "followup_frames_used": int(followup_summary["selected_top_frames"]),
        }
        for _, export_name, _ in PROXY_METRICS:
            baseline_mean = baseline_summary.get(f"{export_name}_mean")
            followup_mean = followup_summary.get(f"{export_name}_mean")
            pair_row[f"{export_name}_baseline_mean"] = baseline_mean
            pair_row[f"{export_name}_followup_mean"] = followup_mean
            if isinstance(baseline_mean, float) and not math.isnan(baseline_mean) and isinstance(followup_mean, float) and not math.isnan(followup_mean):
                pair_row[f"{export_name}_delta_abs"] = followup_mean - baseline_mean
                pair_row[f"{export_name}_delta_pct"] = ((followup_mean - baseline_mean) / baseline_mean * 100.0) if baseline_mean != 0 else float("nan")
            else:
                pair_row[f"{export_name}_delta_abs"] = float("nan")
                pair_row[f"{export_name}_delta_pct"] = float("nan")
        pair_rows.append(pair_row)

    cohort_rows: list[dict[str, object]] = []
    for _, export_name, metric_label in PROXY_METRICS:
        baseline_values: list[float] = []
        followup_values: list[float] = []
        delta_values: list[float] = []
        delta_pct_values: list[float] = []
        for row in pair_rows:
            baseline = row.get(f"{export_name}_baseline_mean")
            followup = row.get(f"{export_name}_followup_mean")
            delta = row.get(f"{export_name}_delta_abs")
            delta_pct = row.get(f"{export_name}_delta_pct")
            if isinstance(baseline, (int, float)) and not math.isnan(float(baseline)):
                baseline_values.append(float(baseline))
            if isinstance(followup, (int, float)) and not math.isnan(float(followup)):
                followup_values.append(float(followup))
            if isinstance(delta, (int, float)) and not math.isnan(float(delta)):
                delta_values.append(float(delta))
            if isinstance(delta_pct, (int, float)) and not math.isnan(float(delta_pct)):
                delta_pct_values.append(float(delta_pct))

        wilcoxon_p = float("nan")
        if len(baseline_values) >= 2 and len(followup_values) == len(baseline_values):
            try:
                from scipy.stats import wilcoxon

                if np.any(np.asarray(baseline_values) != np.asarray(followup_values)):
                    wilcoxon_p = float(wilcoxon(baseline_values, followup_values).pvalue)
            except Exception:
                wilcoxon_p = float("nan")

        cohort_rows.append(
            {
                "metric": export_name,
                "metric_label": metric_label,
                "n_pairs": int(min(len(baseline_values), len(followup_values))),
                "baseline_mean_sd": _fmt_mean_sd(baseline_values),
                "baseline_median_iqr": _fmt_median_iqr(baseline_values),
                "followup_mean_sd": _fmt_mean_sd(followup_values),
                "followup_median_iqr": _fmt_median_iqr(followup_values),
                "delta_mean_sd": _fmt_mean_sd(delta_values),
                "delta_pct_mean_sd": _fmt_mean_sd(delta_pct_values),
                "wilcoxon_p": wilcoxon_p,
            }
        )

    cohort_notes = [
        "# Longitudinal Proxy Cohort Notes",
        "",
        "- This package is a preliminary research dataset derived from HEYEX preview JPEGs rather than validated ACCMetrics exports.",
        "- Candidate cohort rule: at least 2 estimated visits and at least 20 cornea_confocal_like frames across the patient.",
        f"- Top frames per visit analyzed: {top_n_frames}.",
        "- Earliest visit is treated as baseline candidate; latest visit is treated as follow-up candidate.",
        "- Follow-up buckets are based on visit interval only and are not guaranteed to match true postoperative timepoints until surgery dates are confirmed.",
        "- CNFD/CNBD/CTBD/CNFW/CNFracDim/Tortuosity remain proxy metrics from the current MVP segmentation pipeline.",
    ]

    overall_contact_sheet = output_dir / "proxy_cohort_contact_sheet.png"
    if contact_sheet_items:
        save_contact_sheet(contact_sheet_items, overall_contact_sheet)

    candidate_patients_path = output_dir / "candidate_patients.csv"
    excluded_path = output_dir / "excluded_multivisit_patients.csv"
    per_frame_path = output_dir / "per_frame_proxy_metrics.csv"
    per_visit_path = output_dir / "per_visit_proxy_summary.csv"
    pair_path = output_dir / "paired_candidate_summary.csv"
    cohort_path = output_dir / "cohort_paired_stats.csv"
    bundle_path = output_dir / "proxy_cohort_bundle.json"
    notes_path = output_dir / "proxy_cohort_notes.md"

    candidate_patients.to_csv(candidate_patients_path, index=False)
    pd.DataFrame(excluded_rows).to_csv(excluded_path, index=False)
    pd.DataFrame(frame_rows).to_csv(per_frame_path, index=False)
    pd.DataFrame(visit_rows).to_csv(per_visit_path, index=False)
    pd.DataFrame(pair_rows).to_csv(pair_path, index=False)
    pd.DataFrame(cohort_rows).to_csv(cohort_path, index=False)
    notes_path.write_text("\n".join(cohort_notes), encoding="utf-8")

    bundle = {
        "summary": {
            "candidate_patient_count": int(len(candidate_patients)),
            "excluded_multivisit_count": int(len(excluded_rows)),
            "frame_rows": int(len(frame_rows)),
            "visit_rows": int(len(visit_rows)),
            "pair_rows": int(len(pair_rows)),
            "top_n_frames_per_visit": int(top_n_frames),
            "min_total_confocal_frames": int(min_total_confocal_frames),
        },
        "candidate_patients": candidate_patients.fillna("").to_dict(orient="records"),
        "excluded_multivisit": pd.DataFrame(excluded_rows).fillna("").to_dict(orient="records"),
        "per_frame_proxy_metrics": pd.DataFrame(frame_rows).replace({np.nan: None}).to_dict(orient="records"),
        "per_visit_proxy_summary": pd.DataFrame(visit_rows).replace({np.nan: None}).to_dict(orient="records"),
        "paired_candidate_summary": pd.DataFrame(pair_rows).replace({np.nan: None}).to_dict(orient="records"),
        "cohort_paired_stats": pd.DataFrame(cohort_rows).replace({np.nan: None}).to_dict(orient="records"),
        "metric_labels": [{"metric": export_name, "label": metric_label} for _, export_name, metric_label in PROXY_METRICS],
        "notes": cohort_notes,
    }
    import json

    bundle_path.write_text(json.dumps(bundle, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "candidate_patients_csv": candidate_patients_path,
        "excluded_csv": excluded_path,
        "per_frame_csv": per_frame_path,
        "per_visit_csv": per_visit_path,
        "paired_csv": pair_path,
        "cohort_stats_csv": cohort_path,
        "bundle_json": bundle_path,
        "notes_md": notes_path,
        "contact_sheet": overall_contact_sheet,
        "overlay_dir": overlay_dir,
    }
