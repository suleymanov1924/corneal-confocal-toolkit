// Art.Suleimanov1924

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [, , bundlePathArg, outputPathArg, previewDirArg] = process.argv;
if (!bundlePathArg || !outputPathArg) {
  console.error("Usage: node build_proxy_cohort_workbook.mjs <proxy_cohort_bundle.json> <output.xlsx> [preview_dir]");
  process.exit(2);
}

const bundlePath = path.resolve(bundlePathArg);
const outputPath = path.resolve(outputPathArg);
const previewDir = path.resolve(previewDirArg ?? path.join(path.dirname(outputPath), "previews"));

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const bundle = JSON.parse(await fs.readFile(bundlePath, "utf8"));
const workbook = Workbook.create();

const colors = {
  title: "#0B5D7A",
  header: "#D9EAF7",
  rawHeader: "#E2F0D9",
  input: "#FFF2CC",
  note: "#F7F9FB",
  border: "#C7D3DD",
  text: "#1F2937",
};
const borderAll = { preset: "all", style: "thin", color: colors.border };

function excelDate(value) {
  if (!value) return null;
  if (typeof value === "string") {
    let match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
      const [, y, m, d] = match;
      return new Date(Number(y), Number(m) - 1, Number(d), 12, 0, 0);
    }
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed;
}

function colLetter(idx) {
  let n = idx;
  let s = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    s = String.fromCharCode(65 + rem) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function rangeA1(colStart, rowStart, colEnd, rowEnd) {
  return `${colLetter(colStart)}${rowStart}:${colLetter(colEnd)}${rowEnd}`;
}

function writeTable(sheet, headers, rows) {
  const matrix = [headers, ...rows];
  const lastCol = headers.length;
  const lastRow = rows.length + 1;
  sheet.getRange(rangeA1(1, 1, lastCol, lastRow)).values = matrix;
  sheet.getRange(rangeA1(1, 1, lastCol, 1)).format = {
    fill: colors.title,
    font: { bold: true, color: "#FFFFFF" },
    borders: borderAll,
    wrapText: true,
  };
  if (lastRow >= 2) {
    sheet.getRange(rangeA1(1, 2, lastCol, lastRow)).format = {
      borders: borderAll,
      wrapText: true,
      font: { color: colors.text },
    };
  }
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  return { lastCol, lastRow };
}

function applyWidths(sheet, widths) {
  for (const [col, width] of Object.entries(widths)) {
    sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  }
}

function setDateColumns(sheet, cols, lastRow) {
  if (lastRow < 2) return;
  for (const col of cols) {
    sheet.getRange(`${col}2:${col}${lastRow}`).setNumberFormat("yyyy-mm-dd");
  }
}

function setNumberColumns(sheet, cols, lastRow, formatCode = "0.000") {
  if (lastRow < 2) return;
  for (const col of cols) {
    sheet.getRange(`${col}2:${col}${lastRow}`).setNumberFormat(formatCode);
  }
}

function renderName(name) {
  return name.replace(/[^A-Za-z0-9_-]+/g, "_");
}

function buildReadme() {
  const sheet = workbook.worksheets.add("README");
  sheet.showGridLines = false;

  sheet.getRange("A1:H1").merge();
  sheet.getRange("A1").values = [["Longitudinal Proxy Paired Cohort"]];
  sheet.getRange("A1:H1").format = {
    fill: colors.title,
    font: { bold: true, color: "#FFFFFF" },
    borders: borderAll,
  };

  sheet.getRange("A3:B9").values = [
    ["Candidate patients", bundle.summary.candidate_patient_count],
    ["Excluded multi-visit patients", bundle.summary.excluded_multivisit_count],
    ["Analyzed frames", bundle.summary.frame_rows],
    ["Visit summaries", bundle.summary.visit_rows],
    ["Paired rows", bundle.summary.pair_rows],
    ["Top frames per visit", bundle.summary.top_n_frames_per_visit],
    ["Min confocal frames rule", bundle.summary.min_total_confocal_frames],
  ];
  sheet.getRange("A3:B9").format = { borders: borderAll, wrapText: true };
  sheet.getRange("A3:A9").format = { fill: colors.header, font: { bold: true }, borders: borderAll };

  const notes = bundle.notes.map((line) => [line, null, null, null]);
  sheet.getRange("A12:D12").values = [["Assumptions", null, null, null]];
  sheet.getRange("A12:D12").merge();
  sheet.getRange("A12:D12").format = { fill: colors.header, font: { bold: true }, borders: borderAll };
  if (notes.length > 0) {
    sheet.getRange(`A13:D${12 + notes.length}`).values = notes;
    sheet.getRange(`A13:D${12 + notes.length}`).format = { borders: borderAll, wrapText: true, fill: colors.note };
  }

  sheet.getRange("F3:H7").values = [
    ["How to use", null, null],
    ["1", "Use Candidate_Pairs for the manuscript-style patient table."],
    ["2", "Use Cohort_Stats for cohort-level before/after proxy summaries and Wilcoxon p-values."],
    ["3", "Use Visit_Summary and Frame_Metrics for QC and methods traceability."],
    ["4", "Confirm true intervention status and procedure dates before treating these pairs as final publication results."],
  ];
  sheet.getRange("F3:H7").format = { borders: borderAll, wrapText: true };
  sheet.getRange("F3:H3").merge();
  sheet.getRange("F3:H3").format = { fill: colors.header, font: { bold: true }, borders: borderAll };

  applyWidths(sheet, { A: 26, B: 18, C: 16, D: 16, F: 12, G: 42, H: 12 });
}

function buildCandidatePairs() {
  const rows = bundle.paired_candidate_summary.map((row) => [
    row.patient_folder ?? null,
    row.patient_label_guess ?? null,
    excelDate(row.baseline_visit_date),
    excelDate(row.followup_visit_date),
    row.followup_interval_days ?? null,
    row.followup_interval_bucket_candidate ?? null,
    row.baseline_frames_used ?? null,
    row.followup_frames_used ?? null,
    row.CNFD_proxy_n_per_mm2_baseline_mean ?? null,
    row.CNFD_proxy_n_per_mm2_followup_mean ?? null,
    row.CNFD_proxy_n_per_mm2_delta_abs ?? null,
    row.CNFL_mm_per_mm2_baseline_mean ?? null,
    row.CNFL_mm_per_mm2_followup_mean ?? null,
    row.CNFL_mm_per_mm2_delta_abs ?? null,
    row.CNBD_proxy_n_per_mm2_baseline_mean ?? null,
    row.CNBD_proxy_n_per_mm2_followup_mean ?? null,
    row.CNBD_proxy_n_per_mm2_delta_abs ?? null,
    row.CTBD_proxy_n_per_mm2_baseline_mean ?? null,
    row.CTBD_proxy_n_per_mm2_followup_mean ?? null,
    row.CTBD_proxy_n_per_mm2_delta_abs ?? null,
    row.CNFA_mm2_per_mm2_baseline_mean ?? null,
    row.CNFA_mm2_per_mm2_followup_mean ?? null,
    row.CNFA_mm2_per_mm2_delta_abs ?? null,
    row.CNFW_proxy_um_baseline_mean ?? null,
    row.CNFW_proxy_um_followup_mean ?? null,
    row.CNFW_proxy_um_delta_abs ?? null,
    row.CNFracDim_proxy_baseline_mean ?? null,
    row.CNFracDim_proxy_followup_mean ?? null,
    row.CNFracDim_proxy_delta_abs ?? null,
    row.Tortuosity_proxy_baseline_mean ?? null,
    row.Tortuosity_proxy_followup_mean ?? null,
    row.Tortuosity_proxy_delta_abs ?? null,
  ]);
  const headers = [
    "patient_folder",
    "patient_label_guess",
    "baseline_visit_date",
    "followup_visit_date",
    "followup_interval_days",
    "followup_interval_bucket_candidate",
    "baseline_frames_used",
    "followup_frames_used",
    "CNFD_base",
    "CNFD_follow",
    "CNFD_delta",
    "CNFL_base",
    "CNFL_follow",
    "CNFL_delta",
    "CNBD_base",
    "CNBD_follow",
    "CNBD_delta",
    "CTBD_base",
    "CTBD_follow",
    "CTBD_delta",
    "CNFA_base",
    "CNFA_follow",
    "CNFA_delta",
    "CNFW_base",
    "CNFW_follow",
    "CNFW_delta",
    "CNFracDim_base",
    "CNFracDim_follow",
    "CNFracDim_delta",
    "Tortuosity_base",
    "Tortuosity_follow",
    "Tortuosity_delta",
  ];
  const sheet = workbook.worksheets.add("Candidate_Pairs");
  const { lastRow } = writeTable(sheet, headers, rows);
  setDateColumns(sheet, ["C", "D"], lastRow);
  setNumberColumns(sheet, ["E", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD"], lastRow);
  applyWidths(sheet, {
    A: 16, B: 16, C: 12, D: 12, E: 10, F: 20, G: 10, H: 10,
    I: 10, J: 10, K: 10, L: 10, M: 10, N: 10, O: 10, P: 10, Q: 10, R: 10, S: 10, T: 10,
    U: 10, V: 10, W: 10, X: 10, Y: 10, Z: 10, AA: 10, AB: 10, AC: 10, AD: 10,
  });
}

function buildVisitSummary() {
  const rows = bundle.per_visit_proxy_summary.map((row) => [
    row.patient_folder ?? null,
    row.patient_label_guess ?? null,
    row.visit_id_est ?? null,
    row.visit_date_est ? excelDate(row.visit_date_est) : null,
    row.candidate_role ?? null,
    row.interval_days_from_first_visit ?? null,
    row.interval_bucket_candidate ?? null,
    row.available_confocal_like_frames ?? null,
    row.selected_top_frames ?? null,
    row.CNFD_proxy_n_per_mm2_mean_sd ?? null,
    row.CNFL_mm_per_mm2_mean_sd ?? null,
    row.CNBD_proxy_n_per_mm2_mean_sd ?? null,
    row.CTBD_proxy_n_per_mm2_mean_sd ?? null,
    row.CNFA_mm2_per_mm2_mean_sd ?? null,
    row.CNFW_proxy_um_mean_sd ?? null,
    row.CNFracDim_proxy_mean_sd ?? null,
    row.Tortuosity_proxy_mean_sd ?? null,
    row.best_sdb_file ?? null,
  ]);
  const headers = [
    "patient_folder", "patient_label_guess", "visit_id_est", "visit_date_est", "candidate_role",
    "interval_days_from_first_visit", "interval_bucket_candidate", "available_confocal_like_frames",
    "selected_top_frames", "CNFD_mean_sd", "CNFL_mean_sd", "CNBD_mean_sd", "CTBD_mean_sd",
    "CNFA_mean_sd", "CNFW_mean_sd", "CNFracDim_mean_sd", "Tortuosity_mean_sd", "best_sdb_file",
  ];
  const sheet = workbook.worksheets.add("Visit_Summary");
  const { lastRow } = writeTable(sheet, headers, rows);
  setDateColumns(sheet, ["D"], lastRow);
  applyWidths(sheet, {
    A: 16, B: 16, C: 18, D: 12, E: 18, F: 12, G: 22, H: 10, I: 10,
    J: 16, K: 16, L: 16, M: 16, N: 16, O: 16, P: 16, Q: 16, R: 14,
  });
}

function buildCohortStats() {
  const rows = bundle.cohort_paired_stats.map((row) => [
    row.metric ?? null,
    row.metric_label ?? null,
    row.n_pairs ?? null,
    row.baseline_mean_sd ?? null,
    row.baseline_median_iqr ?? null,
    row.followup_mean_sd ?? null,
    row.followup_median_iqr ?? null,
    row.delta_mean_sd ?? null,
    row.delta_pct_mean_sd ?? null,
    row.wilcoxon_p ?? null,
  ]);
  const headers = [
    "metric", "metric_label", "n_pairs", "baseline_mean_sd", "baseline_median_iqr",
    "followup_mean_sd", "followup_median_iqr", "delta_mean_sd", "delta_pct_mean_sd", "wilcoxon_p",
  ];
  const sheet = workbook.worksheets.add("Cohort_Stats");
  const { lastRow } = writeTable(sheet, headers, rows);
  setNumberColumns(sheet, ["J"], lastRow, "0.0000");
  applyWidths(sheet, { A: 20, B: 18, C: 8, D: 18, E: 22, F: 18, G: 22, H: 18, I: 18, J: 10 });
}

function buildFrameMetrics() {
  const rows = bundle.per_frame_proxy_metrics.map((row) => [
    row.patient_folder ?? null,
    row.patient_label_guess ?? null,
    row.visit_id_est ?? null,
    row.visit_date_est ? excelDate(row.visit_date_est) : null,
    row.candidate_role ?? null,
    row.frame_rank_within_visit ?? null,
    row.sdb_file ?? null,
    row.subbasal_candidate_score ?? null,
    row.CNFD_proxy_n_per_mm2 ?? null,
    row.CNFL_mm_per_mm2 ?? null,
    row.CNBD_proxy_n_per_mm2 ?? null,
    row.CTBD_proxy_n_per_mm2 ?? null,
    row.CNFA_mm2_per_mm2 ?? null,
    row.CNFW_proxy_um ?? null,
    row.CNFracDim_proxy ?? null,
    row.Tortuosity_proxy ?? null,
    row.preview_path ?? null,
    row.overlay_file ?? null,
  ]);
  const headers = [
    "patient_folder", "patient_label_guess", "visit_id_est", "visit_date_est", "candidate_role",
    "frame_rank_within_visit", "sdb_file", "subbasal_candidate_score", "CNFD_proxy_n_per_mm2",
    "CNFL_mm_per_mm2", "CNBD_proxy_n_per_mm2", "CTBD_proxy_n_per_mm2", "CNFA_mm2_per_mm2",
    "CNFW_proxy_um", "CNFracDim_proxy", "Tortuosity_proxy", "preview_path", "overlay_file",
  ];
  const sheet = workbook.worksheets.add("Frame_Metrics");
  const { lastRow } = writeTable(sheet, headers, rows);
  setDateColumns(sheet, ["D"], lastRow);
  setNumberColumns(sheet, ["H", "I", "J", "K", "L", "M", "N", "O", "P"], lastRow);
  applyWidths(sheet, {
    A: 16, B: 16, C: 18, D: 12, E: 18, F: 8, G: 14, H: 12,
    I: 12, J: 12, K: 12, L: 12, M: 12, N: 12, O: 12, P: 12, Q: 42, R: 20,
  });
}

function buildExcluded() {
  const rows = bundle.excluded_multivisit.map((row) => [
    row.patient_folder ?? null,
    row.patient_label_guess ?? null,
    row.estimated_visit_count ?? null,
    row.total_confocal_like_frames ?? null,
    row.priority_flag ?? null,
    row.exclusion_reason ?? null,
  ]);
  const headers = [
    "patient_folder", "patient_label_guess", "estimated_visit_count",
    "total_confocal_like_frames", "priority_flag", "exclusion_reason",
  ];
  const sheet = workbook.worksheets.add("Excluded_Multivisit");
  writeTable(sheet, headers, rows);
  applyWidths(sheet, { A: 16, B: 18, C: 12, D: 14, E: 10, F: 28 });
}

buildReadme();
buildCandidatePairs();
buildVisitSummary();
buildCohortStats();
buildFrameMetrics();
buildExcluded();

const inspectSummary = await workbook.inspect({
  kind: "sheet,table",
  maxChars: 6000,
  tableMaxRows: 6,
  tableMaxCols: 8,
  tableMaxCellChars: 80,
});
console.log(inspectSummary.ndjson);

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(formulaErrors.ndjson);

for (const previewSpec of [
  { sheetName: "README", range: "A1:H20" },
  { sheetName: "Candidate_Pairs", range: "A1:AD10" },
  { sheetName: "Visit_Summary", range: "A1:R10" },
  { sheetName: "Cohort_Stats", range: "A1:J12" },
  { sheetName: "Frame_Metrics", range: "A1:R20" },
  { sheetName: "Excluded_Multivisit", range: "A1:F10" },
]) {
  const blob = await workbook.render({
    sheetName: previewSpec.sheetName,
    range: previewSpec.range,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${renderName(previewSpec.sheetName)}.png`),
    new Uint8Array(await blob.arrayBuffer()),
  );
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

console.log(JSON.stringify({ outputPath, previewDir }, null, 2));
