// Art.Suleimanov1924

import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [, , bundlePathArg, outputPathArg, previewDirArg] = process.argv;
if (!bundlePathArg || !outputPathArg) {
  console.error("Usage: node build_analysis_workbook.mjs <analysis_bundle.json> <output.xlsx> [preview_dir]");
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
  formula: "#EDF3F9",
  input: "#FFF2CC",
  border: "#C7D3DD",
  note: "#F7F9FB",
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
    match = value.match(/^(\d{4})\/(\d{2})\/(\d{2})$/);
    if (match) {
      const [, y, m, d] = match;
      return new Date(Number(y), Number(m) - 1, Number(d), 12, 0, 0);
    }
    match = value.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (match) {
      const [, y, m, d, hh, mm, ss] = match;
      return new Date(Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm), Number(ss ?? 0));
    }
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return parsed;
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

function writeMatrix(sheet, startCell, headers, rows) {
  const data = [headers, ...rows];
  const lastCol = headers.length;
  const lastRow = rows.length + 1;
  sheet.getRange(rangeA1(1, 1, lastCol, lastRow)).values = data;
  return { lastCol, lastRow };
}

function styleHeader(sheet, lastCol, fill) {
  const header = sheet.getRange(rangeA1(1, 1, lastCol, 1));
  header.format = {
    fill,
    font: { bold: true, color: fill === colors.title ? "#FFFFFF" : colors.text },
    borders: borderAll,
    wrapText: true,
  };
}

function styleBody(sheet, lastCol, lastRow) {
  if (lastRow < 2) return;
  const body = sheet.getRange(rangeA1(1, 2, lastCol, lastRow));
  body.format = {
    borders: borderAll,
    wrapText: true,
    font: { color: colors.text },
  };
}

function setDateFormat(sheet, cols, lastRow) {
  if (lastRow < 2) return;
  for (const col of cols) {
    sheet.getRange(`${col}2:${col}${lastRow}`).setNumberFormat("yyyy-mm-dd");
  }
}

function setDateTimeFormat(sheet, cols, lastRow) {
  if (lastRow < 2) return;
  for (const col of cols) {
    sheet.getRange(`${col}2:${col}${lastRow}`).setNumberFormat("yyyy-mm-dd hh:mm");
  }
}

function setNumericFormat(sheet, cols, lastRow, formatCode = "0.000") {
  if (lastRow < 2) return;
  for (const col of cols) {
    sheet.getRange(`${col}2:${col}${lastRow}`).setNumberFormat(formatCode);
  }
}

function applyColumnWidths(sheet, widths) {
  for (const [col, width] of Object.entries(widths)) {
    sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  }
}

function applyInputFill(sheet, colRanges, lastRow) {
  for (const col of colRanges) {
    const start = `${col}2:${col}${Math.max(lastRow, 2)}`;
    sheet.getRange(start).format = {
      fill: colors.input,
      borders: borderAll,
    };
  }
}

function applyFormulaFill(sheet, colRanges, lastRow) {
  for (const col of colRanges) {
    const start = `${col}2:${col}${Math.max(lastRow, 2)}`;
    sheet.getRange(start).format = {
      fill: colors.formula,
      borders: borderAll,
    };
  }
}

function setValidation(sheet, range, values) {
  sheet.getRange(range).dataValidation = {
    rule: { type: "list", values },
  };
}

function renderSheetNameToFileName(name) {
  return name.replace(/[^A-Za-z0-9_-]+/g, "_");
}

function buildRawSheet(sheetName, rows, columns, options = {}) {
  const sheet = workbook.worksheets.add(sheetName);
  sheet.showGridLines = false;
  const headers = columns.map((col) => col.header);
  const matrix = rows.map((row) =>
    columns.map((col) => {
      const value = row[col.key];
      if (col.type === "date" || col.type === "datetime") return excelDate(value);
      return value ?? null;
    }),
  );
  const { lastCol, lastRow } = writeMatrix(sheet, "A1", headers, matrix);
  styleHeader(sheet, lastCol, colors.rawHeader);
  styleBody(sheet, lastCol, lastRow);
  sheet.freezePanes.freezeRows(1);
  if (options.dateCols) setDateFormat(sheet, options.dateCols, lastRow);
  if (options.dateTimeCols) setDateTimeFormat(sheet, options.dateTimeCols, lastRow);
  if (options.numericCols) setNumericFormat(sheet, options.numericCols, lastRow, options.numericFormat ?? "0.000");
  applyColumnWidths(sheet, options.widths ?? {});
  return { sheet, lastRow, lastCol };
}

function buildReadmeSheet() {
  const sheet = workbook.worksheets.add("README");
  sheet.showGridLines = false;

  sheet.getRange("A1:H1").merge();
  sheet.getRange("A1").values = [["Confocal Longitudinal Analysis Pack"]];
  sheet.getRange("A1:H1").format = {
    fill: colors.title,
    font: { bold: true, color: "#FFFFFF" },
    borders: borderAll,
  };

  sheet.getRange("A3:B10").values = [
    ["Generated from", bundle.summary.heyex_root],
    ["Section patients", bundle.summary.patients_with_section],
    ["Estimated visits", bundle.summary.estimated_visits],
    ["Patients with >=2 visits", bundle.summary.patients_with_2plus_visits],
    ["Likely longitudinal candidates", bundle.summary.likely_longitudinal_candidates],
    ["Candidate frames", bundle.summary.candidate_frame_rows],
    ["Top review frames", bundle.summary.top_frame_rows],
    ["Registry root", bundle.summary.registry_root],
  ];
  sheet.getRange("A3:B10").format = { borders: borderAll, wrapText: true };
  sheet.getRange("A3:A10").format = { fill: colors.header, font: { bold: true }, borders: borderAll };

  sheet.getRange("A12:H19").values = [
    ["Recommended workflow", null, null, null, null, null, null, null],
    ["1", "Review Longitudinal_Candidates first. These are the strongest follow-up candidates.", null, null, null, null, null, null],
    ["2", "Fill Study_Patients: include_patient, cohort_decision, surgery_date, surgery_eye, and optional study_patient_id.", null, null, null, null, null, null],
    ["3", "Fill Study_Visits: confirm visit_date_verified, eye, cornea_zone, and manual timepoint overrides if needed.", null, null, null, null, null, null],
    ["4", "Use Top_Frames to choose the best confocal frames for morphometry or ACCMetrics export.", null, null, null, null, null, null],
    ["5", "Enter final morphometry in NerveMetrics. Only rows with include_for_stats = yes are used by Stats_Template.", null, null, null, null, null, null],
    ["6", "Stats_Template gives quick descriptive summaries. Final p-values should still be calculated in SPSS/R/Stata.", null, null, null, null, null, null],
    ["7", "Raw sheets are left untouched and act as the audit trail for the article.", null, null, null, null, null, null],
  ];
  sheet.getRange("A12:H19").format = { borders: borderAll, wrapText: true };
  sheet.getRange("A12:H12").merge();
  sheet.getRange("A12:H12").format = {
    fill: colors.header,
    font: { bold: true },
    borders: borderAll,
  };

  const timepointRows = bundle.timepoint_windows.map((row) => [
    row.label,
    row.lower_day ?? "",
    row.upper_day ?? "",
  ]);
  sheet.getRange("A22:C22").values = [["Auto timepoint", "Lower day", "Upper day"]];
  sheet.getRange(`A23:C${22 + timepointRows.length}`).values = timepointRows;
  sheet.getRange(`A22:C${22 + timepointRows.length}`).format = { borders: borderAll, wrapText: true };
  sheet.getRange("A22:C22").format = { fill: colors.header, font: { bold: true }, borders: borderAll };

  sheet.getRange("E22:H27").values = [
    ["Important note", null, null, null],
    ["patient_label_guess is heuristic.", null, null, null],
    ["patient_folder and visit_id_est are the safest link keys.", null, null, null],
    ["visit_date_est comes from preserved file timestamps and should be verified before final analysis.", null, null, null],
    ["standard_timepoint_final can be overridden manually when the default windows do not fit the protocol.", null, null, null],
    ["The workbook is designed for research workflow support, not as a validated clinical record.", null, null, null],
  ];
  sheet.getRange("E22:H27").format = { borders: borderAll, wrapText: true, fill: colors.note };
  sheet.getRange("E22:H22").merge();
  sheet.getRange("E22:H22").format = { fill: colors.header, font: { bold: true }, borders: borderAll };

  applyColumnWidths(sheet, {
    A: 12,
    B: 34,
    C: 16,
    D: 8,
    E: 20,
    F: 20,
    G: 20,
    H: 20,
  });
}

function buildStudyPatientsSheet() {
  const rows = bundle.study_patients;
  const sheet = workbook.worksheets.add("Study_Patients");
  sheet.showGridLines = false;

  const headers = [
    "patient_folder",
    "patient_label_guess",
    "study_patient_id",
    "include_patient",
    "cohort_decision",
    "intervention_confirmed",
    "surgery_date",
    "surgery_eye",
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
    "notes",
  ];
  const matrix = rows.map((row) => [
    row.patient_folder ?? null,
    row.patient_label_guess ?? null,
    row.study_patient_id ?? null,
    row.include_patient ?? null,
    row.cohort_decision ?? null,
    row.intervention_confirmed ?? null,
    null,
    row.surgery_eye ?? null,
    row.first_exam_date ?? null,
    row.last_exam_date ?? null,
    excelDate(row.estimated_first_visit_date),
    excelDate(row.estimated_last_visit_date),
    row.estimated_visit_count ?? null,
    row.total_confocal_like_frames ?? null,
    row.max_subbasal_candidate_score ?? null,
    row.max_subbasal_candidate_sdb ?? null,
    row.likely_longitudinal_candidate ?? null,
    row.priority_flag ?? null,
    row.notes ?? null,
  ]);
  const { lastCol, lastRow } = writeMatrix(sheet, "A1", headers, matrix);
  styleHeader(sheet, lastCol, colors.title);
  styleBody(sheet, lastCol, lastRow);
  sheet.freezePanes.freezeRows(1);

  setDateFormat(sheet, ["G", "K", "L"], lastRow);
  setNumericFormat(sheet, ["O"], lastRow, "0.000");
  applyInputFill(sheet, ["C", "D", "E", "F", "G", "H", "S"], lastRow);
  setValidation(sheet, `D2:D${lastRow}`, ["yes", "review", "no"]);
  setValidation(sheet, `E2:E${lastRow}`, ["target", "other", "uncertain"]);
  setValidation(sheet, `F2:F${lastRow}`, ["yes", "uncertain", "no"]);
  setValidation(sheet, `H2:H${lastRow}`, ["OD", "OS", "OU"]);
  applyColumnWidths(sheet, {
    A: 16,
    B: 18,
    C: 14,
    D: 12,
    E: 14,
    F: 14,
    G: 12,
    H: 10,
    I: 12,
    J: 12,
    K: 14,
    L: 14,
    M: 10,
    N: 12,
    O: 12,
    P: 14,
    Q: 14,
    R: 10,
    S: 24,
  });
}

function buildLongitudinalSheet() {
  buildRawSheet(
    "Longitudinal_Candidates",
    bundle.longitudinal_candidates,
    [
      { key: "patient_folder", header: "patient_folder" },
      { key: "patient_label_guess", header: "patient_label_guess" },
      { key: "visit_id_est", header: "visit_id_est" },
      { key: "visit_seq", header: "visit_seq" },
      { key: "visit_date_est", header: "visit_date_est", type: "date" },
      { key: "visit_start_est", header: "visit_start_est", type: "datetime" },
      { key: "visit_end_est", header: "visit_end_est", type: "datetime" },
      { key: "total_sdb_frames", header: "total_sdb_frames" },
      { key: "cornea_confocal_like", header: "cornea_confocal_like" },
      { key: "best_subbasal_candidate_score", header: "best_subbasal_candidate_score" },
      { key: "best_sdb_file", header: "best_sdb_file" },
      { key: "best_preview_abs_path", header: "best_preview_abs_path" },
      { key: "priority_flag", header: "priority_flag" },
    ],
    {
      dateCols: ["E"],
      dateTimeCols: ["F", "G"],
      numericCols: ["J"],
      widths: {
        A: 16,
        B: 18,
        C: 18,
        D: 8,
        E: 12,
        F: 18,
        G: 18,
        H: 10,
        I: 10,
        J: 12,
        K: 14,
        L: 40,
        M: 10,
      },
    },
  );
}

function buildStudyVisitsSheet() {
  const rows = bundle.study_visits;
  const sheet = workbook.worksheets.add("Study_Visits");
  sheet.showGridLines = false;

  const headers = [
    "patient_folder",
    "patient_label_guess",
    "study_patient_id",
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
    "include_visit",
    "visit_date_verified",
    "eye",
    "cornea_zone",
    "surgery_date_override",
    "visit_role_manual",
    "days_from_surgery_manual",
    "patient_include",
    "patient_cohort_decision",
    "surgery_date_resolved",
    "visit_date_final",
    "days_from_surgery",
    "standard_timepoint_auto",
    "standard_timepoint_final",
    "notes",
  ];
  const matrix = rows.map((row) => [
    row.patient_folder ?? null,
    row.patient_label_guess ?? null,
    null,
    row.visit_id_est ?? null,
    row.visit_seq ?? null,
    excelDate(row.visit_date_est),
    excelDate(row.visit_start_est),
    excelDate(row.visit_end_est),
    row.total_sdb_frames ?? null,
    row.small_single_frame_sdb_count ?? null,
    row.cornea_confocal_like ?? null,
    row.cornea_surface_or_slitlamp_like ?? null,
    row.anterior_segment_slitlamp_like ?? null,
    row.best_subbasal_candidate_score ?? null,
    row.best_sdb_file ?? null,
    row.best_preview_abs_path ?? null,
    row.priority_flag ?? null,
    row.likely_longitudinal_candidate ?? null,
    row.include_visit ?? null,
    null,
    row.eye ?? null,
    row.cornea_zone ?? null,
    null,
    row.visit_role_manual ?? null,
    row.days_from_surgery_manual ?? null,
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    row.notes ?? null,
  ]);

  const { lastCol, lastRow } = writeMatrix(sheet, "A1", headers, matrix);
  styleHeader(sheet, lastCol, colors.title);
  styleBody(sheet, lastCol, lastRow);
  sheet.freezePanes.freezeRows(1);

  const patientLast = bundle.study_patients.length + 1;
  const studyIdFormulas = [];
  const patientIncludeFormulas = [];
  const patientCohortFormulas = [];
  const surgeryResolvedFormulas = [];
  const visitFinalFormulas = [];
  const daysFormulas = [];
  const timepointAutoFormulas = [];
  const timepointFinalFormulas = [];

  for (let rowNum = 2; rowNum <= lastRow; rowNum += 1) {
    studyIdFormulas.push([
      `=IFERROR(VLOOKUP(A${rowNum},'Study_Patients'!$A$2:$S$${patientLast},3,FALSE),"")`,
    ]);
    patientIncludeFormulas.push([
      `=IFERROR(VLOOKUP(A${rowNum},'Study_Patients'!$A$2:$S$${patientLast},4,FALSE),"")`,
    ]);
    patientCohortFormulas.push([
      `=IFERROR(VLOOKUP(A${rowNum},'Study_Patients'!$A$2:$S$${patientLast},5,FALSE),"")`,
    ]);
    surgeryResolvedFormulas.push([
      `=IF(W${rowNum}<>"",W${rowNum},IFERROR(VLOOKUP(A${rowNum},'Study_Patients'!$A$2:$S$${patientLast},7,FALSE),""))`,
    ]);
    visitFinalFormulas.push([[`=IF(T${rowNum}<>"",T${rowNum},F${rowNum})`]][0]);
    daysFormulas.push([
      `=IF(Y${rowNum}<>"",Y${rowNum},IF(OR(AB${rowNum}="",AC${rowNum}=""),"",AC${rowNum}-AB${rowNum}))`,
    ]);
    timepointAutoFormulas.push([
      `=IF(AD${rowNum}="","",IF(AD${rowNum}<0,"preop",IF(AND(AD${rowNum}>=0,AD${rowNum}<=2),"day1",IF(AND(AD${rowNum}>=5,AD${rowNum}<=10),"week1",IF(AND(AD${rowNum}>=25,AD${rowNum}<=45),"month1",IF(AND(AD${rowNum}>=75,AD${rowNum}<=120),"month3",IF(AND(AD${rowNum}>=150,AD${rowNum}<=240),"month6",IF(AND(AD${rowNum}>=300,AD${rowNum}<=420),"month12","other_postop"))))))))`,
    ]);
    timepointFinalFormulas.push([[`=IF(X${rowNum}<>"",X${rowNum},AE${rowNum})`]][0]);
  }

  sheet.getRange(`C2:C${lastRow}`).formulas = studyIdFormulas;
  sheet.getRange(`Z2:Z${lastRow}`).formulas = patientIncludeFormulas;
  sheet.getRange(`AA2:AA${lastRow}`).formulas = patientCohortFormulas;
  sheet.getRange(`AB2:AB${lastRow}`).formulas = surgeryResolvedFormulas;
  sheet.getRange(`AC2:AC${lastRow}`).formulas = visitFinalFormulas;
  sheet.getRange(`AD2:AD${lastRow}`).formulas = daysFormulas;
  sheet.getRange(`AE2:AE${lastRow}`).formulas = timepointAutoFormulas;
  sheet.getRange(`AF2:AF${lastRow}`).formulas = timepointFinalFormulas;

  setDateFormat(sheet, ["F", "T", "W", "AB", "AC"], lastRow);
  setDateTimeFormat(sheet, ["G", "H"], lastRow);
  setNumericFormat(sheet, ["N", "Y", "AD"], lastRow, "0.000");
  applyInputFill(sheet, ["S", "T", "U", "V", "W", "X", "Y", "AG"], lastRow);
  applyFormulaFill(sheet, ["C", "Z", "AA", "AB", "AC", "AD", "AE", "AF"], lastRow);

  setValidation(sheet, `S2:S${lastRow}`, ["yes", "review", "no"]);
  setValidation(sheet, `U2:U${lastRow}`, ["OD", "OS", "OU", "unknown"]);
  setValidation(sheet, `V2:V${lastRow}`, ["center", "12h", "3h", "6h", "9h", "paracentral_other", "unknown"]);
  setValidation(sheet, `X2:X${lastRow}`, ["preop", "day1", "week1", "month1", "month3", "month6", "month12", "other_postop", "exclude"]);

  applyColumnWidths(sheet, {
    A: 16,
    B: 18,
    C: 14,
    D: 18,
    E: 8,
    F: 12,
    G: 18,
    H: 18,
    I: 10,
    J: 10,
    K: 10,
    L: 10,
    M: 10,
    N: 12,
    O: 14,
    P: 42,
    Q: 10,
    R: 12,
    S: 10,
    T: 12,
    U: 10,
    V: 14,
    W: 12,
    X: 12,
    Y: 12,
    Z: 10,
    AA: 12,
    AB: 12,
    AC: 12,
    AD: 12,
    AE: 14,
    AF: 14,
    AG: 22,
  });
}

function buildNerveMetricsSheet() {
  const rows = bundle.nerve_metrics;
  const sheet = workbook.worksheets.add("NerveMetrics");
  sheet.showGridLines = false;

  const headers = [
    "include_for_stats",
    "patient_folder",
    "study_patient_id",
    "visit_id_est",
    "visit_date_est",
    "best_sdb_file",
    "best_preview_abs_path",
    "eye",
    "cornea_zone",
    "visit_date_final",
    "surgery_date",
    "days_from_surgery",
    "standard_timepoint",
    "analyzed_frame_count",
    "selected_frame_ids",
    "selection_method",
    "CNFD_n_per_mm2",
    "CNFL_mm_per_mm2",
    "CNBD_n_per_mm2",
    "CTBD_n_per_mm2",
    "CNFA_mm2_per_mm2",
    "CNFW_mm_per_mm2",
    "CNFracDim",
    "Tortuosity",
    "Reflectivity_score",
    "Beadings_per_mm",
    "MainTrunks_count",
    "StromalNerveDensity",
    "StromalTrunkDiameter_um",
    "BasalEpithelialCellDensity",
    "Langerhans_Immature_n_per_mm2",
    "Langerhans_Mature_n_per_mm2",
    "Langerhans_Total_n_per_mm2",
    "KeratocyteDensity_AnteriorStroma",
    "quality_flag",
    "notes",
  ];
  const matrix = rows.map((row) => [
    row.include_for_stats ?? null,
    row.patient_folder ?? null,
    null,
    row.visit_id_est ?? null,
    excelDate(row.visit_date_est),
    row.best_sdb_file ?? null,
    row.best_preview_abs_path ?? null,
    null,
    null,
    null,
    null,
    null,
    null,
    row.analyzed_frame_count ?? null,
    row.selected_frame_ids ?? null,
    row.selection_method ?? null,
    row.CNFD_n_per_mm2 ?? null,
    row.CNFL_mm_per_mm2 ?? null,
    row.CNBD_n_per_mm2 ?? null,
    row.CTBD_n_per_mm2 ?? null,
    row.CNFA_mm2_per_mm2 ?? null,
    row.CNFW_mm_per_mm2 ?? null,
    row.CNFracDim ?? null,
    row.Tortuosity ?? null,
    row.Reflectivity_score ?? null,
    row.Beadings_per_mm ?? null,
    row.MainTrunks_count ?? null,
    row.StromalNerveDensity ?? null,
    row.StromalTrunkDiameter_um ?? null,
    row.BasalEpithelialCellDensity ?? null,
    row.Langerhans_Immature_n_per_mm2 ?? null,
    row.Langerhans_Mature_n_per_mm2 ?? null,
    null,
    row.KeratocyteDensity_AnteriorStroma ?? null,
    row.quality_flag ?? null,
    row.notes ?? null,
  ]);

  const { lastCol, lastRow } = writeMatrix(sheet, "A1", headers, matrix);
  styleHeader(sheet, lastCol, colors.title);
  styleBody(sheet, lastCol, lastRow);
  sheet.freezePanes.freezeRows(1);

  const visitsLast = bundle.study_visits.length + 1;
  const studyIdFormulas = [];
  const eyeFormulas = [];
  const zoneFormulas = [];
  const visitFinalFormulas = [];
  const surgeryDateFormulas = [];
  const daysFormulas = [];
  const timepointFormulas = [];
  const langerhansTotalFormulas = [];

  for (let rowNum = 2; rowNum <= lastRow; rowNum += 1) {
    studyIdFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$C$2:$C$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    eyeFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$U$2:$U$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    zoneFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$V$2:$V$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    visitFinalFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$AC$2:$AC$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    surgeryDateFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$AB$2:$AB$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    daysFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$AD$2:$AD$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    timepointFormulas.push([
      `=IFERROR(INDEX('Study_Visits'!$AF$2:$AF$${visitsLast},MATCH(D${rowNum},'Study_Visits'!$D$2:$D$${visitsLast},0)),"")`,
    ]);
    langerhansTotalFormulas.push([[`=IF(COUNT(AE${rowNum}:AF${rowNum})=0,"",SUM(AE${rowNum}:AF${rowNum}))`]][0]);
  }

  sheet.getRange(`C2:C${lastRow}`).formulas = studyIdFormulas;
  sheet.getRange(`H2:H${lastRow}`).formulas = eyeFormulas;
  sheet.getRange(`I2:I${lastRow}`).formulas = zoneFormulas;
  sheet.getRange(`J2:J${lastRow}`).formulas = visitFinalFormulas;
  sheet.getRange(`K2:K${lastRow}`).formulas = surgeryDateFormulas;
  sheet.getRange(`L2:L${lastRow}`).formulas = daysFormulas;
  sheet.getRange(`M2:M${lastRow}`).formulas = timepointFormulas;
  sheet.getRange(`AG2:AG${lastRow}`).formulas = langerhansTotalFormulas;

  setDateFormat(sheet, ["E", "J", "K"], lastRow);
  setNumericFormat(sheet, ["L", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "AB", "AC", "AD", "AE", "AF", "AG", "AH"], lastRow, "0.000");
  applyInputFill(sheet, ["A", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE", "AF", "AH", "AI", "AJ"], lastRow);
  applyFormulaFill(sheet, ["C", "H", "I", "J", "K", "L", "M", "AG"], lastRow);

  setValidation(sheet, `A2:A${lastRow}`, ["yes", "review", "no"]);
  setValidation(sheet, `P2:P${lastRow}`, ["ACCMetrics_auto", "manual_mask", "manual_count", "hybrid"]);
  setValidation(sheet, `AI2:AI${lastRow}`, ["ok", "review", "poor_quality"]);

  applyColumnWidths(sheet, {
    A: 10,
    B: 16,
    C: 14,
    D: 18,
    E: 12,
    F: 14,
    G: 42,
    H: 10,
    I: 12,
    J: 12,
    K: 12,
    L: 12,
    M: 14,
    N: 10,
    O: 18,
    P: 14,
    Q: 12,
    R: 12,
    S: 12,
    T: 12,
    U: 12,
    V: 12,
    W: 12,
    X: 12,
    Y: 12,
    Z: 12,
    AA: 12,
    AB: 12,
    AC: 12,
    AD: 14,
    AE: 14,
    AF: 14,
    AG: 14,
    AH: 14,
    AI: 12,
    AJ: 24,
  });
}

function buildStatsSheet() {
  const metrics = [
    ["CNFD_n_per_mm2", "Q"],
    ["CNFL_mm_per_mm2", "R"],
    ["CNBD_n_per_mm2", "S"],
    ["CTBD_n_per_mm2", "T"],
    ["CNFA_mm2_per_mm2", "U"],
    ["CNFW_mm_per_mm2", "V"],
    ["CNFracDim", "W"],
    ["Tortuosity", "X"],
    ["Langerhans_Total_n_per_mm2", "AG"],
  ];
  const timepoints = ["preop", "day1", "week1", "month1", "month3", "month6", "month12", "other_postop"];
  const sheet = workbook.worksheets.add("Stats_Template");
  sheet.showGridLines = false;

  sheet.getRange("A1:I1").values = [["Metric / Statistic", ...timepoints]];
  sheet.getRange("A1:I1").format = {
    fill: colors.title,
    font: { bold: true, color: "#FFFFFF" },
    borders: borderAll,
    wrapText: true,
  };

  let rowCursor = 2;
  const metricsLast = bundle.nerve_metrics.length + 1;
  for (const [metricName, metricCol] of metrics) {
    sheet.getRange(`A${rowCursor}:I${rowCursor}`).merge();
    sheet.getRange(`A${rowCursor}`).values = [[metricName]];
    sheet.getRange(`A${rowCursor}:I${rowCursor}`).format = {
      fill: colors.header,
      font: { bold: true },
      borders: borderAll,
    };
    rowCursor += 1;

    const statRows = [
      ["N", (tp) => `=COUNTIFS('NerveMetrics'!$A$2:$A$${metricsLast},"yes",'NerveMetrics'!$M$2:$M$${metricsLast},${tp},'NerveMetrics'!$${metricCol}$2:$${metricCol}$${metricsLast},"<>")`],
      ["Mean", (tp) => `=IFERROR(AVERAGE(FILTER('NerveMetrics'!$${metricCol}$2:$${metricCol}$${metricsLast},('NerveMetrics'!$A$2:$A$${metricsLast}="yes")*('NerveMetrics'!$M$2:$M$${metricsLast}=${tp}))),"")`],
      ["SD", (tp) => `=IFERROR(STDEV.S(FILTER('NerveMetrics'!$${metricCol}$2:$${metricCol}$${metricsLast},('NerveMetrics'!$A$2:$A$${metricsLast}="yes")*('NerveMetrics'!$M$2:$M$${metricsLast}=${tp}))),"")`],
      ["Median", (tp) => `=IFERROR(MEDIAN(FILTER('NerveMetrics'!$${metricCol}$2:$${metricCol}$${metricsLast},('NerveMetrics'!$A$2:$A$${metricsLast}="yes")*('NerveMetrics'!$M$2:$M$${metricsLast}=${tp}))),"")`],
      ["Q1", (tp) => `=IFERROR(QUARTILE.INC(FILTER('NerveMetrics'!$${metricCol}$2:$${metricCol}$${metricsLast},('NerveMetrics'!$A$2:$A$${metricsLast}="yes")*('NerveMetrics'!$M$2:$M$${metricsLast}=${tp})),1),"")`],
      ["Q3", (tp) => `=IFERROR(QUARTILE.INC(FILTER('NerveMetrics'!$${metricCol}$2:$${metricCol}$${metricsLast},('NerveMetrics'!$A$2:$A$${metricsLast}="yes")*('NerveMetrics'!$M$2:$M$${metricsLast}=${tp})),3),"")`],
    ];

    for (const [label, formulaBuilder] of statRows) {
      sheet.getRange(`A${rowCursor}`).values = [[label]];
      for (let i = 0; i < timepoints.length; i += 1) {
        const tpCell = `${colLetter(i + 2)}$1`;
        sheet.getRange(`${colLetter(i + 2)}${rowCursor}`).formulas = [[formulaBuilder(tpCell)]];
      }
      rowCursor += 1;
    }
  }

  sheet.getRange(`A2:I${rowCursor - 1}`).format = { borders: borderAll, wrapText: true };
  sheet.getRange(`B2:I${rowCursor - 1}`).setNumberFormat("0.000");
  sheet.freezePanes.freezeRows(1);
  applyColumnWidths(sheet, {
    A: 24,
    B: 12,
    C: 12,
    D: 12,
    E: 12,
    F: 12,
    G: 12,
    H: 12,
    I: 14,
  });
}

buildReadmeSheet();
buildLongitudinalSheet();
buildStudyPatientsSheet();
buildStudyVisitsSheet();
buildNerveMetricsSheet();
buildStatsSheet();

buildRawSheet(
  "Raw_Patients",
  bundle.patients_raw,
  [
    { key: "patient_folder", header: "patient_folder" },
    { key: "patient_label_guess", header: "patient_label_guess" },
    { key: "first_exam_date", header: "first_exam_date" },
    { key: "last_exam_date", header: "last_exam_date" },
    { key: "estimated_first_visit_date", header: "estimated_first_visit_date", type: "date" },
    { key: "estimated_last_visit_date", header: "estimated_last_visit_date", type: "date" },
    { key: "estimated_visit_count", header: "estimated_visit_count" },
    { key: "total_confocal_like_frames", header: "total_confocal_like_frames" },
    { key: "max_subbasal_candidate_score", header: "max_subbasal_candidate_score" },
    { key: "max_subbasal_candidate_sdb", header: "max_subbasal_candidate_sdb" },
    { key: "likely_longitudinal_candidate", header: "likely_longitudinal_candidate" },
    { key: "priority_flag", header: "priority_flag" },
  ],
  {
    dateCols: ["E", "F"],
    numericCols: ["I"],
    widths: {
      A: 16,
      B: 18,
      C: 12,
      D: 12,
      E: 14,
      F: 14,
      G: 10,
      H: 12,
      I: 12,
      J: 14,
      K: 12,
      L: 10,
    },
  },
);

buildRawSheet(
  "Raw_Visits",
  bundle.visits_raw,
  [
    { key: "patient_folder", header: "patient_folder" },
    { key: "patient_label_guess", header: "patient_label_guess" },
    { key: "visit_id_est", header: "visit_id_est" },
    { key: "visit_seq", header: "visit_seq" },
    { key: "visit_date_est", header: "visit_date_est", type: "date" },
    { key: "visit_start_est", header: "visit_start_est", type: "datetime" },
    { key: "visit_end_est", header: "visit_end_est", type: "datetime" },
    { key: "total_sdb_frames", header: "total_sdb_frames" },
    { key: "cornea_confocal_like", header: "cornea_confocal_like" },
    { key: "cornea_surface_or_slitlamp_like", header: "cornea_surface_or_slitlamp_like" },
    { key: "anterior_segment_slitlamp_like", header: "anterior_segment_slitlamp_like" },
    { key: "best_subbasal_candidate_score", header: "best_subbasal_candidate_score" },
    { key: "best_sdb_file", header: "best_sdb_file" },
    { key: "best_preview_abs_path", header: "best_preview_abs_path" },
    { key: "priority_flag", header: "priority_flag" },
    { key: "likely_longitudinal_candidate", header: "likely_longitudinal_candidate" },
  ],
  {
    dateCols: ["E"],
    dateTimeCols: ["F", "G"],
    numericCols: ["L"],
    widths: {
      A: 16,
      B: 18,
      C: 18,
      D: 8,
      E: 12,
      F: 18,
      G: 18,
      H: 10,
      I: 10,
      J: 10,
      K: 10,
      L: 12,
      M: 14,
      N: 42,
      O: 10,
      P: 12,
    },
  },
);

buildRawSheet(
  "Top_Frames",
  bundle.top_frames,
  [
    { key: "patient_folder", header: "patient_folder" },
    { key: "patient_label_guess", header: "patient_label_guess" },
    { key: "visit_id_est", header: "visit_id_est" },
    { key: "visit_seq", header: "visit_seq" },
    { key: "visit_date_est", header: "visit_date_est", type: "date" },
    { key: "rank_within_visit", header: "rank_within_visit" },
    { key: "sdb_file", header: "sdb_file" },
    { key: "preview_class", header: "preview_class" },
    { key: "subbasal_candidate_score", header: "subbasal_candidate_score" },
    { key: "preview_score", header: "preview_score" },
    { key: "preview_abs_path", header: "preview_abs_path" },
    { key: "sdb_abs_path", header: "sdb_abs_path" },
  ],
  {
    dateCols: ["E"],
    numericCols: ["I", "J"],
    widths: {
      A: 16,
      B: 18,
      C: 18,
      D: 8,
      E: 12,
      F: 8,
      G: 14,
      H: 20,
      I: 12,
      J: 12,
      K: 40,
      L: 40,
    },
  },
);

buildRawSheet(
  "Codebook",
  bundle.codebook,
  [
    { key: "column_name", header: "column_name" },
    { key: "sheet_name", header: "sheet_name" },
    { key: "meaning", header: "meaning" },
    { key: "units_or_allowed_values", header: "units_or_allowed_values" },
  ],
  {
    widths: {
      A: 22,
      B: 28,
      C: 42,
      D: 24,
    },
  },
);

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
  options: { useRegex: true, maxResults: 200 },
  summary: "formula error scan",
});
console.log(formulaErrors.ndjson);

for (const previewSpec of [
  { sheetName: "README", range: "A1:H29" },
  { sheetName: "Longitudinal_Candidates", range: "A1:M10" },
  { sheetName: "Study_Patients", range: "A1:S20" },
  { sheetName: "Study_Visits", range: "A1:AG20" },
  { sheetName: "NerveMetrics", range: "A1:AJ20" },
  { sheetName: "Stats_Template", range: "A1:I70" },
  { sheetName: "Raw_Patients", range: "A1:L20" },
  { sheetName: "Raw_Visits", range: "A1:P20" },
  { sheetName: "Top_Frames", range: "A1:L20" },
  { sheetName: "Codebook", range: "A1:D25" },
]) {
  const blob = await workbook.render({
    sheetName: previewSpec.sheetName,
    range: previewSpec.range,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${renderSheetNameToFileName(previewSpec.sheetName)}.png`),
    new Uint8Array(await blob.arrayBuffer()),
  );
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

console.log(JSON.stringify({ outputPath, previewDir }, null, 2));
