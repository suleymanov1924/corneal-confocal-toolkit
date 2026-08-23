# Corneal Confocal Toolkit

Author: `Art.Suleimanov1924`

Research toolkit for working with corneal confocal microscopy archives from Heidelberg HRT-III / Rostock Cornea Module.

The public package is intentionally neutral and can be used for different study designs, not only one procedure or cohort.

## What it does

- scans a HEYEX export and builds a longitudinal patient registry
- inspects RAW, BMP, and SDB assets
- finds candidate subbasal nerve plexus frames
- computes nerve metrics from selected images
- prepares analysis-ready tables for Excel, R, SPSS, or Python
- generates a compact report for research workflows

## Current status

This is a research MVP, not a finished clinical product.

Already implemented:

- HEYEX archive scanning
- patient and visit registry export
- frame-level confocal analysis
- nerve segmentation and metric extraction
- longitudinal cohort preparation
- summary report generation

Still worth improving:

- stronger automatic layer detection
- better quality control for low-contrast frames
- validation against manual expert annotation
- packaging as a desktop interface

## Repository layout

- `confocaltoolkit/` - core parsing, analysis, cohort, and reporting logic
- `scripts/` - workbook builders and helper scripts
- `run_confocal_toolkit.py` - neutral entry point
- `analyze_confocal.py` - standalone image-analysis helpers

## Quick start

```powershell
python run_confocal_toolkit.py scan-heyex --heyex-dir "D:\\Data\\HEYEX" --output-dir confocal_output\\heyex_scan
python run_confocal_toolkit.py analyze --study-dir "D:\\Data\\Patient001" --output-dir confocal_output\\analyze
python run_confocal_toolkit.py build-registry --heyex-dir "D:\\Data\\HEYEX" --output-dir confocal_output\\registry
python run_confocal_toolkit.py prepare-analysis-data --heyex-dir "D:\\Data\\HEYEX" --registry-dir confocal_output\\registry --output-dir analysis_output
```

## Outputs

- patient-level registry with visits and eye laterality
- image-level quality and metric tables
- analysis-ready longitudinal dataset
- HTML report
- workbook templates for statistical review

## Data safety

Clinical data are intentionally excluded from this public package. Do not publish:

- raw HEYEX archives
- exported patient images
- spreadsheets with identifiers
- generated reports containing personal health data

Use a de-identified copy of your study data outside the repository.

## Research note

This toolkit is designed for research support and exploratory analysis. It is not a certified medical device and should not be used as the sole basis for clinical decisions.
