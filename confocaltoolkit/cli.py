"""Art.Suleimanov1924."""

from __future__ import annotations

import argparse
from pathlib import Path

from .analyzer import analyze_study
from .cohort import build_proxy_cohort
from .heyex import build_cohort_registry, extract_sdb_previews, scan_heyex_tree
from .inspect import inspect_study, write_contact_sheet, write_inventory, write_selection_template
from .research import prepare_analysis_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confocaltoolkit",
        description="Research toolkit for Heidelberg HRT-III corneal confocal analysis.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Scan a study folder and suggest candidate subbasal frames.")
    inspect_parser.add_argument("--study-dir", type=Path, default=Path("."), help="Folder containing Heidelberg BMP/RAW files.")
    inspect_parser.add_argument("--output-dir", type=Path, default=Path("confocal_output") / "inspect", help="Where to write inventory and selection template.")
    inspect_parser.add_argument("--top-n", type=int, default=8, help="How many frames to pre-mark in the selection template.")

    analyze_parser = subparsers.add_parser("analyze", help="Run metric extraction on selected frames and export the report.")
    analyze_parser.add_argument("--study-dir", type=Path, default=Path("."), help="Folder containing Heidelberg BMP/RAW files.")
    analyze_parser.add_argument("--output-dir", type=Path, default=Path("confocal_output") / "analyze", help="Where to write report artifacts.")
    analyze_parser.add_argument("--selection-file", type=Path, default=None, help="CSV file with include/eye/confidence columns.")
    analyze_parser.add_argument("--auto-select-count", type=int, default=8, help="Used only when selection file is not supplied.")

    heyex_parser = subparsers.add_parser("scan-heyex", help="Build an inventory from a full HEYEX folder with all patients.")
    heyex_parser.add_argument("--heyex-dir", type=Path, required=True, help="Root HEYEX folder containing patients/, data/, plugins/, etc.")
    heyex_parser.add_argument("--output-dir", type=Path, default=Path("confocal_output") / "heyex_scan", help="Where to write the inventory workbook and CSV files.")

    sdb_parser = subparsers.add_parser("extract-sdb", help="Extract preview JPEGs from one SDB container.")
    sdb_parser.add_argument("--sdb-file", type=Path, required=True, help="Path to an SDB file.")
    sdb_parser.add_argument("--output-dir", type=Path, default=Path("confocal_output") / "sdb_extract", help="Where to save preview JPEGs and a contact sheet.")
    sdb_parser.add_argument("--limit", type=int, default=12, help="Maximum number of embedded JPEG previews to extract.")

    cohort_parser = subparsers.add_parser("build-registry", help="Build a registry from HEYEX Section patients and their SDB frames.")
    cohort_parser.add_argument("--heyex-dir", type=Path, required=True, help="Root HEYEX folder.")
    cohort_parser.add_argument("--output-dir", type=Path, default=Path("confocal_output") / "registry", help="Where to write patient/frame tables and preview images.")

    analysis_parser = subparsers.add_parser("prepare-analysis-data", help="Prepare patient/visit/frame tables for a longitudinal study workbook.")
    analysis_parser.add_argument("--heyex-dir", type=Path, required=True, help="Root HEYEX folder.")
    analysis_parser.add_argument("--registry-dir", type=Path, default=Path("confocal_output") / "registry", help="Directory created by build-registry.")
    analysis_parser.add_argument("--output-dir", type=Path, default=Path("analysis_output"), help="Where to write analysis-ready tables and JSON bundle.")

    proxy_parser = subparsers.add_parser("build-proxy-cohort", help="Analyze likely longitudinal HEYEX candidates and build a paired proxy-metrics cohort.")
    proxy_parser.add_argument("--analysis-dir", type=Path, default=Path("analysis_output"), help="Directory created by prepare-analysis-data.")
    proxy_parser.add_argument("--output-dir", type=Path, default=Path("confocal_output") / "proxy_cohort", help="Where to write paired proxy-metric outputs.")
    proxy_parser.add_argument("--top-n-frames", type=int, default=5, help="How many top confocal-like frames to analyze per visit.")
    proxy_parser.add_argument("--min-total-confocal-frames", type=int, default=20, help="Minimum total cornea_confocal_like frames required to keep a multi-visit patient.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inspect":
        frames, rows = inspect_study(args.study_dir)
        csv_path, xlsx_path = write_inventory(rows, args.output_dir)
        template_path = write_selection_template(rows, args.output_dir, top_n=args.top_n)
        contact_path = write_contact_sheet(frames, rows, args.output_dir)
        print(f"Inventory CSV: {csv_path}")
        print(f"Inventory XLSX: {xlsx_path}")
        print(f"Selection template: {template_path}")
        print(f"Contact sheet: {contact_path}")
        return 0

    if args.command == "analyze":
        outputs = analyze_study(
            study_dir=args.study_dir,
            output_dir=args.output_dir,
            selection_file=args.selection_file,
            auto_select_count=args.auto_select_count,
        )
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0

    if args.command == "scan-heyex":
        outputs = scan_heyex_tree(args.heyex_dir, args.output_dir)
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0

    if args.command == "extract-sdb":
        outputs = extract_sdb_previews(args.sdb_file, args.output_dir, limit=args.limit)
        for path in outputs:
            print(path)
        return 0

    if args.command == "build-registry":
        outputs = build_cohort_registry(args.heyex_dir, args.output_dir)
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0

    if args.command == "prepare-analysis-data":
        outputs = prepare_analysis_data(
            heyex_dir=args.heyex_dir,
            registry_dir=args.registry_dir,
            output_dir=args.output_dir,
        )
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0

    if args.command == "build-proxy-cohort":
        outputs = build_proxy_cohort(
            analysis_dir=args.analysis_dir,
            output_dir=args.output_dir,
            top_n_frames=args.top_n_frames,
            min_total_confocal_frames=args.min_total_confocal_frames,
        )
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
