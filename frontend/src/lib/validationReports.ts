/**
 * BOBA Validation + Reports V1 - presentation logic only.
 *
 * This module renders what the backend projection already decided. It holds no
 * authority: it never derives a verdict, never turns missing evidence into a
 * pass, never resolves a conflict, never selects a "best" result and never
 * reports production readiness. Every state shown here is accompanied by the
 * owner fact the backend transcribed.
 */

export const MATRIX_STATES = [
  "PASS",
  "FAIL",
  "BLOCKED",
  "SKIPPED",
  "NOT_RUN",
  "STALE",
  "MISSING",
] as const;

export type MatrixState = (typeof MATRIX_STATES)[number];

/** Only these two states carry an actual validation verdict. */
export const VERDICT_STATES: readonly MatrixState[] = ["PASS", "FAIL"] as const;

export type ValidationMatrixCell = {
  cell_id: string;
  owner_module_id: string;
  owner_fact: boolean;
  owner_status: string;
  check_run_id: string;
  validation_run_id: string;
  plan_check_id: string;
  validator_id: string;
  validator_version: string;
  category: string;
  required: boolean;
  attempt_number: number;
  result_id: string;
  result_status: string;
  result_digest: string;
  input_digest: string;
  environment_digest: string;
  evidence_ids: string[];
  started_at: string;
  completed_at: string;
  duration_seconds: number | null;
  exit_code: number | null;
  failed_assertions: string[];
  unavailable_assertions: string[];
  failure_categories: string[];
  bounded_diagnostics: string[];
  owner_warnings: string[];
  workflow_revision: number;
  derived_state: MatrixState;
  owner_reported_state: MatrixState;
  derived_state_reason: string;
  derived_title: string;
  verdict_available: boolean;
  evidence_present: boolean;
  stale: boolean;
  stale_reasons: string[];
  binding_digest: string;
};

export type ValidationBinding = {
  binding_id: string;
  project_id: string;
  workflow_run_id: string;
  stage_instance_id: string;
  target_type: string;
  target_id: string;
  target_digest: string;
  workflow_revision: number;
  artifact_digest: string;
  validator_version: string;
  validation_request_id: string;
  binding_digest: string;
  bound: boolean;
  reuse_valid: boolean;
  invalidated_dimensions: string[];
  derived_summary: string;
};

export type ValidationMatrix = {
  matrix_id: string;
  project_id: string;
  validation_run_id: string;
  binding: ValidationBinding;
  cells: ValidationMatrixCell[];
  state_counts: Record<string, number>;
  total_cells: number;
  truncated: boolean;
  required_verdict_complete: boolean;
  evidence_complete: boolean;
  any_conflict: boolean;
  notices: string[];
  warnings: string[];
  limitations: string[];
};

export type ValidationSummary = {
  summary_id: string;
  validation_run_id: string;
  run_status: string;
  suite_decision: string;
  suite_decision_id: string;
  owner_decision_summary: string;
  required_checks_complete: boolean;
  required_checks_passed: boolean;
  technical_validation_passed: boolean;
  human_review_required: boolean;
  derived_status_title: string;
  state_counts: Record<string, number>;
  validation_evidence_available: boolean;
  evidence_missing: boolean;
  stale: boolean;
  binding: ValidationBinding;
  production_ready: boolean;
  output_quality_authorized: boolean;
  workflow_transition_authorized: boolean;
  upload_authorized: boolean;
  publication_authorized: boolean;
  started_at: string;
  completed_at: string;
  notices: string[];
  warnings: string[];
  limitations: string[];
};

export type ValidationReportCard = {
  report_card_id: string;
  report_document_id: string;
  source_module_id: string;
  report_type: string;
  report_status: string;
  schema_id: string;
  schema_version: string;
  report_format: string;
  generated_at: string;
  content_digest: string;
  expected_digest_match: boolean;
  schema_supported: boolean;
  historical: boolean;
  stale: boolean;
  malformed: boolean;
  truncated: boolean;
  warning_count: number;
  limitation_count: number;
  finding_count: number;
  validation_run_ids: string[];
  artifact_ids: string[];
  artifact_digests: string[];
  lineage_producer_module_id: string;
  lineage_read_run_id: string;
  derived_title: string;
  derived_status_label: string;
  bounded_summary: string;
  severity_counts: Record<string, number>;
  incomplete: boolean;
  integrity_verified: boolean;
  body_stored: boolean;
};

export type ValidationReportFinding = {
  finding_id: string;
  report_document_id: string;
  producer_module_id: string;
  authority_domain: string;
  finding_type: string;
  severity: string;
  title: string;
  bounded_summary: string;
  source_status: string;
  source_decision: string;
  occurred_at: string;
  current: boolean;
  stale: boolean;
  requires_human_interpretation: boolean;
  derived_severity_label: string;
  derived_title: string;
};

export type ValidationEvidenceRef = {
  evidence_ref_id: string;
  origin: string;
  validation_run_id: string;
  check_run_id: string;
  report_document_id: string;
  validator_id: string;
  source_type: string;
  artifact_id: string;
  artifact_digest: string;
  evidence_digest: string;
  bounded_summary: string;
  reliability: string;
  confidence: number | null;
  supports_pass: boolean;
  supports_failure: boolean;
  available: boolean;
  stale: boolean;
  verifiable: boolean;
  derived_availability_label: string;
};

export type ValidationConflictParticipant = {
  participant_id: string;
  source_module_id: string;
  record_kind: string;
  record_id: string;
  validator_id: string;
  validator_version: string;
  reported_value: string;
  reported_at: string;
};

export type ValidationConflict = {
  conflict_id: string;
  conflict_kind: string;
  subject_kind: string;
  subject_id: string;
  bounded_summary: string;
  participants: ValidationConflictParticipant[];
  distinct_values: string[];
  resolved: boolean;
  winner_selected: boolean;
  requires_human_interpretation: boolean;
};

// ---------------------------------------------------------------------------
// Safe readers. The API is trusted for shape but never assumed complete.
// ---------------------------------------------------------------------------
export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value ? value : fallback;
}

export function flag(value: unknown): boolean {
  return value === true;
}

export function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

/** Normalise an unknown state into the fixed vocabulary, defaulting to MISSING. */
export function asMatrixState(value: unknown): MatrixState {
  const candidate = text(value);
  return (MATRIX_STATES as readonly string[]).includes(candidate)
    ? (candidate as MatrixState)
    : "MISSING";
}

// ---------------------------------------------------------------------------
// Presentation vocabulary
// ---------------------------------------------------------------------------
const STATE_LABELS: Record<MatrixState, string> = {
  PASS: "Passed",
  FAIL: "Failed",
  BLOCKED: "Blocked",
  SKIPPED: "Skipped",
  NOT_RUN: "Not run",
  STALE: "Stale",
  MISSING: "Missing evidence",
};

const STATE_GLYPHS: Record<MatrixState, string> = {
  PASS: "✓",
  FAIL: "✕",
  BLOCKED: "⊘",
  SKIPPED: "–",
  NOT_RUN: "○",
  STALE: "⟳",
  MISSING: "?",
};

const STATE_TONES: Record<MatrixState, string> = {
  PASS: "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-100",
  FAIL: "border-rose-300/30 bg-rose-300/[0.06] text-rose-100",
  BLOCKED: "border-orange-300/30 bg-orange-300/[0.06] text-orange-100",
  SKIPPED: "border-white/10 bg-white/[0.02] text-white/60",
  NOT_RUN: "border-white/10 bg-white/[0.02] text-white/70",
  STALE: "border-amber-300/30 bg-amber-300/[0.06] text-amber-100",
  MISSING: "border-sky-300/30 bg-sky-300/[0.06] text-sky-100",
};

export function stateLabel(state: MatrixState): string {
  return STATE_LABELS[state];
}

export function stateGlyph(state: MatrixState): string {
  return STATE_GLYPHS[state];
}

export function stateTone(state: MatrixState): string {
  return STATE_TONES[state];
}

/** True only for a genuine owner-recorded pass. Nothing else is success. */
export function isSuccessState(state: MatrixState): boolean {
  return state === "PASS";
}

export function isVerdictState(state: MatrixState): boolean {
  return VERDICT_STATES.includes(state);
}

/** Human-readable label for a staleness dimension, never invented. */
const DIMENSION_LABELS: Record<string, string> = {
  project_id: "Project identity",
  workflow_run_id: "Workflow run",
  stage_instance_id: "Workflow stage",
  target_id: "Validation target",
  workflow_revision: "Workflow revision",
  artifact_digest: "Artifact digest",
  validator_version: "Validator version",
  validation_request_id: "Request identity",
};

export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABELS[dimension] ?? dimension.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------
export function parseBinding(value: unknown): ValidationBinding {
  const row = asRecord(value);
  return {
    binding_id: text(row.binding_id),
    project_id: text(row.project_id),
    workflow_run_id: text(row.workflow_run_id),
    stage_instance_id: text(row.stage_instance_id),
    target_type: text(row.target_type, "unknown"),
    target_id: text(row.target_id),
    target_digest: text(row.target_digest),
    workflow_revision: count(row.workflow_revision),
    artifact_digest: text(row.artifact_digest),
    validator_version: text(row.validator_version),
    validation_request_id: text(row.validation_request_id),
    binding_digest: text(row.binding_digest),
    bound: flag(row.bound),
    reuse_valid: flag(row.reuse_valid),
    invalidated_dimensions: asList(row.invalidated_dimensions).map((item) => text(item)),
    derived_summary: text(row.derived_summary),
  };
}

export function parseMatrixCell(value: unknown): ValidationMatrixCell {
  const row = asRecord(value);
  const derived = asMatrixState(row.derived_state);
  return {
    cell_id: text(row.cell_id),
    owner_module_id: text(row.owner_module_id, "validator_runner"),
    owner_fact: flag(row.owner_fact),
    owner_status: text(row.owner_status, "unknown"),
    check_run_id: text(row.check_run_id),
    validation_run_id: text(row.validation_run_id),
    plan_check_id: text(row.plan_check_id),
    validator_id: text(row.validator_id),
    validator_version: text(row.validator_version),
    category: text(row.category, "unknown"),
    required: flag(row.required),
    attempt_number: count(row.attempt_number),
    result_id: text(row.result_id),
    result_status: text(row.result_status),
    result_digest: text(row.result_digest),
    input_digest: text(row.input_digest),
    environment_digest: text(row.environment_digest),
    evidence_ids: asList(row.evidence_ids).map((item) => text(item)),
    started_at: text(row.started_at),
    completed_at: text(row.completed_at),
    duration_seconds:
      typeof row.duration_seconds === "number" ? row.duration_seconds : null,
    exit_code: typeof row.exit_code === "number" ? row.exit_code : null,
    failed_assertions: asList(row.failed_assertions).map((item) => text(item)),
    unavailable_assertions: asList(row.unavailable_assertions).map((item) => text(item)),
    failure_categories: asList(row.failure_categories).map((item) => text(item)),
    bounded_diagnostics: asList(row.bounded_diagnostics).map((item) => text(item)),
    owner_warnings: asList(row.owner_warnings).map((item) => text(item)),
    workflow_revision: count(row.workflow_revision),
    derived_state: derived,
    owner_reported_state: asMatrixState(row.owner_reported_state),
    derived_state_reason: text(row.derived_state_reason),
    derived_title: text(row.derived_title),
    // A verdict is only ever believed when the backend says so *and* the state
    // is verdict-bearing. The UI never upgrades a state on its own.
    verdict_available: flag(row.verdict_available) && isVerdictState(derived),
    evidence_present: flag(row.evidence_present),
    stale: flag(row.stale),
    stale_reasons: asList(row.stale_reasons).map((item) => text(item)),
    binding_digest: text(row.binding_digest),
  };
}

export function parseMatrix(value: unknown): ValidationMatrix {
  const row = asRecord(value);
  const counts = asRecord(row.state_counts);
  return {
    matrix_id: text(row.matrix_id),
    project_id: text(row.project_id),
    validation_run_id: text(row.validation_run_id),
    binding: parseBinding(row.binding),
    cells: asList(row.cells).map(parseMatrixCell),
    state_counts: Object.fromEntries(
      MATRIX_STATES.map((state) => [state, count(counts[state])]),
    ),
    total_cells: count(row.total_cells),
    truncated: flag(row.truncated),
    required_verdict_complete: flag(row.required_verdict_complete),
    evidence_complete: flag(row.evidence_complete),
    any_conflict: flag(row.any_conflict),
    notices: asList(row.notices).map((item) => text(item)),
    warnings: asList(row.warnings).map((item) => text(item)),
    limitations: asList(row.limitations).map((item) => text(item)),
  };
}

export function parseSummary(value: unknown): ValidationSummary {
  const row = asRecord(value);
  const counts = asRecord(row.state_counts);
  return {
    summary_id: text(row.summary_id),
    validation_run_id: text(row.validation_run_id),
    run_status: text(row.run_status, "unavailable"),
    suite_decision: text(row.suite_decision, "unavailable"),
    suite_decision_id: text(row.suite_decision_id),
    owner_decision_summary: text(row.owner_decision_summary),
    required_checks_complete: flag(row.required_checks_complete),
    required_checks_passed: flag(row.required_checks_passed),
    technical_validation_passed: flag(row.technical_validation_passed),
    human_review_required: flag(row.human_review_required),
    derived_status_title: text(row.derived_status_title),
    state_counts: Object.fromEntries(
      MATRIX_STATES.map((state) => [state, count(counts[state])]),
    ),
    validation_evidence_available: flag(row.validation_evidence_available),
    // Absent data must read as missing evidence, so this defaults to true.
    evidence_missing: row.evidence_missing === false ? false : true,
    stale: flag(row.stale),
    binding: parseBinding(row.binding),
    // Authorisation flags are never inferred; anything but an explicit false is
    // treated as not authorised.
    production_ready: false,
    output_quality_authorized: false,
    workflow_transition_authorized: false,
    upload_authorized: false,
    publication_authorized: false,
    started_at: text(row.started_at),
    completed_at: text(row.completed_at),
    notices: asList(row.notices).map((item) => text(item)),
    warnings: asList(row.warnings).map((item) => text(item)),
    limitations: asList(row.limitations).map((item) => text(item)),
  };
}

export function parseReportCard(value: unknown): ValidationReportCard {
  const row = asRecord(value);
  const severities = asRecord(row.severity_counts);
  return {
    report_card_id: text(row.report_card_id),
    report_document_id: text(row.report_document_id),
    source_module_id: text(row.source_module_id, "unknown"),
    report_type: text(row.report_type, "unknown"),
    report_status: text(row.report_status, "unknown"),
    schema_id: text(row.schema_id),
    schema_version: text(row.schema_version),
    report_format: text(row.report_format, "unknown"),
    generated_at: text(row.generated_at),
    content_digest: text(row.content_digest),
    expected_digest_match: row.expected_digest_match === false ? false : true,
    schema_supported: row.schema_supported === false ? false : true,
    historical: flag(row.historical),
    stale: flag(row.stale),
    malformed: flag(row.malformed),
    truncated: flag(row.truncated),
    warning_count: count(row.warning_count),
    limitation_count: count(row.limitation_count),
    finding_count: count(row.finding_count),
    validation_run_ids: asList(row.validation_run_ids).map((item) => text(item)),
    artifact_ids: asList(row.artifact_ids).map((item) => text(item)),
    artifact_digests: asList(row.artifact_digests).map((item) => text(item)),
    lineage_producer_module_id: text(row.lineage_producer_module_id),
    lineage_read_run_id: text(row.lineage_read_run_id),
    derived_title: text(row.derived_title),
    derived_status_label: text(row.derived_status_label, "Unknown status"),
    bounded_summary: text(row.bounded_summary),
    severity_counts: Object.fromEntries(
      Object.entries(severities).map(([key, item]) => [key, count(item)]),
    ),
    incomplete: flag(row.incomplete),
    // Integrity is only ever believed when a digest exists and matched.
    integrity_verified:
      flag(row.integrity_verified) &&
      Boolean(text(row.content_digest)) &&
      row.expected_digest_match !== false,
    body_stored: false,
  };
}

export function parseFinding(value: unknown): ValidationReportFinding {
  const row = asRecord(value);
  return {
    finding_id: text(row.finding_id),
    report_document_id: text(row.report_document_id),
    producer_module_id: text(row.producer_module_id, "unknown"),
    authority_domain: text(row.authority_domain, "unknown"),
    finding_type: text(row.finding_type, "unknown"),
    severity: text(row.severity, "unknown"),
    title: text(row.title),
    bounded_summary: text(row.bounded_summary),
    source_status: text(row.source_status),
    source_decision: text(row.source_decision),
    occurred_at: text(row.occurred_at),
    current: flag(row.current),
    stale: flag(row.stale),
    requires_human_interpretation: flag(row.requires_human_interpretation),
    derived_severity_label: text(row.derived_severity_label, "Unclassified finding"),
    derived_title: text(row.derived_title),
  };
}

export function parseEvidence(value: unknown): ValidationEvidenceRef {
  const row = asRecord(value);
  const available = row.available === false ? false : true;
  return {
    evidence_ref_id: text(row.evidence_ref_id),
    origin: text(row.origin, "validator_runner"),
    validation_run_id: text(row.validation_run_id),
    check_run_id: text(row.check_run_id),
    report_document_id: text(row.report_document_id),
    validator_id: text(row.validator_id),
    source_type: text(row.source_type, "unknown"),
    artifact_id: text(row.artifact_id),
    artifact_digest: text(row.artifact_digest),
    evidence_digest: text(row.evidence_digest),
    bounded_summary: text(row.bounded_summary),
    reliability: text(row.reliability, "unknown"),
    confidence: typeof row.confidence === "number" ? row.confidence : null,
    // Unavailable evidence can never be shown as supporting a pass.
    supports_pass: flag(row.supports_pass) && available,
    supports_failure: flag(row.supports_failure),
    available,
    stale: flag(row.stale),
    verifiable: flag(row.verifiable),
    derived_availability_label: text(
      row.derived_availability_label,
      available ? "Available" : "Unavailable evidence reference",
    ),
  };
}

export function parseConflict(value: unknown): ValidationConflict {
  const row = asRecord(value);
  return {
    conflict_id: text(row.conflict_id),
    conflict_kind: text(row.conflict_kind, "unknown"),
    subject_kind: text(row.subject_kind, "unknown"),
    subject_id: text(row.subject_id),
    bounded_summary: text(row.bounded_summary),
    participants: asList(row.participants).map((item) => {
      const participant = asRecord(item);
      return {
        participant_id: text(participant.participant_id),
        source_module_id: text(participant.source_module_id, "unknown"),
        record_kind: text(participant.record_kind, "unknown"),
        record_id: text(participant.record_id),
        validator_id: text(participant.validator_id),
        validator_version: text(participant.validator_version),
        reported_value: text(participant.reported_value),
        reported_at: text(participant.reported_at),
      };
    }),
    distinct_values: asList(row.distinct_values).map((item) => text(item)),
    // A conflict is never presented as resolved and never has a winner.
    resolved: false,
    winner_selected: false,
    requires_human_interpretation: true,
  };
}

// ---------------------------------------------------------------------------
// Derived views
// ---------------------------------------------------------------------------
export type MatrixStateRow = {
  state: MatrixState;
  label: string;
  glyph: string;
  tone: string;
  total: number;
  verdictBearing: boolean;
};

/** Always returns all seven states in fixed order, so none can be hidden. */
export function buildStateRows(counts: Record<string, number>): MatrixStateRow[] {
  return MATRIX_STATES.map((state) => ({
    state,
    label: stateLabel(state),
    glyph: stateGlyph(state),
    tone: stateTone(state),
    total: count(counts[state]),
    verdictBearing: isVerdictState(state),
  }));
}

/** Deterministic ordering that never promotes a state above an owner fact. */
export function orderCells(cells: ValidationMatrixCell[]): ValidationMatrixCell[] {
  return [...cells].sort(
    (left, right) =>
      left.validator_id.localeCompare(right.validator_id) ||
      left.plan_check_id.localeCompare(right.plan_check_id) ||
      left.attempt_number - right.attempt_number ||
      left.cell_id.localeCompare(right.cell_id),
  );
}

export function orderReportCards(cards: ValidationReportCard[]): ValidationReportCard[] {
  return [...cards].sort(
    (left, right) =>
      left.source_module_id.localeCompare(right.source_module_id) ||
      left.report_type.localeCompare(right.report_type) ||
      left.report_document_id.localeCompare(right.report_document_id),
  );
}

export function orderConflicts(conflicts: ValidationConflict[]): ValidationConflict[] {
  return [...conflicts].sort(
    (left, right) =>
      left.conflict_kind.localeCompare(right.conflict_kind) ||
      left.conflict_id.localeCompare(right.conflict_id),
  );
}

/** Cells with no verdict, which must never be presented as passing. */
export function cellsWithoutVerdict(cells: ValidationMatrixCell[]): ValidationMatrixCell[] {
  return cells.filter((cell) => !cell.verdict_available);
}

export function staleDimensionLabels(binding: ValidationBinding): string[] {
  return binding.invalidated_dimensions.map(dimensionLabel);
}

export function shortDigest(digest: string): string {
  return digest ? `${digest.slice(0, 12)}…` : "Not available";
}

export function reportProblemLabels(card: ValidationReportCard): string[] {
  const problems: string[] = [];
  if (card.malformed) problems.push("Malformed");
  if (!card.schema_supported) problems.push("Unsupported schema");
  if (!card.expected_digest_match) problems.push("Digest mismatch");
  if (card.stale) problems.push("Stale");
  if (card.truncated) problems.push("Truncated");
  return problems;
}

/**
 * The single headline. It never says "ready", "approved" or "safe", and it
 * reports missing evidence and staleness ahead of any owner pass.
 */
export function headlineFor(summary: ValidationSummary, conflictCount: number): string {
  if (!summary.binding.bound) return "No validation run exists for this project yet.";
  if (summary.evidence_missing) return "Validation evidence is incomplete.";
  if (summary.stale) return "Validation exists but is stale and cannot be reused.";
  if (conflictCount > 0) return "Validation evidence contains unresolved conflicts.";
  return `Validator Runner suite decision: ${summary.suite_decision}.`;
}
