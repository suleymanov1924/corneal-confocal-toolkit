"""Art.Suleimanov1924."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TIMEPOINT_WINDOWS: list[tuple[str, int | None, int | None]] = [
    ("preop", None, -1),
    ("day1", 0, 2),
    ("week1", 5, 10),
    ("month1", 25, 45),
    ("month3", 75, 120),
    ("month6", 150, 240),
    ("month12", 300, 420),
]

METRIC_CODEBOOK = [
    ("CNFD_n_per_mm2", "Main subbasal nerve fiber density", "n/mm2"),
    ("CNFL_mm_per_mm2", "Total subbasal nerve fiber length", "mm/mm2"),
    ("CNBD_n_per_mm2", "Main trunk branch density", "n/mm2"),
    ("CTBD_n_per_mm2", "Total branch density", "n/mm2"),
    ("CNFA_mm2_per_mm2", "Nerve fiber area fraction", "mm2/mm2"),
    ("CNFW_mm_per_mm2", "Average nerve fiber width", "mm/mm2"),
    ("CNFracDim", "Fractal dimension of the nerve plexus", "unitless"),
    ("Tortuosity", "Tortuosity coefficient or Oliveira-Soto score", "unitless"),
    ("Reflectivity_score", "Reflectivity grade", "unitless"),
    ("Beadings_per_mm", "Beadings per mm of nerve length", "1/mm"),
    ("MainTrunks_count", "Main nerve trunks in analyzed frame", "count"),
    ("StromalNerveDensity", "Stromal nerve density", "n/mm2"),
    ("StromalTrunkDiameter_um", "Stromal nerve trunk diameter", "um"),
    ("BasalEpithelialCellDensity", "Basal epithelial cell density", "cells/mm2"),
    ("Langerhans_Immature_n_per_mm2", "Immature Langerhans cells density", "n/mm2"),
    ("Langerhans_Mature_n_per_mm2", "Mature Langerhans cells density", "n/mm2"),
    ("Langerhans_Total_n_per_mm2", "Total Langerhans cells density", "n/mm2"),
    ("KeratocyteDensity_AnteriorStroma", "Anterior stromal keratocyte density", "cells/mm2"),
]

PREVIEW_PRIORITY = {
    "cornea_confocal_like": 0,
    "cornea_surface_or_slitlamp_like": 1,
    "anterior_segment_slitlamp_like": 2,
    "dark_surface_or_low_signal": 3,
    "unclear": 4,
    "retina_fundus_like": 5,
    "no_preview": 6,
}


def _safe_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _priority_flag(visit_count: int, confocal_frames: int) -> str:
    if visit_count >= 2 and confocal_frames >= 20:
        return "high"
    if visit_count >= 2 or confocal_frames >= 20:
        return "medium"
    return "review"


def _to_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []

    out: list[dict[str, object]] = []
    for record in frame.to_dict(orient="records"):
        cleaned: dict[str, object] = {}
        for key, value in record.items():
            if isinstance(value, pd.Timestamp):
                cleaned[key] = value.isoformat(sep=" ")
            elif value is None or pd.isna(value):
                cleaned[key] = None
            else:
                cleaned[key] = value
        out.append(cleaned)
    return out


def prepare_analysis_data(
    heyex_dir: Path,
    registry_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    workspace_root = heyex_dir.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    patients_path = registry_dir / "cohort_patients.csv"
    frames_path = registry_dir / "cohort_sdb_frames.csv"

    patients = pd.read_csv(patients_path)
    frames = pd.read_csv(frames_path)
    if frames.empty:
        raise ValueError(f"No frame rows found in {frames_path}")

    patient_files_root = heyex_dir / "patients"
    abs_sdb_paths = [patient_files_root / row.patient_folder / row.sdb_file for row in frames.itertuples(index=False)]
    mtimes = [pd.Timestamp(path.stat().st_mtime, unit="s") for path in abs_sdb_paths]

    frames = frames.copy()
    frames["sdb_abs_path"] = [str(path.resolve()) for path in abs_sdb_paths]
    frames["file_mtime"] = mtimes
    frames["visit_date_est"] = frames["file_mtime"].dt.strftime("%Y-%m-%d")

    visit_dates = (
        frames[["patient_folder", "visit_date_est"]]
        .drop_duplicates()
        .sort_values(["patient_folder", "visit_date_est"])
        .reset_index(drop=True)
    )
    visit_dates["visit_seq"] = visit_dates.groupby("patient_folder").cumcount() + 1
    visit_dates["visit_id_est"] = visit_dates["patient_folder"] + "_V" + visit_dates["visit_seq"].astype(str).str.zfill(2)
    frames = frames.merge(visit_dates, on=["patient_folder", "visit_date_est"], how="left")

    frames["preview_abs_path"] = frames["preview_saved_path"].apply(
        lambda value: str((workspace_root / str(value)).resolve()) if _safe_text(value) else ""
    )
    frames["subbasal_candidate_score"] = pd.to_numeric(frames["subbasal_candidate_score"], errors="coerce")
    frames["preview_score"] = pd.to_numeric(frames["preview_score"], errors="coerce")

    class_counts = (
        frames.groupby(["patient_folder", "visit_id_est", "visit_seq", "visit_date_est"])["preview_class"]
        .value_counts()
        .unstack(fill_value=0)
        .reset_index()
    )
    for required in PREVIEW_PRIORITY:
        if required not in class_counts.columns:
            class_counts[required] = 0

    visit_meta = (
        frames.groupby(["patient_folder", "visit_id_est", "visit_seq", "visit_date_est"], dropna=False)
        .agg(
            patient_label_guess=("patient_label_guess", "first"),
            visit_start_est=("file_mtime", "min"),
            visit_end_est=("file_mtime", "max"),
            total_sdb_frames=("sdb_file", "count"),
            small_single_frame_sdb_count=("size_profile", lambda s: int((s == "small_single_frame_candidate").sum())),
            best_subbasal_candidate_score=("subbasal_candidate_score", "max"),
        )
        .reset_index()
    )

    best_idx = (
        frames.assign(
            preview_priority=frames["preview_class"].map(PREVIEW_PRIORITY).fillna(99),
            score_for_sort=frames["subbasal_candidate_score"].fillna(frames["preview_score"]).fillna(-999.0),
        )
        .sort_values(
            ["patient_folder", "visit_id_est", "preview_priority", "score_for_sort"],
            ascending=[True, True, True, False],
        )
        .groupby(["patient_folder", "visit_id_est"], as_index=False)
        .head(1)
    )
    best_visit = best_idx[
        [
            "patient_folder",
            "visit_id_est",
            "sdb_file",
            "preview_abs_path",
            "preview_class",
            "subbasal_candidate_score",
        ]
    ].rename(
        columns={
            "sdb_file": "best_sdb_file",
            "preview_abs_path": "best_preview_abs_path",
            "preview_class": "best_preview_class",
            "subbasal_candidate_score": "best_sdb_score",
        }
    )

    visits = visit_meta.merge(class_counts, on=["patient_folder", "visit_id_est", "visit_seq", "visit_date_est"], how="left")
    visits = visits.merge(best_visit, on=["patient_folder", "visit_id_est"], how="left")
    visits["visit_date_est"] = pd.to_datetime(visits["visit_date_est"])

    patient_visit_summary = (
        visits.groupby("patient_folder", dropna=False)
        .agg(
            estimated_visit_count=("visit_id_est", "count"),
            estimated_first_visit_date=("visit_date_est", "min"),
            estimated_last_visit_date=("visit_date_est", "max"),
            total_confocal_like_frames=("cornea_confocal_like", "sum"),
        )
        .reset_index()
    )
    patient_visit_summary["likely_longitudinal_candidate"] = patient_visit_summary.apply(
        lambda row: "yes" if int(row["estimated_visit_count"]) >= 2 and int(row["total_confocal_like_frames"]) >= 20 else "",
        axis=1,
    )
    patient_visit_summary["priority_flag"] = patient_visit_summary.apply(
        lambda row: _priority_flag(int(row["estimated_visit_count"]), int(row["total_confocal_like_frames"])),
        axis=1,
    )

    patients = patients.merge(patient_visit_summary, on="patient_folder", how="left")
    patients["estimated_visit_count"] = patients["estimated_visit_count"].fillna(0).astype(int)
    patients["total_confocal_like_frames"] = patients["total_confocal_like_frames"].fillna(0).astype(int)
    patients["priority_flag"] = patients["priority_flag"].fillna("review")
    patients["likely_longitudinal_candidate"] = patients["likely_longitudinal_candidate"].fillna("")
    patients["estimated_first_visit_date"] = pd.to_datetime(patients["estimated_first_visit_date"], errors="coerce")
    patients["estimated_last_visit_date"] = pd.to_datetime(patients["estimated_last_visit_date"], errors="coerce")

    visits = visits.merge(
        patients[["patient_folder", "priority_flag", "likely_longitudinal_candidate"]],
        on="patient_folder",
        how="left",
    )

    frames["score_for_rank"] = frames["subbasal_candidate_score"].fillna(frames["preview_score"]).fillna(-999.0)
    frames["rank_within_visit"] = (
        frames.sort_values(["patient_folder", "visit_id_est", "score_for_rank"], ascending=[True, True, False])
        .groupby(["patient_folder", "visit_id_est"])
        .cumcount()
        + 1
    )

    candidate_frames = frames[
        frames["preview_class"].isin(
            [
                "cornea_confocal_like",
                "cornea_surface_or_slitlamp_like",
                "anterior_segment_slitlamp_like",
            ]
        )
    ].copy()
    top_frames = candidate_frames[candidate_frames["rank_within_visit"] <= 5].copy()
    top_frames = top_frames.sort_values(["patient_folder", "visit_seq", "rank_within_visit"])

    study_patients = patients[
        [
            "patient_folder",
            "patient_label_guess",
            "first_exam_date",
            "last_exam_date",
            "estimated_first_visit_date",
            "estimated_last_visit_date",
            "estimated_visit_count",
            "total_confocal_like_frames",
            "max_subbasal_candidate_score",
            "max_subbasal_candidate_sdb",
            "likely_longitudinal_candidate",
            "priority_flag",
        ]
    ].copy()
    study_patients["study_patient_id"] = ""
    study_patients["include_patient"] = ""
    study_patients["cohort_decision"] = ""
    study_patients["intervention_confirmed"] = ""
    study_patients["surgery_date"] = ""
    study_patients["surgery_eye"] = ""
    study_patients["notes"] = ""

    study_visits = visits[
        [
            "patient_folder",
            "patient_label_guess",
            "visit_id_est",
            "visit_seq",
            "visit_date_est",
            "visit_start_est",
            "visit_end_est",
            "total_sdb_frames",
            "small_single_frame_sdb_count",
            "cornea_confocal_like",
            "cornea_surface_or_slitlamp_like",
            "anterior_segment_slitlamp_like",
            "best_subbasal_candidate_score",
            "best_sdb_file",
            "best_preview_abs_path",
            "priority_flag",
            "likely_longitudinal_candidate",
        ]
    ].copy()
    study_visits["study_patient_id"] = ""
    study_visits["include_visit"] = ""
    study_visits["visit_date_verified"] = ""
    study_visits["eye"] = ""
    study_visits["cornea_zone"] = ""
    study_visits["surgery_date_override"] = ""
    study_visits["visit_role_manual"] = ""
    study_visits["days_from_surgery_manual"] = ""
    study_visits["notes"] = ""

    nerve_metrics = study_visits[
        [
            "patient_folder",
            "visit_id_est",
            "visit_seq",
            "visit_date_est",
            "best_sdb_file",
            "best_preview_abs_path",
        ]
    ].copy()
    nerve_metrics["include_for_stats"] = ""
    nerve_metrics["study_patient_id"] = ""
    nerve_metrics["eye"] = ""
    nerve_metrics["cornea_zone"] = ""
    nerve_metrics["visit_date_final"] = ""
    nerve_metrics["surgery_date"] = ""
    nerve_metrics["days_from_surgery"] = ""
    nerve_metrics["standard_timepoint"] = ""
    nerve_metrics["analyzed_frame_count"] = ""
    nerve_metrics["selected_frame_ids"] = ""
    nerve_metrics["selection_method"] = ""
    for metric_name, _, _ in METRIC_CODEBOOK:
        nerve_metrics[metric_name] = ""
    nerve_metrics["quality_flag"] = ""
    nerve_metrics["notes"] = ""

    longitudinal_candidates = study_visits[
        (study_visits["likely_longitudinal_candidate"] == "yes") | (study_visits["priority_flag"] == "high")
    ].copy()
    longitudinal_candidates = longitudinal_candidates.sort_values(["patient_folder", "visit_seq"])

    codebook_rows = [
        {
            "column_name": "patient_folder",
            "sheet_name": "Study_Patients / Study_Visits / NerveMetrics",
            "meaning": "Stable HEYEX folder identifier and the safest link key across all tables.",
            "units_or_allowed_values": "text",
        },
        {
            "column_name": "visit_id_est",
            "sheet_name": "Study_Visits / NerveMetrics",
            "meaning": "Estimated visit key grouped by file modified date.",
            "units_or_allowed_values": "patient_folder_V##",
        },
        {
            "column_name": "visit_date_est",
            "sheet_name": "Study_Visits",
            "meaning": "Estimated visit date from preserved SDB file timestamps.",
            "units_or_allowed_values": "yyyy-mm-dd",
        },
        {
            "column_name": "standard_timepoint",
            "sheet_name": "Study_Visits / NerveMetrics",
            "meaning": "Final analysis bucket after surgery-date entry and optional manual correction.",
            "units_or_allowed_values": "preop, day1, week1, month1, month3, month6, month12, other_postop",
        },
    ]
    for metric_name, description, units in METRIC_CODEBOOK:
        codebook_rows.append(
            {
                "column_name": metric_name,
                "sheet_name": "NerveMetrics",
                "meaning": description,
                "units_or_allowed_values": units,
            }
        )

    patients_raw_path = output_dir / "analysis_patients_raw.csv"
    visits_raw_path = output_dir / "analysis_visits_raw.csv"
    candidate_frames_path = output_dir / "analysis_candidate_frames.csv"
    top_frames_path = output_dir / "analysis_top_frames.csv"
    study_patients_path = output_dir / "study_patients.csv"
    study_visits_path = output_dir / "study_visits.csv"
    nerve_metrics_path = output_dir / "nerve_metrics_template.csv"
    longitudinal_path = output_dir / "longitudinal_candidates.csv"
    codebook_path = output_dir / "analysis_codebook.csv"
    bundle_path = output_dir / "analysis_bundle.json"
    summary_path = output_dir / "analysis_summary.md"

    patients.to_csv(patients_raw_path, index=False)
    visits.to_csv(visits_raw_path, index=False)
    candidate_frames.to_csv(candidate_frames_path, index=False)
    top_frames.to_csv(top_frames_path, index=False)
    study_patients.to_csv(study_patients_path, index=False)
    study_visits.to_csv(study_visits_path, index=False)
    nerve_metrics.to_csv(nerve_metrics_path, index=False)
    longitudinal_candidates.to_csv(longitudinal_path, index=False)
    pd.DataFrame(codebook_rows).to_csv(codebook_path, index=False)

    summary = {
        "heyex_root": str(heyex_dir),
        "registry_root": str(registry_dir),
        "patients_with_section": int(len(study_patients)),
        "estimated_visits": int(len(study_visits)),
        "patients_with_2plus_visits": int((study_patients["estimated_visit_count"] >= 2).sum()),
        "likely_longitudinal_candidates": int((study_patients["likely_longitudinal_candidate"] == "yes").sum()),
        "top_frame_rows": int(len(top_frames)),
        "candidate_frame_rows": int(len(candidate_frames)),
    }

    bundle = {
        "summary": summary,
        "timepoint_windows": [
            {"label": label, "lower_day": lower, "upper_day": upper}
            for label, lower, upper in TIMEPOINT_WINDOWS
        ],
        "study_patients": _to_records(study_patients),
        "study_visits": _to_records(study_visits),
        "nerve_metrics": _to_records(nerve_metrics),
        "longitudinal_candidates": _to_records(longitudinal_candidates),
        "patients_raw": _to_records(
            patients[
                [
                    "patient_folder",
                    "patient_label_guess",
                    "first_exam_date",
                    "last_exam_date",
                    "estimated_first_visit_date",
                    "estimated_last_visit_date",
                    "estimated_visit_count",
                    "total_confocal_like_frames",
                    "max_subbasal_candidate_score",
                    "max_subbasal_candidate_sdb",
                    "likely_longitudinal_candidate",
                    "priority_flag",
                ]
            ]
        ),
        "visits_raw": _to_records(
            visits[
                [
                    "patient_folder",
                    "patient_label_guess",
                    "visit_id_est",
                    "visit_seq",
                    "visit_date_est",
                    "visit_start_est",
                    "visit_end_est",
                    "total_sdb_frames",
                    "cornea_confocal_like",
                    "cornea_surface_or_slitlamp_like",
                    "anterior_segment_slitlamp_like",
                    "best_subbasal_candidate_score",
                    "best_sdb_file",
                    "best_preview_abs_path",
                    "priority_flag",
                    "likely_longitudinal_candidate",
                ]
            ]
        ),
        "top_frames": _to_records(
            top_frames[
                [
                    "patient_folder",
                    "patient_label_guess",
                    "visit_id_est",
                    "visit_seq",
                    "visit_date_est",
                    "rank_within_visit",
                    "sdb_file",
                    "preview_class",
                    "subbasal_candidate_score",
                    "preview_score",
                    "preview_abs_path",
                    "sdb_abs_path",
                ]
            ]
        ),
        "codebook": codebook_rows,
        "stats_metrics": [
            "CNFD_n_per_mm2",
            "CNFL_mm_per_mm2",
            "CNBD_n_per_mm2",
            "CTBD_n_per_mm2",
            "CNFA_mm2_per_mm2",
            "CNFW_mm_per_mm2",
            "CNFracDim",
            "Tortuosity",
            "Langerhans_Total_n_per_mm2",
        ],
        "stats_timepoints": [label for label, _, _ in TIMEPOINT_WINDOWS] + ["other_postop"],
    }
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=True, indent=2), encoding="utf-8")

    top_longitudinal = longitudinal_candidates[
        [
            "patient_folder",
            "patient_label_guess",
            "visit_id_est",
            "visit_seq",
            "visit_date_est",
            "cornea_confocal_like",
            "best_subbasal_candidate_score",
            "best_sdb_file",
        ]
    ]
    summary_lines = [
        "# Confocal Analysis Package",
        "",
        f"- Patients with Section data: **{summary['patients_with_section']}**",
        f"- Estimated visits from file timestamps: **{summary['estimated_visits']}**",
        f"- Patients with >=2 estimated visits: **{summary['patients_with_2plus_visits']}**",
        f"- Likely longitudinal candidates: **{summary['likely_longitudinal_candidates']}**",
        f"- Candidate frame rows: **{summary['candidate_frame_rows']}**",
        f"- Top-frame rows kept for workbook review: **{summary['top_frame_rows']}**",
        "",
        "## Top longitudinal candidates",
        "",
    ]
    if top_longitudinal.empty:
        summary_lines.append("- No multi-visit confocal candidates were detected.")
    else:
        for row in top_longitudinal.itertuples(index=False):
            summary_lines.append(
                f"- `{row.patient_folder}` | visit `{row.visit_id_est}` | {pd.to_datetime(row.visit_date_est).strftime('%Y-%m-%d')} | "
                f"confocal frames `{int(row.cornea_confocal_like)}` | best score `{_safe_text(row.best_subbasal_candidate_score)}` | best file `{row.best_sdb_file}`"
            )
    summary_lines.extend(
        [
            "",
            "## Files",
            "",
            "- `analysis_patients_raw.csv`",
            "- `analysis_visits_raw.csv`",
            "- `analysis_candidate_frames.csv`",
            "- `analysis_top_frames.csv`",
            "- `study_patients.csv`",
            "- `study_visits.csv`",
            "- `nerve_metrics_template.csv`",
            "- `longitudinal_candidates.csv`",
            "- `analysis_codebook.csv`",
            "- `analysis_bundle.json`",
        ]
    )
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    return {
        "patients_raw_csv": patients_raw_path,
        "visits_raw_csv": visits_raw_path,
        "candidate_frames_csv": candidate_frames_path,
        "top_frames_csv": top_frames_path,
        "study_patients_csv": study_patients_path,
        "study_visits_csv": study_visits_path,
        "nerve_metrics_csv": nerve_metrics_path,
        "longitudinal_csv": longitudinal_path,
        "codebook_csv": codebook_path,
        "bundle_json": bundle_path,
        "summary_md": summary_path,
    }
