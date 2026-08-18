"""BOBA Validation + Reports V1 - truthful validation and report projection.

This module is a **projection and presentation boundary**. It is not a
validator, not a report store, and not a decision authority. It runs nothing,
decides nothing and stores no authoritative verdict of its own.

Canonical ownership is unchanged:

    Validator Runner    -> owns validation execution, check verdicts, evidence
                           records, suite decisions and validator identity
    Report Reader       -> owns safe report reading, parsing, findings,
                           contradictions and report bodies
    Artifact Inspector  -> owns artifact identity, digests and lineage
    Workflow Controller -> owns workflow state, stage identity and revision
    Safety Gate         -> owns safety authorisation
    Final Decision Bus  -> owns final action authorisation
    Integration Layer   -> owns typed cross-module routing

What this module adds, and only this:

1. A deterministic **validation matrix** in which every cell keeps the owner's
   exact status verbatim alongside a derived presentation state drawn from a
   fixed seven-value vocabulary. The owner vocabulary is larger than the
   presentation vocabulary, so the derived state is always accompanied by the
   untouched owner fact and a rationale naming it. Nothing is collapsed away.
2. A **report projection** built from Report Reader documents. Report bodies
   stay owned by the Report Reader; this module stores references, digests and
   bounded summaries only.
3. Explicit **conflict identification** across multiple validators and reports.
   Contradictory evidence is preserved side by side. Nothing is averaged, no
   result is selected as best, no root cause is inferred and no repair is
   proposed.
4. **Staleness binding** across the eight dimensions that make a validation
   verdict reusable: project, workflow run, stage, target, revision, artifact
   digest, validator version and request identity.

Truthfulness rules enforced in code, not merely documented:

* Missing evidence is reported as ``MISSING``. It never becomes a pass.
* Only ``PASS`` and ``FAIL`` carry a verdict. Everything else records that no
  verdict exists, via ``verdict_available``.
* Passing validators never imply production readiness, quality acceptance,
  workflow advancement, upload or publication. Those flags are hard ``False``.
* A projection is never an approval, a Safety decision or an execution receipt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import Field, model_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.report_reader import sanitize_report_export
from olympus.boba.review_ui import (
    _PRIVATE_PATH,
    _SENSITIVE_KEY,
    _active_workflow_run,
    _as_mapping,
    _digest,
    _safe_id,
    _safe_payload,
    _safe_text,
    _stable_id,
)
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.integration import BobaIntegration


# ----------------------------------------------------------------------
# Fixed bounds. Every projection is bounded; nothing grows with input size.
# ----------------------------------------------------------------------
MAX_MATRIX_CELLS = 200
MAX_REPORT_CARDS = 64
MAX_FINDING_ROWS = 100
MAX_SECTION_ROWS = 64
MAX_EVIDENCE_ROWS = 100
MAX_CONFLICT_ROWS = 50
MAX_CONFLICT_PARTICIPANTS = 8
MAX_EVENTS = 100
MAX_WARNINGS = 24
MAX_DIAGNOSTIC_ROWS = 12
MAX_SUMMARY_LENGTH = 900

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_URL = re.compile(r"(?i)\b(?:https?|ftp|file)://")
_UNC_PATH = re.compile(r"\\\\[^\s\\]+")
_TRAVERSAL = re.compile(r"\.\./|\.\.\\")
_WINDOWS_ABSOLUTE = re.compile(r"(?i)^[a-z]:[\\/]")
_SHELL_TOKEN = re.compile(r"(?:\|\||&&|[|><;`]|\$\(|\r|\n)")
_COMMAND_EXECUTABLE = re.compile(
    r"(?i)(?:^|[\s\"'])(?:ffmpeg|ffprobe|git|python3?|pip3?|npm|npx|yarn|pnpm|node|"
    r"bash|sh|zsh|powershell|pwsh|cmd|docker|apt|apt-get|brew|curl|wget|make|"
    r"systemctl|kill|pkill|rm|mv|cp|chmod|chown|sudo|ssh|scp|rsync)\b"
)
_RAW_MEDIA = re.compile(r"(?i)\.(?:mp4|mov|mkv|webm|avi|m4a|mp3|wav|flac|aac|jpg|jpeg|png)\b")


# ----------------------------------------------------------------------
# Truthfulness notices. These are presentation strings, never authority.
# ----------------------------------------------------------------------
PROJECTION_ONLY_NOTICE = (
    "This is a read-only projection of existing owner records. It runs no "
    "validator, reads no new report and decides nothing."
)
NOT_PRODUCTION_READY_NOTICE = (
    "Passing technical validation does not mean the output is production ready, "
    "quality accepted, rights cleared or approved for upload or publication."
)
MISSING_EVIDENCE_NOTICE = (
    "Missing evidence is reported as MISSING. It is never treated as a pass."
)
CONFLICT_NOTICE = (
    "Contradictory results are preserved separately. No result is selected as "
    "best, averaged or merged, and no root cause or repair is inferred."
)
STALE_NOTICE = (
    "The bound project, workflow run, stage, target, revision, artifact digest, "
    "validator version or request identity changed. Earlier verdicts cannot be "
    "reused and are shown as STALE."
)
REPORT_BODY_NOTICE = (
    "Report bodies remain owned by the Report Reader. This projection stores "
    "references, digests and bounded summaries only."
)


# ----------------------------------------------------------------------
# Vocabularies
# ----------------------------------------------------------------------
ValidationMatrixState = Literal[
    "PASS",
    "FAIL",
    "BLOCKED",
    "SKIPPED",
    "NOT_RUN",
    "STALE",
    "MISSING",
]

MATRIX_STATES: tuple[ValidationMatrixState, ...] = (
    "PASS",
    "FAIL",
    "BLOCKED",
    "SKIPPED",
    "NOT_RUN",
    "STALE",
    "MISSING",
)

# Only these two presentation states carry an actual validation verdict.
VERDICT_STATES: frozenset[str] = frozenset({"PASS", "FAIL"})

ValidationProjectionSourceV1 = Literal[
    "validator_runner",
    "report_reader",
    "artifact_inspector",
    "workflow_controller",
    "safety_gate",
    "final_decision_bus",
]

ValidationConflictKindV1 = Literal[
    "check_status_conflict",
    "result_status_conflict",
    "validator_version_conflict",
    "input_digest_conflict",
    "suite_decision_conflict",
    "report_status_conflict",
    "report_digest_conflict",
    "reported_contradiction",
    "unknown",
]

ValidationReportsEventTypeV1 = Literal[
    "projection_requested",
    "matrix_projected",
    "reports_projected",
    "evidence_projected",
    "conflict_detected",
    "evidence_missing",
    "stale_binding_detected",
    "report_malformed",
    "digest_mismatch",
    "projection_empty",
    "metadata_reset",
    "unknown",
]

# The Validator Runner's own check vocabulary has fourteen values. The matrix
# vocabulary has seven. Mapping is therefore lossy *by itself*, which is exactly
# why every cell also carries ``owner_status`` verbatim and a rationale naming
# it. No owner fact is discarded; only the presentation is condensed.
_OWNER_CHECK_STATE: dict[str, ValidationMatrixState] = {
    "passed": "PASS",
    "failed": "FAIL",
    "blocked": "BLOCKED",
    "dependency_blocked": "BLOCKED",
    "errored": "BLOCKED",
    "timed_out": "BLOCKED",
    "cancelled": "BLOCKED",
    "skipped_not_required": "SKIPPED",
    "pending": "NOT_RUN",
    "ready": "NOT_RUN",
    "running": "NOT_RUN",
    "superseded": "STALE",
    "unavailable": "MISSING",
    "unknown": "MISSING",
}

_OWNER_STATE_RATIONALE: dict[str, str] = {
    "passed": "The Validator Runner recorded a passing verdict for this check.",
    "failed": "The Validator Runner recorded a failing verdict for this check.",
    "blocked": "The Validator Runner reported the check blocked; no verdict exists.",
    "dependency_blocked": (
        "A prerequisite check did not complete, so this check was never run."
    ),
    "errored": "The check errored before producing a verdict.",
    "timed_out": "The check exceeded its timeout before producing a verdict.",
    "cancelled": "The check was cancelled before producing a verdict.",
    "skipped_not_required": "The check was not required and was deliberately skipped.",
    "pending": "The check is registered but has not started.",
    "ready": "The check is ready to run but has not started.",
    "running": "The check is still running and has produced no verdict.",
    "superseded": "A newer check run replaced this one, so its verdict is stale.",
    "unavailable": "The validator was unavailable, so no evidence was produced.",
    "unknown": "The Validator Runner reported an unknown status; no verdict exists.",
}

_STALE_DIMENSIONS: tuple[str, ...] = (
    "project_id",
    "workflow_run_id",
    "stage_instance_id",
    "target_id",
    "workflow_revision",
    "artifact_digest",
    "validator_version",
    "validation_request_id",
)

# Wall-clock metadata that must never contribute to a content digest. A
# projection rebuilt from unchanged canonical evidence has to produce an
# identical digest, otherwise the digest cannot be used to tell "nothing
# changed" apart from "something changed". These keys stay in the payload as
# metadata; they are only excluded from the digested content.
_VOLATILE_DIGEST_KEYS: frozenset[str] = frozenset({"created_at"})


def owner_check_state_mapping() -> dict[str, str]:
    """Return the fixed owner-status to matrix-state mapping."""
    return dict(_OWNER_CHECK_STATE)


def derive_matrix_state(owner_status: str) -> ValidationMatrixState:
    """Map an exact owner check status onto the fixed matrix vocabulary.

    An unrecognised owner status becomes ``MISSING`` rather than a pass. A new
    owner status must never silently read as success.
    """
    return _OWNER_CHECK_STATE.get(owner_status.strip().casefold(), "MISSING")


def matrix_state_reason(owner_status: str) -> str:
    normalized = owner_status.strip().casefold()
    known = _OWNER_STATE_RATIONALE.get(normalized)
    if known:
        return known
    return (
        f"The Validator Runner reported the unrecognised status "
        f"'{_safe_text(normalized, 120)}'. No verdict is claimed."
    )


def verdict_available(state: str) -> bool:
    """True only when the state genuinely carries a validation verdict."""
    return state in VERDICT_STATES


# ----------------------------------------------------------------------
# Security helpers. Reuses the owners' redaction helpers rather than
# reimplementing them, and refuses unsafe material outright.
# ----------------------------------------------------------------------
def _unsafe_reason(value: str) -> str | None:
    """Name the unsafe material in raw text, or return None when it is clean."""
    if _SENSITIVE_KEY.search(value):
        return "a credential-like token"
    if _SHELL_TOKEN.search(value) or _COMMAND_EXECUTABLE.search(value):
        return "executable command text"
    if _URL.search(value):
        return "an external URL"
    if _PRIVATE_PATH.search(value) or _UNC_PATH.search(value):
        return "a private filesystem path"
    if _TRAVERSAL.search(value):
        return "a path traversal sequence"
    return None


def validate_projection_digest(value: object, *, label: str) -> str:
    """Accept an empty digest or an exact lowercase SHA-256, nothing else."""
    text = "" if value is None else str(value).strip().casefold()
    if not text:
        return ""
    if not _SHA256.fullmatch(text):
        raise ValidationError(f"A BOBA validation {label} must be a lowercase SHA-256 digest.")
    return text


def validate_projection_reference(value: object, *, label: str) -> str:
    """Bound a project-scoped reference, refusing anything outside the project.

    Absolute paths, Windows drive paths, UNC paths, traversal, external URLs and
    raw media references are all refused rather than sanitised, so an unsafe
    reference can never survive as a quietly rewritten string.
    """
    text = "" if value is None else str(value).strip().replace("\\", "/")
    if not text:
        return ""
    if _URL.search(text):
        raise ValidationError(f"External URLs are not accepted as a BOBA validation {label}.")
    if text.startswith("//") or _UNC_PATH.search(text):
        raise ValidationError(f"UNC references are not accepted as a BOBA validation {label}.")
    if text.startswith("/") or _WINDOWS_ABSOLUTE.match(text):
        raise ValidationError(
            f"Absolute references are not accepted as a BOBA validation {label}."
        )
    if _TRAVERSAL.search(text) or any(part in {"", ".", ".."} for part in text.split("/")):
        raise ValidationError(f"Traversal is not accepted as a BOBA validation {label}.")
    if _RAW_MEDIA.search(text):
        raise ValidationError(
            f"Raw media references are not accepted as a BOBA validation {label}."
        )
    if _SENSITIVE_KEY.search(text):
        raise ValidationError(f"A BOBA validation {label} cannot carry credential-like text.")
    return _safe_text(text, 500)


def bounded_projection_text(value: object, maximum: int = MAX_SUMMARY_LENGTH) -> str:
    """Bound owner-supplied prose, refusing unsafe material before sanitising.

    Validation happens on the raw value on purpose: ``_safe_text`` rewrites
    private paths, and in doing so turns ``https://`` into ``http[...]/``. A
    check performed after sanitisation would therefore accept the very material
    this refuses.
    """
    raw = "" if value is None else str(value)
    if not raw.strip():
        return ""
    if _unsafe_reason(raw) is not None:
        # Owner prose is projected, not trusted. Unsafe content is replaced with a
        # truthful placeholder instead of raising, because refusing here would
        # make an owner record unreadable rather than safe.
        return "[redacted: unsafe content in owner record]"
    return _safe_text(raw, maximum)


def _bounded_rows(value: object, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [_as_mapping(row) for row in list(value)[:limit] if isinstance(row, Mapping)]


def _bounded_ids(value: object, limit: int = 64) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    seen: list[str] = []
    for item in list(value)[: limit * 2]:
        text = _safe_text(item, 180)
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _bounded_warnings(value: object) -> list[str]:
    rows = value if isinstance(value, Sequence) and not isinstance(value, str) else []
    out: list[str] = []
    for item in list(rows)[: MAX_WARNINGS * 2]:
        text = bounded_projection_text(item, 300)
        if text and text not in out:
            out.append(text)
        if len(out) >= MAX_WARNINGS:
            break
    return out


def sanitize_validation_reports_export(value: Any) -> Any:
    """Reuse the Report Reader export sanitiser for this module's export."""
    return sanitize_report_export(value)


def projection_content_for_digest(value: Any) -> Any:
    """Return ``value`` with wall-clock metadata removed, recursively.

    The projection digest has to identify *content*. Generation timestamps are
    honest metadata but they are not content: including them made every rebuild
    of an unchanged projection report a different digest, which silently
    destroyed the determinism this module promises. Timestamps that are owner
    facts (``started_at``, ``completed_at``, ``generated_at``) are deliberately
    kept, because those genuinely describe the evidence being projected.
    """
    if isinstance(value, Mapping):
        return {
            key: projection_content_for_digest(item)
            for key, item in value.items()
            if key not in _VOLATILE_DIGEST_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [projection_content_for_digest(item) for item in value]
    return value


def projection_content_digest(payload: Mapping[str, Any]) -> str:
    """Digest a projection payload over its content alone."""
    content = projection_content_for_digest(dict(payload))
    content.pop("projection_digest", None)
    return _digest(_safe_payload(content))


# ----------------------------------------------------------------------
# Contracts
#
# Every contract that carries an owner value keeps ``owner_fact`` separate from
# the ``derived_*`` presentation fields, so a rendered label can never be
# mistaken for something a canonical owner actually asserted.
# ----------------------------------------------------------------------
class BobaValidationReportsRegistrySnapshotV1(BobaContract):
    registry_snapshot_id: str = Field(min_length=1, max_length=180)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    matrix_states: list[str] = Field(default_factory=list, max_length=16)
    owner_check_statuses: list[str] = Field(default_factory=list, max_length=32)
    owner_status_to_matrix_state: dict[str, str] = Field(default_factory=dict, max_length=32)
    verdict_bearing_states: list[str] = Field(default_factory=list, max_length=8)
    staleness_dimensions: list[str] = Field(default_factory=list, max_length=16)
    projection_source_module_ids: list[str] = Field(default_factory=list, max_length=16)
    conflict_kinds: list[str] = Field(default_factory=list, max_length=16)
    registry_digest: str = Field(default="", max_length=64)
    projection_only: Literal[True] = True
    executes_validation: Literal[False] = False
    owns_validation_verdicts: Literal[False] = False
    owns_report_bodies: Literal[False] = False


class BobaValidationBindingV1(BobaContract):
    """The eight dimensions that make a validation verdict reusable."""

    binding_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    workflow_run_id: str = Field(default="", max_length=180)
    stage_instance_id: str = Field(default="", max_length=180)
    target_type: str = Field(default="unknown", max_length=80)
    target_id: str = Field(default="", max_length=180)
    target_digest: str = Field(default="", max_length=64)
    workflow_revision: int = Field(default=0, ge=0)
    artifact_digest: str = Field(default="", max_length=64)
    validator_id: str = Field(default="", max_length=180)
    validator_version: str = Field(default="", max_length=80)
    validation_request_id: str = Field(default="", max_length=180)
    binding_digest: str = Field(default="", max_length=64)
    bound: bool = False
    reuse_valid: bool = False
    invalidated_dimensions: list[str] = Field(default_factory=list, max_length=16)
    owner_fact: Literal[True] = True
    derived_summary: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)


class BobaValidationMatrixCellV1(BobaContract):
    """One validation check: owner facts first, derived presentation second."""

    cell_id: str = Field(min_length=1, max_length=180)

    # --- Owner facts, transcribed verbatim from the Validator Runner ---
    owner_module_id: Literal["validator_runner"] = "validator_runner"
    owner_fact: Literal[True] = True
    owner_status: str = Field(default="unknown", max_length=80)
    check_run_id: str = Field(default="", max_length=180)
    validation_run_id: str = Field(default="", max_length=180)
    plan_check_id: str = Field(default="", max_length=180)
    validator_id: str = Field(default="", max_length=180)
    validator_version: str = Field(default="", max_length=80)
    category: str = Field(default="unknown", max_length=80)
    required: bool = True
    attempt_number: int = Field(default=1, ge=1, le=16)
    result_id: str = Field(default="", max_length=180)
    result_status: str = Field(default="", max_length=80)
    result_digest: str = Field(default="", max_length=64)
    input_digest: str = Field(default="", max_length=64)
    environment_digest: str = Field(default="", max_length=64)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    started_at: str = Field(default="", max_length=80)
    completed_at: str = Field(default="", max_length=80)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    exit_code: int | None = None
    blocks_suite_pass: bool = True
    protected_state_unchanged: bool = True
    failed_assertions: list[str] = Field(default_factory=list, max_length=32)
    unavailable_assertions: list[str] = Field(default_factory=list, max_length=32)
    failure_categories: list[str] = Field(default_factory=list, max_length=16)
    bounded_diagnostics: list[str] = Field(default_factory=list, max_length=MAX_DIAGNOSTIC_ROWS)
    owner_warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    workflow_revision: int = Field(default=0, ge=0)

    # --- Derived presentation, owned by this module and clearly labelled ---
    derived_state: ValidationMatrixState = "MISSING"
    owner_reported_state: ValidationMatrixState = "MISSING"
    derived_state_reason: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)
    derived_title: str = Field(default="", max_length=240)
    verdict_available: bool = False
    evidence_present: bool = False
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list, max_length=16)
    binding_digest: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def validate_truthfulness(self) -> BobaValidationMatrixCellV1:
        """A cell may never claim a verdict it does not have."""
        if self.verdict_available and self.derived_state not in VERDICT_STATES:
            raise ValidationError(
                "A validation matrix cell cannot claim a verdict outside PASS or FAIL."
            )
        if self.derived_state in VERDICT_STATES and not self.verdict_available:
            raise ValidationError(
                "A PASS or FAIL validation matrix cell must record an available verdict."
            )
        if self.derived_state == "PASS" and not self.evidence_present:
            raise ValidationError(
                "A passing validation matrix cell requires owner evidence; missing "
                "evidence is never a pass."
            )
        if self.stale and self.derived_state != "STALE":
            raise ValidationError("A stale validation matrix cell must present as STALE.")
        return self


class BobaValidationMatrixV1(BobaContract):
    matrix_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    validation_run_id: str = Field(default="", max_length=180)
    validation_plan_id: str = Field(default="", max_length=180)
    binding: BobaValidationBindingV1
    cells: list[BobaValidationMatrixCellV1] = Field(
        default_factory=list, max_length=MAX_MATRIX_CELLS
    )
    state_counts: dict[str, int] = Field(default_factory=dict, max_length=16)
    total_cells: int = Field(default=0, ge=0)
    truncated: bool = False
    required_verdict_complete: bool = False
    evidence_complete: bool = False
    any_conflict: bool = False
    matrix_digest: str = Field(default="", max_length=64)
    projection_only: Literal[True] = True
    notices: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)

    @model_validator(mode="after")
    def validate_counts(self) -> BobaValidationMatrixV1:
        if self.required_verdict_complete and not self.evidence_complete:
            raise ValidationError(
                "A matrix cannot report complete required verdicts without complete evidence."
            )
        return self


class BobaValidationSummaryV1(BobaContract):
    """Suite-level truth. Never a readiness, quality or workflow claim."""

    summary_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso, max_length=80)

    # --- Owner facts ---
    owner_module_id: Literal["validator_runner"] = "validator_runner"
    owner_fact: Literal[True] = True
    validation_run_id: str = Field(default="", max_length=180)
    validation_plan_id: str = Field(default="", max_length=180)
    run_status: str = Field(default="unavailable", max_length=80)
    suite_decision_id: str = Field(default="", max_length=180)
    suite_decision: str = Field(default="unavailable", max_length=80)
    owner_decision_summary: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)
    required_checks_complete: bool = False
    required_checks_passed: bool = False
    optional_checks_complete: bool = False
    acceptance_criteria_met: bool = False
    rejection_criteria_triggered: bool = False
    owner_evidence_complete: bool = False
    target_digest_unchanged: bool = False
    environment_digest_unchanged: bool = False
    project_snapshot_current: bool = False
    technical_validation_passed: bool = False
    human_review_required: bool = False
    started_at: str = Field(default="", max_length=80)
    completed_at: str = Field(default="", max_length=80)
    workflow_revision: int = Field(default=0, ge=0)

    # --- Derived presentation ---
    derived_status_title: str = Field(default="", max_length=240)
    derived_summary: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)
    state_counts: dict[str, int] = Field(default_factory=dict, max_length=16)
    validation_evidence_available: bool = False
    evidence_missing: bool = True
    stale: bool = False
    binding: BobaValidationBindingV1

    # --- Hard truthfulness floors. These are never computed upward. ---
    production_ready: Literal[False] = False
    output_quality_authorized: Literal[False] = False
    workflow_transition_authorized: Literal[False] = False
    safety_authorized: Literal[False] = False
    upload_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    approval_granted: Literal[False] = False

    notices: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)

    @model_validator(mode="after")
    def validate_no_invented_success(self) -> BobaValidationSummaryV1:
        if self.technical_validation_passed and not self.validation_evidence_available:
            raise ValidationError(
                "Technical validation cannot be reported as passed without evidence."
            )
        if self.evidence_missing and self.required_checks_passed:
            raise ValidationError(
                "Required checks cannot be reported as passed while evidence is missing."
            )
        return self


class BobaValidationReportCardV1(BobaContract):
    """A bounded projection of one Report Reader document. Never the body."""

    report_card_id: str = Field(min_length=1, max_length=180)

    # --- Owner facts ---
    owner_module_id: Literal["report_reader"] = "report_reader"
    owner_fact: Literal[True] = True
    report_document_id: str = Field(default="", max_length=180)
    report_reference_id: str = Field(default="", max_length=180)
    source_module_id: str = Field(default="unknown", max_length=160)
    producer_record_id: str = Field(default="", max_length=180)
    report_type: str = Field(default="unknown", max_length=80)
    report_status: str = Field(default="unknown", max_length=80)
    schema_id: str = Field(default="", max_length=180)
    schema_version: str = Field(default="", max_length=80)
    report_format: str = Field(default="unknown", max_length=40)
    parser_id: str = Field(default="", max_length=120)
    generated_at: str = Field(default="", max_length=80)
    content_digest: str = Field(default="", max_length=64)
    expected_digest_match: bool = True
    project_identity_match: bool = True
    source_identity_match: bool = True
    schema_supported: bool = True
    current_project_snapshot_match: bool = False
    historical: bool = False
    stale: bool = False
    malformed: bool = False
    truncated: bool = False
    warning_count: int = Field(default=0, ge=0)
    limitation_count: int = Field(default=0, ge=0)
    finding_count: int = Field(default=0, ge=0)
    sanitized_storage_reference: str = Field(default="", max_length=500)

    # --- Linkage, by reference only ---
    validation_run_ids: list[str] = Field(default_factory=list, max_length=32)
    validator_ids: list[str] = Field(default_factory=list, max_length=32)
    artifact_ids: list[str] = Field(default_factory=list, max_length=32)
    artifact_digests: list[str] = Field(default_factory=list, max_length=32)
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=64)
    source_decision_ids: list[str] = Field(default_factory=list, max_length=32)
    section_ids: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ROWS)
    finding_ids: list[str] = Field(default_factory=list, max_length=MAX_FINDING_ROWS)

    # --- Lineage ---
    lineage_producer_module_id: str = Field(default="", max_length=160)
    lineage_read_run_id: str = Field(default="", max_length=180)
    lineage_read_request_id: str = Field(default="", max_length=180)
    lineage_registry_snapshot_id: str = Field(default="", max_length=180)

    # --- Derived presentation ---
    derived_title: str = Field(default="", max_length=240)
    derived_status_label: str = Field(default="", max_length=120)
    bounded_summary: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)
    severity_counts: dict[str, int] = Field(default_factory=dict, max_length=8)
    incomplete: bool = False
    integrity_verified: bool = False

    # --- Ownership floors ---
    body_stored: Literal[False] = False
    report_regenerated: Literal[False] = False

    @model_validator(mode="after")
    def validate_integrity_claim(self) -> BobaValidationReportCardV1:
        if self.integrity_verified and not (self.content_digest and self.expected_digest_match):
            raise ValidationError(
                "Report integrity cannot be reported as verified without a matching digest."
            )
        return self


class BobaValidationReportSectionV1(BobaContract):
    report_section_id: str = Field(min_length=1, max_length=180)
    report_document_id: str = Field(default="", max_length=180)
    section_type: str = Field(default="unknown", max_length=80)
    title: str = Field(default="", max_length=240)
    bounded_text: str = Field(default="", max_length=2_000)
    item_count: int = Field(default=0, ge=0)
    source_owned: Literal[True] = True
    owner_fact: Literal[True] = True
    decision_bearing: bool = False
    evidence_bearing: bool = False
    warning_bearing: bool = False
    limitation_bearing: bool = False
    truncated: bool = False


class BobaValidationReportFindingV1(BobaContract):
    finding_id: str = Field(min_length=1, max_length=180)
    report_document_id: str = Field(default="", max_length=180)

    # --- Owner facts ---
    owner_fact: Literal[True] = True
    producer_module_id: str = Field(default="unknown", max_length=160)
    authority_domain: str = Field(default="unknown", max_length=80)
    finding_type: str = Field(default="unknown", max_length=120)
    severity: str = Field(default="unknown", max_length=40)
    title: str = Field(default="", max_length=240)
    bounded_summary: str = Field(default="", max_length=2_000)
    source_status: str = Field(default="", max_length=180)
    source_decision: str = Field(default="", max_length=180)
    confirmed_fact: str = Field(default="", max_length=1_200)
    source_assessment: str = Field(default="", max_length=1_200)
    occurred_at: str = Field(default="", max_length=80)
    timestamp_precision: str = Field(default="unknown", max_length=40)
    current: bool = False
    stale: bool = False
    requires_human_interpretation: bool = False
    evidence_reference_ids: list[str] = Field(default_factory=list, max_length=32)

    # --- Derived presentation, kept away from the owner's own words ---
    derived_severity_label: str = Field(default="", max_length=80)
    derived_title: str = Field(default="", max_length=240)
    root_cause_inferred: Literal[False] = False
    repair_inferred: Literal[False] = False


class BobaValidationEvidenceRefV1(BobaContract):
    """Evidence by reference. This module stores no evidence payload."""

    evidence_ref_id: str = Field(min_length=1, max_length=180)
    origin: ValidationProjectionSourceV1 = "validator_runner"
    owner_fact: Literal[True] = True
    source_record_id: str = Field(default="", max_length=180)
    validation_run_id: str = Field(default="", max_length=180)
    check_run_id: str = Field(default="", max_length=180)
    report_document_id: str = Field(default="", max_length=180)
    validator_id: str = Field(default="", max_length=180)
    source_type: str = Field(default="unknown", max_length=80)
    category: str = Field(default="unknown", max_length=80)
    artifact_id: str = Field(default="", max_length=180)
    artifact_digest: str = Field(default="", max_length=64)
    evidence_digest: str = Field(default="", max_length=64)
    bounded_summary: str = Field(default="", max_length=1_200)
    reliability: str = Field(default="unknown", max_length=40)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    supports_pass: bool = False
    supports_failure: bool = False
    available: bool = True
    current: bool = False
    stale: bool = False
    verifiable: bool = False
    requires_human_interpretation: bool = False
    redacted: Literal[True] = True
    derived_availability_label: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def validate_support(self) -> BobaValidationEvidenceRefV1:
        if self.supports_pass and self.supports_failure:
            raise ValidationError(
                "A single evidence reference cannot be projected as supporting both "
                "a pass and a failure; the contradiction belongs in a conflict."
            )
        if self.supports_pass and not self.available:
            raise ValidationError("Unavailable evidence cannot be projected as supporting a pass.")
        return self


class BobaValidationConflictParticipantV1(BobaContract):
    participant_id: str = Field(min_length=1, max_length=180)
    source_module_id: str = Field(default="unknown", max_length=160)
    record_kind: str = Field(default="unknown", max_length=80)
    record_id: str = Field(default="", max_length=180)
    validator_id: str = Field(default="", max_length=180)
    validator_version: str = Field(default="", max_length=80)
    reported_value: str = Field(default="", max_length=240)
    reported_at: str = Field(default="", max_length=80)
    digest: str = Field(default="", max_length=64)
    owner_fact: Literal[True] = True


class BobaValidationConflictV1(BobaContract):
    """An explicitly named disagreement. Never resolved, never averaged."""

    conflict_id: str = Field(min_length=1, max_length=180)
    conflict_kind: ValidationConflictKindV1 = "unknown"
    subject_kind: str = Field(default="unknown", max_length=80)
    subject_id: str = Field(default="", max_length=180)
    bounded_summary: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)
    participants: list[BobaValidationConflictParticipantV1] = Field(
        default_factory=list, max_length=MAX_CONFLICT_PARTICIPANTS
    )
    distinct_values: list[str] = Field(default_factory=list, max_length=MAX_CONFLICT_PARTICIPANTS)
    detected_at: str = Field(default_factory=now_iso, max_length=80)

    # --- Floors that keep this an observation rather than a judgement ---
    preserved_separately: Literal[True] = True
    resolved: Literal[False] = False
    winner_selected: Literal[False] = False
    values_merged: Literal[False] = False
    values_averaged: Literal[False] = False
    root_cause_inferred: Literal[False] = False
    repair_inferred: Literal[False] = False
    workflow_completion_inferred: Literal[False] = False
    requires_human_interpretation: Literal[True] = True

    @model_validator(mode="after")
    def validate_conflict_shape(self) -> BobaValidationConflictV1:
        if len(self.participants) < 2:
            raise ValidationError("A validation conflict requires at least two participants.")
        if len(self.distinct_values) < 2:
            raise ValidationError("A validation conflict requires at least two distinct values.")
        return self


class BobaValidationReportsEventV1(BobaContract):
    """This module's own append-only projection event. Not an owner event."""

    event_id: str = Field(min_length=1, max_length=180)
    sequence: int = Field(default=1, ge=1)
    event_type: ValidationReportsEventTypeV1 = "unknown"
    occurred_at: str = Field(default_factory=now_iso, max_length=80)
    project_id: str = Field(min_length=1, max_length=128)
    validation_run_id: str = Field(default="", max_length=180)
    bounded_summary: str = Field(default="", max_length=MAX_SUMMARY_LENGTH)
    binding_digest: str = Field(default="", max_length=64)
    event_digest: str = Field(default="", max_length=64)
    projection_only: Literal[True] = True
    duplicates_owner_event_stream: Literal[False] = False


class BobaValidationReportsRequestV1(BobaContract):
    """Request metadata this module genuinely owns, including idempotency."""

    request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    requested_scope: str = Field(default="full", max_length=80)
    validation_run_id: str = Field(default="", max_length=180)
    idempotency_key: str = Field(default="", max_length=180)
    request_digest: str = Field(default="", max_length=64)
    binding_digest: str = Field(default="", max_length=64)
    reused_existing_projection: bool = False
    executes_nothing: Literal[True] = True


class BobaValidationReportsSignalUsageV1(BobaContract):
    validator_runner_records_read: bool = False
    report_reader_records_read: bool = False
    artifact_inspector_records_read: bool = False
    workflow_controller_records_read: bool = False
    safety_gate_records_read: bool = False
    final_decision_bus_records_read: bool = False
    sources_unavailable: list[str] = Field(default_factory=list, max_length=16)
    validation_executed: Literal[False] = False
    reports_read_from_disk: Literal[False] = False
    owner_records_modified: Literal[False] = False
    safety_decision_created: Literal[False] = False
    workflow_advanced: Literal[False] = False
    approval_created: Literal[False] = False


class BobaValidationReportsOverviewV1(BobaContract):
    overview_id: str = Field(min_length=1, max_length=180)
    validation_available: bool = False
    reports_available: bool = False
    matrix_cell_count: int = Field(default=0, ge=0)
    report_card_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    state_counts: dict[str, int] = Field(default_factory=dict, max_length=16)
    stale: bool = False
    evidence_missing: bool = True
    derived_headline: str = Field(default="", max_length=240)


class BobaValidationReportsSetV1(BobaContract):
    schema_version: Literal["boba_validation_reports_v1"] = "boba_validation_reports_v1"
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    registry_snapshot: BobaValidationReportsRegistrySnapshotV1
    binding: BobaValidationBindingV1
    summary: BobaValidationSummaryV1
    matrix: BobaValidationMatrixV1
    report_cards: list[BobaValidationReportCardV1] = Field(
        default_factory=list, max_length=MAX_REPORT_CARDS
    )
    evidence: list[BobaValidationEvidenceRefV1] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ROWS
    )
    conflicts: list[BobaValidationConflictV1] = Field(
        default_factory=list, max_length=MAX_CONFLICT_ROWS
    )
    overview: BobaValidationReportsOverviewV1
    signal_usage: BobaValidationReportsSignalUsageV1 = Field(
        default_factory=BobaValidationReportsSignalUsageV1
    )
    projection_digest: str = Field(default="", max_length=64)
    notices: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_WARNINGS)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Validation + Reports is a read-only projection and executes nothing.",
            "Validator Runner remains the only owner of validation verdicts.",
            "Report Reader remains the only owner of report bodies.",
            "Safety Gate remains authoritative for safety decisions.",
            "A projection is never an approval, a quality decision or a workflow "
            "transition.",
        ],
        max_length=MAX_WARNINGS,
    )


# ----------------------------------------------------------------------
# Fixed registries
# ----------------------------------------------------------------------
def build_fixed_validation_matrix_state_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed, non-collapsible matrix state vocabulary."""
    descriptions: dict[str, str] = {
        "PASS": "An owner-recorded passing verdict backed by owner evidence.",
        "FAIL": "An owner-recorded failing verdict backed by owner evidence.",
        "BLOCKED": "The check produced no verdict because it was obstructed.",
        "SKIPPED": "The check was deliberately not required and was skipped.",
        "NOT_RUN": "The check exists but has not produced a verdict yet.",
        "STALE": "A verdict exists but its binding changed, so it cannot be reused.",
        "MISSING": "No owner evidence exists. This is never treated as a pass.",
    }
    return {
        state: {
            "state": state,
            "description": descriptions[state],
            "verdict_bearing": state in VERDICT_STATES,
            "owner_statuses": sorted(
                owner for owner, mapped in _OWNER_CHECK_STATE.items() if mapped == state
            ),
            "counts_as_success": state == "PASS",
        }
        for state in MATRIX_STATES
    }


def build_fixed_validation_projection_source_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed set of owner modules this projection may read."""
    owners: dict[str, tuple[str, str]] = {
        "validator_runner": ("Validator Runner", "validation execution and verdicts"),
        "report_reader": ("Report Reader", "safe report reading and report bodies"),
        "artifact_inspector": ("Artifact Inspector", "artifact identity and digests"),
        "workflow_controller": ("Workflow Controller", "workflow state and revision"),
        "safety_gate": ("Safety Gate", "safety authorisation"),
        "final_decision_bus": ("Final Decision Bus", "final action authorisation"),
    }
    return {
        module_id: {
            "source_module_id": module_id,
            "name": name,
            "owns": owns,
            "access": "read_only",
            "projection_may_override": False,
            "projection_may_execute": False,
        }
        for module_id, (name, owns) in owners.items()
    }


def build_fixed_validation_conflict_kind_registry() -> dict[str, dict[str, Any]]:
    """Return the fixed conflict vocabulary. Conflicts are named, never solved."""
    kinds: dict[str, str] = {
        "check_status_conflict": (
            "Two check runs for the same plan check report different statuses."
        ),
        "result_status_conflict": (
            "A recorded result status disagrees with its own check run status."
        ),
        "validator_version_conflict": (
            "The same validator reports results under different versions."
        ),
        "input_digest_conflict": (
            "Checks for one target ran against different input digests."
        ),
        "suite_decision_conflict": (
            "More than one suite decision exists for a single validation run."
        ),
        "report_status_conflict": (
            "Two reports from the same producer disagree on status."
        ),
        "report_digest_conflict": (
            "A report's content digest does not match its expected digest."
        ),
        "reported_contradiction": (
            "The Report Reader itself recorded a contradiction between reports."
        ),
        "unknown": "A disagreement that does not match a known fixed kind.",
    }
    return {
        kind: {
            "conflict_kind": kind,
            "description": description,
            "resolved_automatically": False,
            "winner_selected": False,
            "root_cause_inferred": False,
        }
        for kind, description in kinds.items()
    }


# ----------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------
class BobaValidationReportsV1:
    """Read-only coordination and presentation over canonical owner records."""

    def __init__(self, store: BobaMemoryStore, integration: BobaIntegration) -> None:
        self.store = store
        self.integration = integration

    # ------------------------------------------------------------------
    # Canonical source access. Read-only, failure-tolerant, never cached.
    # ------------------------------------------------------------------
    _LOADERS: ClassVar[dict[str, str]] = {
        "validator_runner": "load_boba_validator_runner",
        "report_reader": "load_boba_report_reader",
        "artifact_inspector": "load_boba_artifact_inspector",
        "workflow_controller": "load_boba_workflow_controller",
        "safety_gate": "load_boba_safety_gate",
        "final_decision_bus": "load_boba_final_decision_bus",
    }

    def _source_payload(self, module_id: str, project_id: str) -> dict[str, Any]:
        loader_name = self._LOADERS.get(module_id)
        if loader_name is None:
            raise ValidationError("Unknown BOBA validation projection source module.")
        loader = getattr(self.store, loader_name, None)
        if loader is None:
            return {}
        try:
            return _as_mapping(loader(project_id))
        except (ValidationError, NotFoundError, OSError):
            return {}

    def _rows(
        self, project_id: str, module_id: str, key: str, limit: int = 4_096
    ) -> list[dict[str, Any]]:
        return _bounded_rows(self._source_payload(module_id, project_id).get(key), limit)

    def _latest(self, project_id: str, module_id: str, key: str) -> dict[str, Any]:
        rows = self._rows(project_id, module_id, key)
        return rows[-1] if rows else {}

    def _workflow_run(self, project_id: str) -> dict[str, Any]:
        return _active_workflow_run(self._source_payload("workflow_controller", project_id))

    def _workflow_revision(self, project_id: str) -> int:
        revision = self._workflow_run(project_id).get("revision")
        return revision if isinstance(revision, int) and revision >= 0 else 0

    def _reject_foreign_project(self, project_id: str, row: Mapping[str, Any], label: str) -> None:
        """Refuse any owner record that belongs to a different project."""
        owner_project = row.get("project_id")
        if isinstance(owner_project, str) and owner_project and owner_project != project_id:
            raise ValidationError(
                f"A BOBA validation {label} from another project cannot be projected."
            )

    def _signal_usage(self, project_id: str) -> BobaValidationReportsSignalUsageV1:
        seen: dict[str, bool] = {}
        unavailable: list[str] = []
        for module_id in self._LOADERS:
            payload = self._source_payload(module_id, project_id)
            seen[module_id] = bool(payload)
            if not payload:
                unavailable.append(module_id)
        return BobaValidationReportsSignalUsageV1(
            validator_runner_records_read=seen.get("validator_runner", False),
            report_reader_records_read=seen.get("report_reader", False),
            artifact_inspector_records_read=seen.get("artifact_inspector", False),
            workflow_controller_records_read=seen.get("workflow_controller", False),
            safety_gate_records_read=seen.get("safety_gate", False),
            final_decision_bus_records_read=seen.get("final_decision_bus", False),
            sources_unavailable=unavailable,
        )

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def build_validation_reports_registry(self, project_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        states = build_fixed_validation_matrix_state_registry()
        sources = build_fixed_validation_projection_source_registry()
        conflicts = build_fixed_validation_conflict_kind_registry()
        registry_digest = _digest({"s": states, "o": sources, "c": conflicts})
        snapshot_id = _stable_id("validation_reports_registry", "v1", registry_digest)

        # An immutable snapshot is reused verbatim when it already exists. Rebuilding
        # it would mint a fresh ``created_at`` and collide with its own immutability.
        stored = self.store.load_boba_validation_reports_registry(project_id, snapshot_id)
        snapshot = (
            BobaValidationReportsRegistrySnapshotV1.model_validate(stored)
            if isinstance(stored, Mapping)
            else BobaValidationReportsRegistrySnapshotV1(
                registry_snapshot_id=snapshot_id,
                matrix_states=list(MATRIX_STATES),
                owner_check_statuses=sorted(_OWNER_CHECK_STATE),
                owner_status_to_matrix_state=owner_check_state_mapping(),
                verdict_bearing_states=sorted(VERDICT_STATES),
                staleness_dimensions=list(_STALE_DIMENSIONS),
                projection_source_module_ids=sorted(sources),
                conflict_kinds=sorted(conflicts),
                registry_digest=registry_digest,
            )
        )
        if not isinstance(stored, Mapping):
            self.store.save_boba_validation_reports_registry(
                project_id, snapshot_id, snapshot.model_dump(mode="json")
            )
        return {
            "schema_version": "boba_validation_reports_registry_v1",
            "project_id": project_id,
            "registry_snapshot": snapshot.model_dump(mode="json"),
            "matrix_states": states,
            "projection_sources": sources,
            "conflict_kinds": conflicts,
            "notices": [PROJECTION_ONLY_NOTICE, MISSING_EVIDENCE_NOTICE, CONFLICT_NOTICE],
        }

    # ------------------------------------------------------------------
    # Validation run selection and staleness binding
    # ------------------------------------------------------------------
    def _validation_runs(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._rows(project_id, "validator_runner", "validation_runs")
        for row in rows:
            self._reject_foreign_project(project_id, row, "validation run")
        return sorted(
            rows,
            key=lambda row: (
                _safe_text(row.get("created_at"), 80),
                _safe_text(row.get("validation_run_id"), 180),
            ),
        )

    def _select_validation_run(
        self, project_id: str, validation_run_id: str = ""
    ) -> dict[str, Any]:
        runs = self._validation_runs(project_id)
        if not validation_run_id:
            return runs[-1] if runs else {}
        wanted = _safe_id(validation_run_id, "validation run id")
        for row in runs:
            if _safe_text(row.get("validation_run_id"), 180) == wanted:
                return row
        raise NotFoundError("The requested BOBA validation run is unavailable.")

    def _current_validator_versions(self, project_id: str) -> dict[str, str]:
        versions: dict[str, str] = {}
        for row in self._rows(project_id, "validator_runner", "validator_descriptors"):
            validator_id = _safe_text(row.get("validator_id"), 180)
            version = _safe_text(row.get("validator_version"), 80)
            if validator_id and version:
                versions[validator_id] = version
        return versions

    def _suite_decision(self, project_id: str, validation_run_id: str) -> dict[str, Any]:
        matches = [
            row
            for row in self._rows(project_id, "validator_runner", "suite_decisions")
            if _safe_text(row.get("validation_run_id"), 180) == validation_run_id
        ]
        return matches[-1] if matches else {}

    def _artifact_digest_for(self, project_id: str, run: Mapping[str, Any]) -> str:
        """Prefer the exact bound artifact digest, falling back to the target digest."""
        plan_id = _safe_text(run.get("validation_plan_id"), 180)
        for row in self._rows(project_id, "validator_runner", "input_bindings"):
            self._reject_foreign_project(project_id, row, "input binding")
            if _safe_text(row.get("validation_plan_id"), 180) != plan_id:
                continue
            digest = validate_projection_digest(row.get("artifact_digest"), label="artifact digest")
            if digest:
                return digest
        return validate_projection_digest(run.get("target_digest"), label="target digest")

    def _binding(self, project_id: str, run: Mapping[str, Any]) -> BobaValidationBindingV1:
        """Bind a verdict to all eight dimensions and name what invalidated reuse."""
        current_run = self._workflow_run(project_id)
        current_workflow_id = _safe_text(current_run.get("workflow_run_id"), 180)
        current_stage = _safe_text(current_run.get("current_stage_instance_id"), 180)
        revision = self._workflow_revision(project_id)

        run_id = _safe_text(run.get("validation_run_id"), 180)
        bound_workflow_id = _safe_text(run.get("workflow_run_id"), 180)
        bound_stage = _safe_text(run.get("stage_instance_id"), 180)
        target_id = _safe_text(run.get("target_id"), 180)
        target_digest = validate_projection_digest(run.get("target_digest"), label="target digest")
        artifact_digest = self._artifact_digest_for(project_id, run) if run else ""
        request_id = _safe_text(run.get("idempotency_key"), 180)
        decision = self._suite_decision(project_id, run_id) if run_id else {}

        invalidated: list[str] = []
        if run and _safe_text(run.get("project_id"), 128) not in {"", project_id}:
            invalidated.append("project_id")
        if bound_workflow_id and current_workflow_id and bound_workflow_id != current_workflow_id:
            invalidated.append("workflow_run_id")
        if bound_stage and current_stage and bound_stage != current_stage:
            invalidated.append("stage_instance_id")
        if run and not target_id:
            invalidated.append("target_id")
        if decision and decision.get("project_snapshot_current") is False:
            invalidated.append("workflow_revision")
        if decision and decision.get("target_digest_unchanged") is False:
            invalidated.append("artifact_digest")
        current_versions = self._current_validator_versions(project_id)
        for cell in self._check_rows(project_id, run_id) if run_id else []:
            validator_id = _safe_text(cell.get("validator_id"), 180)
            version = _safe_text(cell.get("validator_version"), 80)
            expected = current_versions.get(validator_id, "")
            if validator_id and version and expected and version != expected:
                invalidated.append("validator_version")
                break
        if run and not request_id:
            invalidated.append("validation_request_id")

        ordered = [name for name in _STALE_DIMENSIONS if name in invalidated]
        bound = bool(run)
        summary = (
            "This validation run is bound to the current project state."
            if bound and not ordered
            else STALE_NOTICE
            if ordered
            else "No validation run is bound to this project yet."
        )
        return BobaValidationBindingV1(
            binding_id=_stable_id("vrbind", project_id, run_id, revision),
            project_id=project_id,
            workflow_run_id=bound_workflow_id,
            stage_instance_id=bound_stage,
            target_type=_safe_text(run.get("target_type") or "unknown", 80),
            target_id=target_id,
            target_digest=target_digest,
            workflow_revision=revision,
            artifact_digest=artifact_digest,
            validator_id="",
            validator_version="",
            validation_request_id=request_id,
            binding_digest=_digest(
                {
                    "project_id": project_id,
                    "workflow_run_id": bound_workflow_id,
                    "stage_instance_id": bound_stage,
                    "target_id": target_id,
                    "target_digest": target_digest,
                    "workflow_revision": revision,
                    "artifact_digest": artifact_digest,
                    "validation_request_id": request_id,
                }
            ),
            bound=bound,
            reuse_valid=bound and not ordered,
            invalidated_dimensions=ordered,
            derived_summary=summary,
        )

    # ------------------------------------------------------------------
    # Validation matrix
    # ------------------------------------------------------------------
    def _check_rows(self, project_id: str, validation_run_id: str) -> list[dict[str, Any]]:
        """Return this run's check runs in a fully deterministic order."""
        rows = [
            row
            for row in self._rows(project_id, "validator_runner", "check_runs")
            if _safe_text(row.get("validation_run_id"), 180) == validation_run_id
        ]
        return sorted(
            rows,
            key=lambda row: (
                _safe_text(row.get("validator_id"), 180),
                _safe_text(row.get("plan_check_id"), 180),
                int(row.get("attempt_number") or 1),
                _safe_text(row.get("check_run_id"), 180),
            ),
        )

    def _results_by_check(
        self, project_id: str, validation_run_id: str
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self._rows(project_id, "validator_runner", "validation_results"):
            if _safe_text(row.get("validation_run_id"), 180) != validation_run_id:
                continue
            check_run_id = _safe_text(row.get("check_run_id"), 180)
            if check_run_id:
                out[check_run_id] = row
        return out

    def _evidence_by_check(
        self, project_id: str, validation_run_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows(project_id, "validator_runner", "evidence_records"):
            if _safe_text(row.get("validation_run_id"), 180) != validation_run_id:
                continue
            check_run_id = _safe_text(row.get("check_run_id"), 180)
            if check_run_id:
                out.setdefault(check_run_id, []).append(row)
        return out

    def _incidents_by_check(self, project_id: str, validation_run_id: str) -> dict[str, list[str]]:
        """Project incident types as failure categories, exactly as the owner named them."""
        out: dict[str, list[str]] = {}
        for row in self._rows(project_id, "validator_runner", "incidents"):
            if _safe_text(row.get("validation_run_id"), 180) != validation_run_id:
                continue
            check_run_id = _safe_text(row.get("check_run_id"), 180)
            incident_type = _safe_text(row.get("incident_type"), 80)
            if not incident_type:
                continue
            bucket = out.setdefault(check_run_id, [])
            if incident_type not in bucket and len(bucket) < 16:
                bucket.append(incident_type)
        return out

    def _cell(
        self,
        *,
        project_id: str,
        check: Mapping[str, Any],
        result: Mapping[str, Any],
        evidence: Sequence[Mapping[str, Any]],
        failure_categories: Sequence[str],
        binding: BobaValidationBindingV1,
        current_versions: Mapping[str, str],
    ) -> BobaValidationMatrixCellV1:
        owner_status = _safe_text(check.get("status") or "unknown", 80)
        check_run_id = _safe_text(check.get("check_run_id"), 180)
        validator_id = _safe_text(check.get("validator_id"), 180)
        validator_version = _safe_text(check.get("validator_version"), 80)

        owner_state = derive_matrix_state(owner_status)
        evidence_present = bool(evidence)

        # A pass without owner evidence is downgraded rather than trusted. This is
        # the single most important rule in this module.
        if owner_state == "PASS" and not evidence_present:
            derived_state: ValidationMatrixState = "MISSING"
            reason = (
                "The Validator Runner recorded a passing status but no evidence "
                "record exists for this check, so no pass is claimed."
            )
        else:
            derived_state = owner_state
            reason = matrix_state_reason(owner_status)

        stale_reasons: list[str] = []
        expected_version = current_versions.get(validator_id, "")
        if validator_version and expected_version and validator_version != expected_version:
            stale_reasons.append("validator_version")
        if binding.invalidated_dimensions:
            stale_reasons.extend(binding.invalidated_dimensions)
        ordered_stale = [name for name in _STALE_DIMENSIONS if name in set(stale_reasons)]

        # Staleness overrides the presentation but never the owner fact, which is
        # why owner_reported_state is kept alongside derived_state.
        stale = bool(ordered_stale) and derived_state in VERDICT_STATES
        if stale:
            reason = (
                f"{matrix_state_reason(owner_status)} That verdict cannot be reused "
                f"because these bound dimensions changed: {', '.join(ordered_stale)}."
            )
            derived_state = "STALE"

        diagnostics: list[str] = []
        for source in (check.get("failure_summary"), check.get("stop_reason")):
            text = bounded_projection_text(source, 300)
            if text and text not in diagnostics:
                diagnostics.append(text)
        for item in _bounded_ids(result.get("failed_assertions"), 8):
            text = bounded_projection_text(item, 200)
            if text and text not in diagnostics and len(diagnostics) < MAX_DIAGNOSTIC_ROWS:
                diagnostics.append(text)

        return BobaValidationMatrixCellV1(
            cell_id=_stable_id("vrcell", project_id, check_run_id, owner_status),
            owner_status=owner_status,
            check_run_id=check_run_id,
            validation_run_id=_safe_text(check.get("validation_run_id"), 180),
            plan_check_id=_safe_text(check.get("plan_check_id"), 180),
            validator_id=validator_id,
            validator_version=validator_version,
            category=_safe_text(check.get("category") or "unknown", 80),
            required=bool(check.get("required", True)),
            attempt_number=max(1, min(16, int(check.get("attempt_number") or 1))),
            result_id=_safe_text(result.get("result_id"), 180),
            result_status=_safe_text(result.get("status"), 80),
            result_digest=validate_projection_digest(
                result.get("result_digest"), label="result digest"
            ),
            input_digest=validate_projection_digest(
                check.get("input_digest"), label="input digest"
            ),
            environment_digest=validate_projection_digest(
                check.get("environment_digest"), label="environment digest"
            ),
            evidence_ids=_bounded_ids(check.get("evidence_ids"), 64),
            started_at=_safe_text(check.get("started_at"), 80),
            completed_at=_safe_text(check.get("completed_at"), 80),
            duration_seconds=(
                float(check["duration_seconds"])
                if isinstance(check.get("duration_seconds"), int | float)
                else None
            ),
            exit_code=check.get("exit_code") if isinstance(check.get("exit_code"), int) else None,
            blocks_suite_pass=bool(result.get("blocks_suite_pass", True)),
            protected_state_unchanged=bool(check.get("protected_state_unchanged", True)),
            failed_assertions=_bounded_ids(result.get("failed_assertions"), 32),
            unavailable_assertions=_bounded_ids(result.get("unavailable_assertions"), 32),
            failure_categories=list(failure_categories)[:16],
            bounded_diagnostics=diagnostics[:MAX_DIAGNOSTIC_ROWS],
            owner_warnings=_bounded_warnings(check.get("warnings")),
            workflow_revision=binding.workflow_revision,
            derived_state=derived_state,
            owner_reported_state=owner_state,
            derived_state_reason=reason,
            derived_title=f"{validator_id or 'Unknown validator'} - {derived_state}",
            verdict_available=verdict_available(derived_state),
            evidence_present=evidence_present,
            stale=stale,
            stale_reasons=ordered_stale,
            binding_digest=binding.binding_digest,
        )

    def build_validation_matrix(
        self, project_id: str, validation_run_id: str = ""
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        run = self._select_validation_run(project_id, validation_run_id)
        binding = self._binding(project_id, run)
        run_id = _safe_text(run.get("validation_run_id"), 180)

        checks = self._check_rows(project_id, run_id) if run_id else []
        results = self._results_by_check(project_id, run_id) if run_id else {}
        evidence = self._evidence_by_check(project_id, run_id) if run_id else {}
        incidents = self._incidents_by_check(project_id, run_id) if run_id else {}
        current_versions = self._current_validator_versions(project_id)

        truncated = len(checks) > MAX_MATRIX_CELLS
        cells = [
            self._cell(
                project_id=project_id,
                check=check,
                result=results.get(_safe_text(check.get("check_run_id"), 180), {}),
                evidence=evidence.get(_safe_text(check.get("check_run_id"), 180), []),
                failure_categories=incidents.get(_safe_text(check.get("check_run_id"), 180), []),
                binding=binding,
                current_versions=current_versions,
            )
            for check in checks[:MAX_MATRIX_CELLS]
        ]

        counts: dict[str, int] = dict.fromkeys(MATRIX_STATES, 0)
        for cell in cells:
            counts[cell.derived_state] += 1

        required = [cell for cell in cells if cell.required]
        required_complete = bool(required) and all(cell.verdict_available for cell in required)
        evidence_complete = bool(cells) and all(cell.evidence_present for cell in required)

        warnings: list[str] = []
        if not cells:
            warnings.append("No validation checks exist for this project yet.")
        if counts["MISSING"]:
            warnings.append(f"{counts['MISSING']} check(s) have no owner evidence.")
        if counts["STALE"]:
            warnings.append(
                f"{counts['STALE']} verdict(s) cannot be reused because the binding changed."
            )
        if truncated:
            warnings.append(
                f"Only the first {MAX_MATRIX_CELLS} checks are shown; the projection is bounded."
            )

        matrix = BobaValidationMatrixV1(
            matrix_id=_stable_id("vrmatrix", project_id, run_id, binding.binding_digest),
            project_id=project_id,
            validation_run_id=run_id,
            validation_plan_id=_safe_text(run.get("validation_plan_id"), 180),
            binding=binding,
            cells=cells,
            state_counts=counts,
            total_cells=len(checks),
            truncated=truncated,
            required_verdict_complete=required_complete and evidence_complete,
            evidence_complete=evidence_complete,
            any_conflict=False,
            matrix_digest=_digest([cell.model_dump(mode="json") for cell in cells]),
            notices=[PROJECTION_ONLY_NOTICE, MISSING_EVIDENCE_NOTICE, NOT_PRODUCTION_READY_NOTICE],
            warnings=warnings[:MAX_WARNINGS],
            limitations=[
                "The Validator Runner owns every status shown here.",
                "Derived states are presentation only and never replace owner facts.",
            ],
        )
        return matrix.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Validation summary
    # ------------------------------------------------------------------
    def build_validation_summary(
        self, project_id: str, validation_run_id: str = ""
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        run = self._select_validation_run(project_id, validation_run_id)
        run_id = _safe_text(run.get("validation_run_id"), 180)
        binding = self._binding(project_id, run)
        decision = self._suite_decision(project_id, run_id) if run_id else {}
        matrix = self.build_validation_matrix(project_id, run_id)
        counts = {
            str(key): int(value)
            for key, value in _as_mapping(matrix.get("state_counts")).items()
            if isinstance(value, int)
        }

        evidence_available = bool(self._evidence_by_check(project_id, run_id)) if run_id else False
        evidence_missing = not evidence_available or bool(counts.get("MISSING"))
        owner_evidence_complete = bool(decision.get("evidence_complete", False))
        stale = bool(binding.invalidated_dimensions)

        # ``technical_validation_passed`` is the owner's own field. It is copied,
        # never recomputed, and is forced down when evidence is absent.
        owner_passed = bool(decision.get("technical_validation_passed", False))
        technical_passed = owner_passed and evidence_available and not stale
        required_passed = (
            bool(decision.get("required_checks_passed", False)) and not evidence_missing
        )

        suite_decision = _safe_text(decision.get("decision") or "unavailable", 80)
        run_status = _safe_text(run.get("run_status") or "unavailable", 80)

        if not run:
            headline = "No validation run exists for this project yet."
        elif stale:
            headline = f"Validation is stale ({suite_decision}); the bound state changed."
        elif evidence_missing:
            headline = f"Validation is incomplete ({suite_decision}); evidence is missing."
        else:
            headline = f"Validator Runner suite decision: {suite_decision}."

        warnings: list[str] = _bounded_warnings(run.get("warnings"))
        if not run:
            warnings.append("No validation evidence is available for this project.")
        if stale:
            warnings.append(STALE_NOTICE)
        if evidence_missing and run:
            warnings.append(MISSING_EVIDENCE_NOTICE)
        if owner_passed and not technical_passed:
            warnings.append(
                "The owner recorded a technical pass, but this projection does not "
                "present it as current because evidence is missing or the binding changed."
            )

        summary = BobaValidationSummaryV1(
            summary_id=_stable_id("vrsum", project_id, run_id, binding.binding_digest),
            project_id=project_id,
            validation_run_id=run_id,
            validation_plan_id=_safe_text(run.get("validation_plan_id"), 180),
            run_status=run_status,
            suite_decision_id=_safe_text(decision.get("suite_decision_id"), 180),
            suite_decision=suite_decision,
            owner_decision_summary=bounded_projection_text(decision.get("decision_summary")),
            required_checks_complete=bool(decision.get("required_checks_complete", False)),
            required_checks_passed=required_passed,
            optional_checks_complete=bool(decision.get("optional_checks_complete", False)),
            acceptance_criteria_met=bool(decision.get("acceptance_criteria_met", False)),
            rejection_criteria_triggered=bool(decision.get("rejection_criteria_triggered", False)),
            owner_evidence_complete=owner_evidence_complete,
            target_digest_unchanged=bool(decision.get("target_digest_unchanged", False)),
            environment_digest_unchanged=bool(decision.get("environment_digest_unchanged", False)),
            project_snapshot_current=bool(decision.get("project_snapshot_current", False)),
            technical_validation_passed=technical_passed,
            human_review_required=bool(decision.get("human_review_required", False)),
            started_at=_safe_text(run.get("started_at"), 80),
            completed_at=_safe_text(run.get("completed_at"), 80),
            workflow_revision=binding.workflow_revision,
            derived_status_title=headline,
            derived_summary=bounded_projection_text(headline),
            state_counts=counts,
            validation_evidence_available=evidence_available,
            evidence_missing=evidence_missing,
            stale=stale,
            binding=binding,
            notices=[
                PROJECTION_ONLY_NOTICE,
                NOT_PRODUCTION_READY_NOTICE,
                MISSING_EVIDENCE_NOTICE,
            ],
            warnings=warnings[:MAX_WARNINGS],
            limitations=[
                "Validator Runner owns the suite decision shown here.",
                "This summary grants no approval and authorises no action.",
            ],
        )
        return summary.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Report projection
    # ------------------------------------------------------------------
    def _report_documents(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._rows(project_id, "report_reader", "report_documents")
        for row in rows:
            self._reject_foreign_project(project_id, row, "report document")
        return sorted(
            rows,
            key=lambda row: (
                _safe_text(row.get("producer_module_id"), 160),
                _safe_text(row.get("report_type"), 80),
                _safe_text(row.get("report_document_id"), 180),
            ),
        )

    def _reference_index(self, project_id: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self._rows(project_id, "report_reader", "report_references"):
            self._reject_foreign_project(project_id, row, "report reference")
            key = _safe_text(row.get("report_reference_id"), 180)
            if key:
                out[key] = row
        return out

    def _findings_by_document(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows(project_id, "report_reader", "findings"):
            key = _safe_text(row.get("report_document_id"), 180)
            if key:
                out.setdefault(key, []).append(row)
        for rows in out.values():
            rows.sort(key=lambda row: _safe_text(row.get("finding_id"), 180))
        return out

    def _report_evidence_by_document(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows(project_id, "report_reader", "evidence_references"):
            key = _safe_text(row.get("report_document_id"), 180)
            if key:
                out.setdefault(key, []).append(row)
        return out

    def _read_run_for_document(self, project_id: str, document_id: str) -> dict[str, Any]:
        for row in self._rows(project_id, "report_reader", "read_runs"):
            ids = _bounded_ids(row.get("report_document_ids"), 128)
            if document_id in ids:
                return row
        return {}

    def _report_card(
        self,
        *,
        project_id: str,
        document: Mapping[str, Any],
        reference: Mapping[str, Any],
        findings: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]],
    ) -> BobaValidationReportCardV1:
        document_id = _safe_text(document.get("report_document_id"), 180)
        read_run = self._read_run_for_document(project_id, document_id)
        malformed = bool(document.get("malformed", False))
        stale = bool(document.get("stale", False))
        digest_match = bool(document.get("expected_digest_match", True))
        schema_supported = bool(document.get("schema_supported", True))
        read_status = _safe_text(document.get("read_status") or "unknown", 80)

        severities: dict[str, int] = {}
        for row in findings:
            key = _safe_text(row.get("severity") or "unknown", 40)
            severities[key] = severities.get(key, 0) + 1

        validation_run_ids: list[str] = []
        validator_ids: list[str] = []
        artifact_ids: list[str] = []
        artifact_digests: list[str] = []
        for row in evidence:
            for value, bucket in (
                (_safe_text(row.get("validation_run_id"), 180), validation_run_ids),
                (_safe_text(row.get("validator_id"), 180), validator_ids),
                (_safe_text(row.get("artifact_id"), 180), artifact_ids),
            ):
                if value and value not in bucket and len(bucket) < 32:
                    bucket.append(value)
            digest = validate_projection_digest(row.get("artifact_digest"), label="artifact digest")
            if digest and digest not in artifact_digests and len(artifact_digests) < 32:
                artifact_digests.append(digest)

        if malformed:
            status_label = "Malformed report"
        elif not schema_supported:
            status_label = "Unsupported schema"
        elif not digest_match:
            status_label = "Digest mismatch"
        elif stale:
            status_label = "Stale report"
        else:
            status_label = f"Read {read_status}"

        producer = _safe_text(document.get("producer_module_id") or "unknown", 160)
        report_type = _safe_text(document.get("report_type") or "unknown", 80)
        return BobaValidationReportCardV1(
            report_card_id=_stable_id("vrcard", project_id, document_id),
            report_document_id=document_id,
            report_reference_id=_safe_text(document.get("report_reference_id"), 180),
            source_module_id=producer,
            producer_record_id=_safe_text(document.get("producer_record_id"), 180),
            report_type=report_type,
            report_status=read_status,
            schema_id=_safe_text(document.get("schema_id"), 180),
            schema_version=_safe_text(document.get("schema_version"), 80),
            report_format=_safe_text(document.get("format") or "unknown", 40),
            parser_id=_safe_text(document.get("parser_id"), 120),
            generated_at=_safe_text(reference.get("created_at"), 80),
            content_digest=validate_projection_digest(
                document.get("content_digest"), label="content digest"
            ),
            expected_digest_match=digest_match,
            project_identity_match=bool(document.get("project_identity_match", True)),
            source_identity_match=bool(document.get("source_identity_match", True)),
            schema_supported=schema_supported,
            current_project_snapshot_match=bool(
                document.get("current_project_snapshot_match", False)
            ),
            historical=bool(document.get("historical", False)),
            stale=stale,
            malformed=malformed,
            truncated=bool(document.get("truncated", False)),
            warning_count=max(0, int(document.get("warning_count") or 0)),
            limitation_count=max(0, int(document.get("limitation_count") or 0)),
            finding_count=len(findings),
            sanitized_storage_reference=validate_projection_reference(
                reference.get("sanitized_storage_reference"), label="report reference"
            ),
            validation_run_ids=validation_run_ids,
            validator_ids=validator_ids,
            artifact_ids=artifact_ids,
            artifact_digests=artifact_digests,
            evidence_reference_ids=_bounded_ids(document.get("evidence_reference_ids"), 64),
            source_decision_ids=_bounded_ids(document.get("source_decision_ids"), 32),
            section_ids=_bounded_ids(document.get("section_ids"), MAX_SECTION_ROWS),
            finding_ids=_bounded_ids(document.get("finding_ids"), MAX_FINDING_ROWS),
            lineage_producer_module_id=producer,
            lineage_read_run_id=_safe_text(read_run.get("read_run_id"), 180),
            lineage_read_request_id=_safe_text(read_run.get("read_request_id"), 180),
            lineage_registry_snapshot_id=_safe_text(reference.get("source_descriptor_id"), 180),
            derived_title=f"{producer} - {report_type}",
            derived_status_label=status_label,
            bounded_summary=bounded_projection_text(
                "; ".join(_bounded_ids(document.get("warnings"), 4)) or status_label
            ),
            severity_counts=severities,
            incomplete=malformed or not schema_supported or stale or not digest_match,
            integrity_verified=bool(document.get("content_digest")) and digest_match,
        )

    def inspect_reports(self, project_id: str, report_type: str = "") -> dict[str, Any]:
        _safe_id(project_id, "project id")
        wanted = _safe_text(report_type, 80)
        documents = self._report_documents(project_id)
        references = self._reference_index(project_id)
        findings = self._findings_by_document(project_id)
        evidence = self._report_evidence_by_document(project_id)

        selected = [
            document
            for document in documents
            if not wanted or _safe_text(document.get("report_type"), 80) == wanted
        ]
        truncated = len(selected) > MAX_REPORT_CARDS
        cards = [
            self._report_card(
                project_id=project_id,
                document=document,
                reference=references.get(
                    _safe_text(document.get("report_reference_id"), 180), {}
                ),
                findings=findings.get(_safe_text(document.get("report_document_id"), 180), []),
                evidence=evidence.get(_safe_text(document.get("report_document_id"), 180), []),
            )
            for document in selected[:MAX_REPORT_CARDS]
        ]
        return {
            "schema_version": "boba_validation_reports_reports_v1",
            "project_id": project_id,
            "report_type_filter": wanted,
            "report_cards": [card.model_dump(mode="json") for card in cards],
            "total_reports": len(selected),
            "truncated": truncated,
            "reports_available": bool(cards),
            "malformed_count": sum(1 for card in cards if card.malformed),
            "stale_count": sum(1 for card in cards if card.stale),
            "digest_mismatch_count": sum(1 for card in cards if not card.expected_digest_match),
            "notices": [PROJECTION_ONLY_NOTICE, REPORT_BODY_NOTICE],
        }

    def inspect_report_detail(self, project_id: str, report_document_id: str) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        wanted = _safe_id(report_document_id, "report document id")
        documents = self._report_documents(project_id)
        match = next(
            (
                document
                for document in documents
                if _safe_text(document.get("report_document_id"), 180) == wanted
            ),
            None,
        )
        if match is None:
            raise NotFoundError("The requested BOBA validation report is unavailable.")

        references = self._reference_index(project_id)
        findings = self._findings_by_document(project_id).get(wanted, [])
        evidence_rows = self._report_evidence_by_document(project_id).get(wanted, [])
        card = self._report_card(
            project_id=project_id,
            document=match,
            reference=references.get(_safe_text(match.get("report_reference_id"), 180), {}),
            findings=findings,
            evidence=evidence_rows,
        )

        sections = [
            BobaValidationReportSectionV1(
                report_section_id=_safe_text(row.get("report_section_id"), 180) or "unknown",
                report_document_id=wanted,
                section_type=_safe_text(row.get("section_type") or "unknown", 80),
                title=bounded_projection_text(row.get("title"), 240),
                bounded_text=bounded_projection_text(row.get("bounded_text"), 2_000),
                item_count=max(0, int(row.get("item_count") or 0)),
                decision_bearing=bool(row.get("decision_bearing", False)),
                evidence_bearing=bool(row.get("evidence_bearing", False)),
                warning_bearing=bool(row.get("warning_bearing", False)),
                limitation_bearing=bool(row.get("limitation_bearing", False)),
                truncated=bool(row.get("truncated", False)),
            )
            for row in sorted(
                (
                    row
                    for row in self._rows(project_id, "report_reader", "report_sections")
                    if _safe_text(row.get("report_document_id"), 180) == wanted
                ),
                key=lambda row: _safe_text(row.get("report_section_id"), 180),
            )[:MAX_SECTION_ROWS]
        ]

        projected_findings = [
            self._finding(row) for row in findings[:MAX_FINDING_ROWS]
        ]
        failures = [
            row.model_dump(mode="json")
            for row in projected_findings
            if row.severity in {"high", "critical"}
        ]
        warnings = [
            row.model_dump(mode="json")
            for row in projected_findings
            if row.severity in {"medium", "low"}
        ]

        return {
            "schema_version": "boba_validation_reports_detail_v1",
            "project_id": project_id,
            "report_card": card.model_dump(mode="json"),
            "sections": [section.model_dump(mode="json") for section in sections],
            "findings": [row.model_dump(mode="json") for row in projected_findings],
            "failures": failures,
            "warnings": warnings,
            "evidence": [
                row.model_dump(mode="json")
                for row in self._report_evidence_refs(evidence_rows, wanted)
            ],
            "findings_truncated": len(findings) > MAX_FINDING_ROWS,
            "notices": [PROJECTION_ONLY_NOTICE, REPORT_BODY_NOTICE, CONFLICT_NOTICE],
        }

    def _finding(self, row: Mapping[str, Any]) -> BobaValidationReportFindingV1:
        severity = _safe_text(row.get("severity") or "unknown", 40)
        labels = {
            "critical": "Critical finding",
            "high": "High severity finding",
            "medium": "Medium severity finding",
            "low": "Low severity finding",
            "info": "Informational finding",
        }
        return BobaValidationReportFindingV1(
            finding_id=_safe_text(row.get("finding_id"), 180) or "unknown",
            report_document_id=_safe_text(row.get("report_document_id"), 180),
            producer_module_id=_safe_text(row.get("producer_module_id") or "unknown", 160),
            authority_domain=_safe_text(row.get("authority_domain") or "unknown", 80),
            finding_type=_safe_text(row.get("finding_type") or "unknown", 120),
            severity=severity,
            title=bounded_projection_text(row.get("title"), 240),
            bounded_summary=bounded_projection_text(row.get("bounded_summary"), 2_000),
            source_status=_safe_text(row.get("source_status"), 180),
            source_decision=_safe_text(row.get("source_decision"), 180),
            confirmed_fact=bounded_projection_text(row.get("confirmed_fact"), 1_200),
            source_assessment=bounded_projection_text(row.get("source_assessment"), 1_200),
            occurred_at=_safe_text(row.get("occurred_at"), 80),
            timestamp_precision=_safe_text(row.get("timestamp_precision") or "unknown", 40),
            current=bool(row.get("current", False)),
            stale=bool(row.get("stale", False)),
            requires_human_interpretation=bool(row.get("requires_human_interpretation", False)),
            evidence_reference_ids=_bounded_ids(row.get("evidence_reference_ids"), 32),
            derived_severity_label=labels.get(severity, "Unclassified finding"),
            derived_title=bounded_projection_text(row.get("title"), 240)
            or f"{_safe_text(row.get('finding_type') or 'unknown', 120)} finding",
        )

    # ------------------------------------------------------------------
    # Evidence projection
    # ------------------------------------------------------------------
    def _report_evidence_refs(
        self, rows: Sequence[Mapping[str, Any]], document_id: str
    ) -> list[BobaValidationEvidenceRefV1]:
        out: list[BobaValidationEvidenceRefV1] = []
        for row in sorted(
            rows, key=lambda item: _safe_text(item.get("evidence_reference_id"), 180)
        )[:MAX_EVIDENCE_ROWS]:
            available = bool(row.get("available", True))
            out.append(
                BobaValidationEvidenceRefV1(
                    evidence_ref_id=_safe_text(row.get("evidence_reference_id"), 180) or "unknown",
                    origin="report_reader",
                    source_record_id=_safe_text(row.get("source_record_id"), 180),
                    validation_run_id=_safe_text(row.get("validation_run_id"), 180),
                    report_document_id=document_id,
                    validator_id=_safe_text(row.get("validator_id"), 180),
                    source_type=_safe_text(row.get("evidence_type") or "unknown", 80),
                    artifact_id=_safe_text(row.get("artifact_id"), 180),
                    artifact_digest=validate_projection_digest(
                        row.get("artifact_digest"), label="artifact digest"
                    ),
                    bounded_summary=bounded_projection_text(row.get("bounded_summary"), 1_200),
                    reliability=_safe_text(row.get("reliability") or "unknown", 40),
                    available=available,
                    current=bool(row.get("current", False)),
                    stale=bool(row.get("stale", False)),
                    verifiable=bool(row.get("verifiable", False)),
                    derived_availability_label=(
                        "Available" if available else "Unavailable evidence reference"
                    ),
                )
            )
        return out

    def inspect_evidence(
        self, project_id: str, validation_run_id: str = "", report_document_id: str = ""
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        rows: list[BobaValidationEvidenceRefV1] = []

        if not report_document_id:
            run = self._select_validation_run(project_id, validation_run_id)
            run_id = _safe_text(run.get("validation_run_id"), 180)
            for check_id, records in sorted(
                self._evidence_by_check(project_id, run_id).items() if run_id else []
            ):
                for record in records:
                    supports_pass = bool(record.get("supports_pass", False))
                    supports_failure = bool(record.get("supports_failure", False))
                    if supports_pass and supports_failure:
                        # The owner recorded ambiguous support. Preserve neither
                        # side as a verdict; the disagreement surfaces as a conflict.
                        supports_pass = False
                        supports_failure = False
                    rows.append(
                        BobaValidationEvidenceRefV1(
                            evidence_ref_id=_safe_text(record.get("evidence_id"), 180) or "unknown",
                            origin="validator_runner",
                            source_record_id=_safe_text(record.get("evidence_id"), 180),
                            validation_run_id=run_id,
                            check_run_id=check_id,
                            validator_id=_safe_text(record.get("validator_id"), 180),
                            source_type=_safe_text(record.get("source_type") or "unknown", 80),
                            category=_safe_text(record.get("category") or "unknown", 80),
                            evidence_digest=validate_projection_digest(
                                record.get("evidence_digest"), label="evidence digest"
                            ),
                            bounded_summary=bounded_projection_text(
                                record.get("bounded_summary"), 1_200
                            ),
                            reliability=_safe_text(record.get("reliability") or "unknown", 40),
                            confidence=(
                                float(record["confidence"])
                                if isinstance(record.get("confidence"), int | float)
                                else None
                            ),
                            supports_pass=supports_pass,
                            supports_failure=supports_failure,
                            requires_human_interpretation=bool(
                                record.get("requires_human_interpretation", False)
                            ),
                            verifiable=bool(record.get("evidence_digest")),
                            derived_availability_label="Available",
                        )
                    )
        else:
            wanted = _safe_id(report_document_id, "report document id")
            rows.extend(
                self._report_evidence_refs(
                    self._report_evidence_by_document(project_id).get(wanted, []), wanted
                )
            )

        bounded = rows[:MAX_EVIDENCE_ROWS]
        return {
            "schema_version": "boba_validation_reports_evidence_v1",
            "project_id": project_id,
            "validation_run_id": _safe_text(validation_run_id, 180),
            "report_document_id": _safe_text(report_document_id, 180),
            "evidence": [row.model_dump(mode="json") for row in bounded],
            "total_evidence": len(rows),
            "truncated": len(rows) > MAX_EVIDENCE_ROWS,
            "evidence_available": bool(bounded),
            "notices": [PROJECTION_ONLY_NOTICE, MISSING_EVIDENCE_NOTICE],
        }

    # ------------------------------------------------------------------
    # Conflict identification
    #
    # Conflicts are named and preserved. Nothing here picks a winner, averages
    # values, merges incompatible evidence, infers a root cause or a repair, or
    # concludes anything about workflow completion.
    # ------------------------------------------------------------------
    def _participant(
        self,
        *,
        source_module_id: str,
        record_kind: str,
        record_id: str,
        reported_value: str,
        validator_id: str = "",
        validator_version: str = "",
        reported_at: str = "",
        digest: str = "",
    ) -> BobaValidationConflictParticipantV1:
        return BobaValidationConflictParticipantV1(
            participant_id=_stable_id("vrpart", source_module_id, record_kind, record_id),
            source_module_id=source_module_id,
            record_kind=record_kind,
            record_id=record_id,
            validator_id=validator_id,
            validator_version=validator_version,
            reported_value=_safe_text(reported_value, 240),
            reported_at=_safe_text(reported_at, 80),
            digest=digest,
        )

    def _conflict(
        self,
        *,
        project_id: str,
        kind: ValidationConflictKindV1,
        subject_kind: str,
        subject_id: str,
        summary: str,
        participants: Sequence[BobaValidationConflictParticipantV1],
    ) -> BobaValidationConflictV1 | None:
        distinct = sorted({item.reported_value for item in participants if item.reported_value})
        if len(participants) < 2 or len(distinct) < 2:
            return None
        return BobaValidationConflictV1(
            conflict_id=_stable_id("vrconf", project_id, kind, subject_id, distinct),
            conflict_kind=kind,
            subject_kind=subject_kind,
            subject_id=subject_id,
            bounded_summary=bounded_projection_text(summary),
            participants=list(participants)[:MAX_CONFLICT_PARTICIPANTS],
            distinct_values=distinct[:MAX_CONFLICT_PARTICIPANTS],
        )

    def _check_status_conflicts(
        self, project_id: str, validation_run_id: str
    ) -> list[BobaValidationConflictV1]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._check_rows(project_id, validation_run_id):
            key = _safe_text(row.get("plan_check_id"), 180)
            if key:
                grouped.setdefault(key, []).append(row)

        out: list[BobaValidationConflictV1] = []
        for plan_check_id, rows in sorted(grouped.items()):
            if len(rows) < 2:
                continue
            participants = [
                self._participant(
                    source_module_id="validator_runner",
                    record_kind="check_run",
                    record_id=_safe_text(row.get("check_run_id"), 180),
                    reported_value=_safe_text(row.get("status") or "unknown", 80),
                    validator_id=_safe_text(row.get("validator_id"), 180),
                    validator_version=_safe_text(row.get("validator_version"), 80),
                    reported_at=_safe_text(row.get("completed_at"), 80),
                    digest=validate_projection_digest(
                        row.get("input_digest"), label="input digest"
                    ),
                )
                for row in rows[:MAX_CONFLICT_PARTICIPANTS]
            ]
            conflict = self._conflict(
                project_id=project_id,
                kind="check_status_conflict",
                subject_kind="plan_check",
                subject_id=plan_check_id,
                summary=(
                    f"Plan check {plan_check_id} has check runs reporting different "
                    f"statuses. Both are preserved; neither is selected."
                ),
                participants=participants,
            )
            if conflict is not None:
                out.append(conflict)

            versions = [
                item for item in participants if item.validator_version
            ]
            version_conflict = self._conflict(
                project_id=project_id,
                kind="validator_version_conflict",
                subject_kind="plan_check",
                subject_id=plan_check_id,
                summary=(
                    f"Plan check {plan_check_id} was evaluated under more than one "
                    f"validator version."
                ),
                participants=[
                    self._participant(
                        source_module_id="validator_runner",
                        record_kind="check_run",
                        record_id=item.record_id,
                        reported_value=item.validator_version,
                        validator_id=item.validator_id,
                        validator_version=item.validator_version,
                    )
                    for item in versions
                ],
            )
            if version_conflict is not None:
                out.append(version_conflict)
        return out

    def _result_status_conflicts(
        self, project_id: str, validation_run_id: str
    ) -> list[BobaValidationConflictV1]:
        results = self._results_by_check(project_id, validation_run_id)
        out: list[BobaValidationConflictV1] = []
        for check in self._check_rows(project_id, validation_run_id):
            check_run_id = _safe_text(check.get("check_run_id"), 180)
            result = results.get(check_run_id)
            if not result:
                continue
            check_status = _safe_text(check.get("status") or "unknown", 80)
            result_status = _safe_text(result.get("status") or "unknown", 80)
            if check_status == result_status:
                continue
            conflict = self._conflict(
                project_id=project_id,
                kind="result_status_conflict",
                subject_kind="check_run",
                subject_id=check_run_id,
                summary=(
                    f"Check run {check_run_id} reports '{check_status}' while its "
                    f"recorded result reports '{result_status}'. Both are preserved."
                ),
                participants=[
                    self._participant(
                        source_module_id="validator_runner",
                        record_kind="check_run",
                        record_id=check_run_id,
                        reported_value=check_status,
                        validator_id=_safe_text(check.get("validator_id"), 180),
                    ),
                    self._participant(
                        source_module_id="validator_runner",
                        record_kind="validation_result",
                        record_id=_safe_text(result.get("result_id"), 180),
                        reported_value=result_status,
                        digest=validate_projection_digest(
                            result.get("result_digest"), label="result digest"
                        ),
                    ),
                ],
            )
            if conflict is not None:
                out.append(conflict)
        return out

    def _suite_decision_conflicts(
        self, project_id: str, validation_run_id: str
    ) -> list[BobaValidationConflictV1]:
        rows = [
            row
            for row in self._rows(project_id, "validator_runner", "suite_decisions")
            if _safe_text(row.get("validation_run_id"), 180) == validation_run_id
        ]
        if len(rows) < 2:
            return []
        conflict = self._conflict(
            project_id=project_id,
            kind="suite_decision_conflict",
            subject_kind="validation_run",
            subject_id=validation_run_id,
            summary=(
                f"Validation run {validation_run_id} has more than one suite decision. "
                f"All are preserved; none is treated as final."
            ),
            participants=[
                self._participant(
                    source_module_id="validator_runner",
                    record_kind="suite_decision",
                    record_id=_safe_text(row.get("suite_decision_id"), 180),
                    reported_value=_safe_text(row.get("decision") or "unknown", 80),
                )
                for row in rows[:MAX_CONFLICT_PARTICIPANTS]
            ],
        )
        return [conflict] if conflict is not None else []

    def _report_conflicts(self, project_id: str) -> list[BobaValidationConflictV1]:
        out: list[BobaValidationConflictV1] = []
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for document in self._report_documents(project_id):
            key = (
                _safe_text(document.get("producer_module_id") or "unknown", 160),
                _safe_text(document.get("report_type") or "unknown", 80),
            )
            grouped.setdefault(key, []).append(document)

        for (producer, report_type), documents in sorted(grouped.items()):
            if len(documents) >= 2:
                conflict = self._conflict(
                    project_id=project_id,
                    kind="report_status_conflict",
                    subject_kind="report_type",
                    subject_id=f"{producer}:{report_type}",
                    summary=(
                        f"{producer} produced more than one {report_type} report with "
                        f"differing read statuses. All are preserved."
                    ),
                    participants=[
                        self._participant(
                            source_module_id="report_reader",
                            record_kind="report_document",
                            record_id=_safe_text(row.get("report_document_id"), 180),
                            reported_value=_safe_text(row.get("read_status") or "unknown", 80),
                            digest=validate_projection_digest(
                                row.get("content_digest"), label="content digest"
                            ),
                        )
                        for row in documents[:MAX_CONFLICT_PARTICIPANTS]
                    ],
                )
                if conflict is not None:
                    out.append(conflict)

            for row in documents:
                if row.get("expected_digest_match", True):
                    continue
                document_id = _safe_text(row.get("report_document_id"), 180)
                reference = self._reference_index(project_id).get(
                    _safe_text(row.get("report_reference_id"), 180), {}
                )
                conflict = self._conflict(
                    project_id=project_id,
                    kind="report_digest_conflict",
                    subject_kind="report_document",
                    subject_id=document_id,
                    summary=(
                        f"Report {document_id} does not match the digest its reference "
                        f"declared. The mismatch is reported, not resolved."
                    ),
                    participants=[
                        self._participant(
                            source_module_id="report_reader",
                            record_kind="report_document",
                            record_id=document_id,
                            reported_value=validate_projection_digest(
                                row.get("content_digest"), label="content digest"
                            )
                            or "absent",
                        ),
                        self._participant(
                            source_module_id="report_reader",
                            record_kind="report_reference",
                            record_id=_safe_text(row.get("report_reference_id"), 180),
                            reported_value=validate_projection_digest(
                                reference.get("expected_digest"), label="expected digest"
                            )
                            or "absent",
                        ),
                    ],
                )
                if conflict is not None:
                    out.append(conflict)

        for row in self._rows(project_id, "report_reader", "contradictions"):
            summary = bounded_projection_text(
                row.get("bounded_summary") or row.get("contradiction_type")
            )
            participants = [
                self._participant(
                    source_module_id="report_reader",
                    record_kind="report_document",
                    record_id=item,
                    reported_value=_safe_text(row.get("contradiction_type") or "unknown", 80)
                    + f":{item}",
                )
                for item in _bounded_ids(row.get("report_document_ids"), 4)
            ]
            conflict = self._conflict(
                project_id=project_id,
                kind="reported_contradiction",
                subject_kind="report_contradiction",
                subject_id=_safe_text(row.get("contradiction_id"), 180),
                summary=summary
                or "The Report Reader recorded a contradiction between reports.",
                participants=participants,
            )
            if conflict is not None:
                out.append(conflict)
        return out

    def inspect_conflicts(self, project_id: str, validation_run_id: str = "") -> dict[str, Any]:
        _safe_id(project_id, "project id")
        run = self._select_validation_run(project_id, validation_run_id)
        run_id = _safe_text(run.get("validation_run_id"), 180)
        conflicts = (
            self._check_status_conflicts(project_id, run_id)
            + self._result_status_conflicts(project_id, run_id)
            + self._suite_decision_conflicts(project_id, run_id)
            if run_id
            else []
        ) + self._report_conflicts(project_id)
        ordered = sorted(conflicts, key=lambda item: (item.conflict_kind, item.conflict_id))
        bounded = ordered[:MAX_CONFLICT_ROWS]
        return {
            "schema_version": "boba_validation_reports_conflicts_v1",
            "project_id": project_id,
            "validation_run_id": run_id,
            "conflicts": [item.model_dump(mode="json") for item in bounded],
            "total_conflicts": len(ordered),
            "truncated": len(ordered) > MAX_CONFLICT_ROWS,
            "conflicts_present": bool(bounded),
            "notices": [CONFLICT_NOTICE, PROJECTION_ONLY_NOTICE],
        }

    # ------------------------------------------------------------------
    # Own append-only event log. This does not mirror an owner event stream.
    # ------------------------------------------------------------------
    def _emit(
        self,
        project_id: str,
        event_type: ValidationReportsEventTypeV1,
        summary: str,
        *,
        validation_run_id: str = "",
        binding_digest: str = "",
    ) -> BobaValidationReportsEventV1:
        existing = self.store.load_boba_validation_reports_events(project_id)
        sequence = len(existing) + 1
        event = BobaValidationReportsEventV1(
            event_id=_stable_id("vrevent", project_id, sequence, event_type),
            sequence=sequence,
            event_type=event_type,
            project_id=project_id,
            validation_run_id=validation_run_id,
            bounded_summary=bounded_projection_text(summary),
            binding_digest=binding_digest,
            event_digest=_digest(
                {
                    "project_id": project_id,
                    "sequence": sequence,
                    "event_type": event_type,
                    "summary": summary,
                }
            ),
        )
        self.store.append_boba_validation_reports_event(
            project_id, event.model_dump(mode="json")
        )
        return event

    def inspect_validation_report_events(
        self, project_id: str, *, after_sequence: int = 0, limit: int = MAX_EVENTS
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        if after_sequence < 0:
            raise ValidationError("An event sequence cursor cannot be negative.")
        bounded_limit = max(1, min(int(limit), MAX_EVENTS))
        rows = self.store.load_boba_validation_reports_events(project_id)
        selected = [
            row
            for row in rows
            if isinstance(row.get("sequence"), int) and row["sequence"] > after_sequence
        ]
        selected.sort(key=lambda row: (int(row.get("sequence") or 0), str(row.get("event_id"))))
        page = selected[:bounded_limit]
        return {
            "schema_version": "boba_validation_reports_events_v1",
            "project_id": project_id,
            "events": page,
            "returned": len(page),
            "total_available": len(selected),
            "next_cursor": int(page[-1]["sequence"]) if page else after_sequence,
            "has_more": len(selected) > len(page),
            "append_only": True,
            "duplicates_owner_event_stream": False,
            "notices": [PROJECTION_ONLY_NOTICE],
        }

    # ------------------------------------------------------------------
    # Request metadata and idempotency, both genuinely owned here
    # ------------------------------------------------------------------
    def create_projection_request(
        self,
        project_id: str,
        *,
        requested_scope: str = "full",
        validation_run_id: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        scope = _safe_text(requested_scope or "full", 80)
        if scope not in {"full", "summary", "matrix", "reports", "evidence", "conflicts"}:
            raise ValidationError("Unknown BOBA validation projection scope.")
        key = _safe_text(idempotency_key, 180)
        run = self._select_validation_run(project_id, validation_run_id)
        binding = self._binding(project_id, run)
        digest = _digest(
            {
                "project_id": project_id,
                "scope": scope,
                "validation_run_id": _safe_text(run.get("validation_run_id"), 180),
                "binding_digest": binding.binding_digest,
                "idempotency_key": key,
            }
        )
        request_id = _stable_id("vrreq", project_id, digest)
        existing = self.store.load_boba_validation_reports_request(project_id, request_id)
        request = BobaValidationReportsRequestV1(
            request_id=request_id,
            project_id=project_id,
            requested_scope=scope,
            validation_run_id=_safe_text(run.get("validation_run_id"), 180),
            idempotency_key=key,
            request_digest=digest,
            binding_digest=binding.binding_digest,
            reused_existing_projection=existing is not None,
        )
        payload = request.model_dump(mode="json")
        if existing is None:
            self.store.save_boba_validation_reports_request(project_id, request_id, payload)
        else:
            payload = {**existing, "reused_existing_projection": True}
        self._emit(
            project_id,
            "projection_requested",
            f"A {scope} validation projection was requested.",
            validation_run_id=request.validation_run_id,
            binding_digest=binding.binding_digest,
        )
        return payload

    # ------------------------------------------------------------------
    # Full projection
    # ------------------------------------------------------------------
    def build_validation_reports(
        self, project_id: str, validation_run_id: str = ""
    ) -> dict[str, Any]:
        _safe_id(project_id, "project id")
        registry = self.build_validation_reports_registry(project_id)
        run = self._select_validation_run(project_id, validation_run_id)
        run_id = _safe_text(run.get("validation_run_id"), 180)
        binding = self._binding(project_id, run)

        summary_payload = self.build_validation_summary(project_id, run_id)
        matrix_payload = self.build_validation_matrix(project_id, run_id)
        reports_payload = self.inspect_reports(project_id)
        evidence_payload = self.inspect_evidence(project_id, run_id)
        conflicts_payload = self.inspect_conflicts(project_id, run_id)

        summary = BobaValidationSummaryV1.model_validate(summary_payload)
        matrix = BobaValidationMatrixV1.model_validate(matrix_payload)
        cards = [
            BobaValidationReportCardV1.model_validate(row)
            for row in _bounded_rows(reports_payload.get("report_cards"), MAX_REPORT_CARDS)
        ]
        evidence = [
            BobaValidationEvidenceRefV1.model_validate(row)
            for row in _bounded_rows(evidence_payload.get("evidence"), MAX_EVIDENCE_ROWS)
        ]
        conflicts = [
            BobaValidationConflictV1.model_validate(row)
            for row in _bounded_rows(conflicts_payload.get("conflicts"), MAX_CONFLICT_ROWS)
        ]
        matrix = matrix.model_copy(update={"any_conflict": bool(conflicts)})

        if summary.evidence_missing:
            headline = "Validation evidence is incomplete."
        elif summary.stale:
            headline = "Validation exists but is stale."
        elif conflicts:
            headline = "Validation evidence contains unresolved conflicts."
        else:
            headline = summary.derived_status_title

        overview = BobaValidationReportsOverviewV1(
            overview_id=_stable_id("vrover", project_id, run_id, binding.binding_digest),
            validation_available=bool(run),
            reports_available=bool(cards),
            matrix_cell_count=len(matrix.cells),
            report_card_count=len(cards),
            conflict_count=len(conflicts),
            evidence_count=len(evidence),
            state_counts=matrix.state_counts,
            stale=summary.stale,
            evidence_missing=summary.evidence_missing,
            derived_headline=bounded_projection_text(headline, 240),
        )

        result = BobaValidationReportsSetV1(
            project_id=project_id,
            registry_snapshot=BobaValidationReportsRegistrySnapshotV1.model_validate(
                registry["registry_snapshot"]
            ),
            binding=binding,
            summary=summary,
            matrix=matrix,
            report_cards=cards,
            evidence=evidence,
            conflicts=conflicts,
            overview=overview,
            signal_usage=self._signal_usage(project_id),
            notices=[
                PROJECTION_ONLY_NOTICE,
                NOT_PRODUCTION_READY_NOTICE,
                MISSING_EVIDENCE_NOTICE,
                CONFLICT_NOTICE,
                REPORT_BODY_NOTICE,
            ],
            warnings=summary.warnings[:MAX_WARNINGS],
        )
        payload = result.model_dump(mode="json")
        payload["projection_digest"] = projection_content_digest(payload)
        self.store.save_boba_validation_reports(project_id, payload)

        if not run:
            self._emit(project_id, "projection_empty", "No validation run exists to project.")
        else:
            self._emit(
                project_id,
                "matrix_projected",
                f"Projected {len(matrix.cells)} validation check(s).",
                validation_run_id=run_id,
                binding_digest=binding.binding_digest,
            )
        if cards:
            self._emit(
                project_id,
                "reports_projected",
                f"Projected {len(cards)} report(s) from the Report Reader.",
                validation_run_id=run_id,
            )
        if summary.evidence_missing:
            self._emit(
                project_id,
                "evidence_missing",
                "Validation evidence is missing; no pass is claimed.",
                validation_run_id=run_id,
            )
        if binding.invalidated_dimensions:
            self._emit(
                project_id,
                "stale_binding_detected",
                f"Binding invalidated: {', '.join(binding.invalidated_dimensions)}.",
                validation_run_id=run_id,
                binding_digest=binding.binding_digest,
            )
        for conflict in conflicts[:8]:
            self._emit(
                project_id,
                "conflict_detected",
                f"{conflict.conflict_kind} on {conflict.subject_id}.",
                validation_run_id=run_id,
            )
        for card in cards:
            if card.malformed:
                self._emit(
                    project_id,
                    "report_malformed",
                    f"Report {card.report_document_id} is malformed.",
                )
            if not card.expected_digest_match:
                self._emit(
                    project_id,
                    "digest_mismatch",
                    f"Report {card.report_document_id} failed its digest check.",
                )
        return payload

    def load_validation_reports(self, project_id: str) -> dict[str, Any] | None:
        _safe_id(project_id, "project id")
        payload = self.store.load_boba_validation_reports(project_id)
        return payload if isinstance(payload, dict) else None

    def export_validation_reports(self, project_id: str) -> dict[str, Any]:
        """Export bounded, redacted metadata. Never report bodies or raw paths."""
        _safe_id(project_id, "project id")
        payload = self.load_validation_reports(project_id)
        if payload is None:
            payload = self.build_validation_reports(project_id)
        sanitized = sanitize_validation_reports_export(payload)
        if not isinstance(sanitized, dict):
            raise ValidationError(
                "The BOBA validation export sanitiser returned an invalid payload."
            )
        return {
            "schema_version": "boba_validation_reports_export_v1",
            "project_id": project_id,
            "projection": sanitized,
            "report_bodies_included": False,
            "raw_paths_included": False,
            "commands_included": False,
            "secrets_included": False,
            "media_included": False,
            "notices": [PROJECTION_ONLY_NOTICE, REPORT_BODY_NOTICE],
        }

    def reset_validation_report_metadata(self, project_id: str) -> dict[str, Any]:
        """Remove only this module's projection metadata. Owners are untouched."""
        _safe_id(project_id, "project id")
        result: dict[str, Any] = dict(
            self.store.reset_boba_validation_reports_metadata(project_id)
        )
        self._emit(
            project_id,
            "metadata_reset",
            "Validation + Reports projection metadata was reset; owner history is preserved.",
        )
        return result
