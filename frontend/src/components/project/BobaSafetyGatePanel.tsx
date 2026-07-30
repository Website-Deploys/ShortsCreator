"use client";

import { useState } from "react";

import {
  useBobaSafetyGate,
  useCreateBobaSafetyPolicy,
  useEvaluateBobaSafetyRequest,
  useExportBobaSafetyGate,
  useInvalidateBobaSafetyDecision,
  useRecordBobaSafetyHumanReview,
  useResetBobaSafetyGate,
  useRevalidateBobaSafetyDecision,
} from "@/lib/queries";

function words(value: string | undefined) {
  return value ? value.replace(/_/g, " ") : "Not available";
}

function shortDigest(value: string | undefined) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "Not available";
}

function yesNo(value: boolean | undefined) {
  return value === undefined ? "Not available" : value ? "Yes" : "No";
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function statusTone(value: string | undefined) {
  if (
    value?.startsWith("allowed") ||
    value === "passed" ||
    value === "completed"
  ) {
    return "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-100";
  }
  if (
    value === "human_review_required" ||
    value === "more_evidence_required" ||
    value === "awaiting_human_review" ||
    value === "awaiting_evidence"
  ) {
    return "border-amber-300/30 bg-amber-300/[0.06] text-amber-100";
  }
  if (
    value?.startsWith("blocked") ||
    value === "denied" ||
    value === "failed" ||
    value === "expired" ||
    value === "invalidated"
  ) {
    return "border-rose-300/30 bg-rose-300/[0.06] text-rose-100";
  }
  return "border-white/10 bg-white/[0.03] text-muted";
}

function parseApproval(value: string): Record<string, unknown> | undefined {
  if (!value.trim()) return undefined;
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Approval must be one JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function BobaSafetyGatePanel({ projectId }: { projectId: string }) {
  const gateQuery = useBobaSafetyGate(projectId);
  const createPolicy = useCreateBobaSafetyPolicy(projectId);
  const evaluate = useEvaluateBobaSafetyRequest(projectId);
  const revalidate = useRevalidateBobaSafetyDecision(projectId);
  const invalidate = useInvalidateBobaSafetyDecision(projectId);
  const humanReview = useRecordBobaSafetyHumanReview(projectId);
  const exportGate = useExportBobaSafetyGate(projectId);
  const resetGate = useResetBobaSafetyGate(projectId);
  const [approvalJson, setApprovalJson] = useState("");
  const [reviewerIdentity, setReviewerIdentity] = useState("local_operator");
  const [reviewReason, setReviewReason] = useState("");
  const [status, setStatus] = useState("");

  const gate = gateQuery.data;
  const evaluation = gate?.evaluation_cases.at(-1);
  const request =
    gate?.action_requests.find(
      (item) => item.action_request_id === evaluation?.action_request_id,
    ) ?? gate?.action_requests.at(-1);
  const decision =
    gate?.safety_decisions.find(
      (item) => item.safety_decision_id === evaluation?.safety_decision_id,
    ) ?? gate?.safety_decisions.at(-1);
  const approval = gate?.approval_reviews.find(
    (item) => item.approval_review_id === evaluation?.approval_review_id,
  );
  const rights = gate?.rights_reviews.find(
    (item) => item.rights_review_id === evaluation?.rights_review_id,
  );
  const checkpoint = gate?.checkpoint_reviews.find(
    (item) => item.checkpoint_review_id === evaluation?.checkpoint_review_id,
  );
  const validation = gate?.validation_reviews.find(
    (item) => item.validation_review_id === evaluation?.validation_review_id,
  );
  const quality = gate?.quality_reviews.find(
    (item) => item.quality_review_id === evaluation?.quality_review_id,
  );
  const risk = gate?.risk_assessments.find(
    (item) => item.risk_assessment_id === evaluation?.risk_assessment_id,
  );
  const checks =
    gate?.constraint_checks.filter(
      (item) => item.safety_case_id === evaluation?.safety_case_id,
    ) ?? [];
  const handoff = gate?.handoffs
    .filter((item) => item.safety_case_id === evaluation?.safety_case_id)
    .at(-1);
  const invalidation = gate?.decision_invalidations
    .filter((item) => item.safety_decision_id === decision?.safety_decision_id)
    .at(-1);
  const passedChecks = checks.filter((item) => item.status === "passed");
  const failedChecks = checks.filter((item) =>
    ["failed", "blocked", "stale", "conflicting"].includes(item.status),
  );
  const unavailableChecks = checks.filter((item) =>
    ["unavailable", "unknown"].includes(item.status),
  );
  const busy = [
    createPolicy,
    evaluate,
    revalidate,
    invalidate,
    humanReview,
    exportGate,
    resetGate,
  ].some((mutation) => mutation.isPending);

  function approvalRecord() {
    try {
      return parseApproval(approvalJson);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Approval JSON is invalid.");
      return null;
    }
  }

  function evaluateExactAction() {
    if (!request) return;
    const parsed = approvalRecord();
    if (parsed === null) return;
    setStatus("");
    evaluate.mutate(
      {
        actionRequestId: request.action_request_id,
        approvalRecord: parsed,
      },
      {
        onSuccess: (result) =>
          setStatus(
            `Safety evaluation recorded: ${words(result.decision)}. Nothing was executed.`,
          ),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function revalidateDecision() {
    if (!decision) return;
    const parsed = approvalRecord();
    if (parsed === null) return;
    setStatus("");
    revalidate.mutate(
      {
        decisionId: decision.safety_decision_id,
        approvalRecord: parsed,
      },
      {
        onSuccess: (result) =>
          setStatus(`Revalidation result: ${words(result.decision)}.`),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function invalidateDecision() {
    if (!decision) return;
    const reason =
      reviewReason.trim() ||
      window.prompt("Why is this exact Safety Gate decision invalid now?")?.trim();
    if (!reason) return;
    invalidate.mutate(
      { decisionId: decision.safety_decision_id, reason },
      {
        onSuccess: () => setStatus("Exact Safety Gate decision invalidated."),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function recordReview(decisionValue: "deny_action" | "request_more_evidence") {
    if (!evaluation || !request) return;
    if (!reviewerIdentity.trim() || !reviewReason.trim()) {
      setStatus("Reviewer identity and a bounded reason are required.");
      return;
    }
    humanReview.mutate(
      {
        caseId: evaluation.safety_case_id,
        input: {
          decision: decisionValue,
          reason: reviewReason.trim(),
          reviewer_identity: reviewerIdentity.trim(),
          request_digest: request.request_digest,
          project_snapshot_digest: request.project_snapshot_digest,
        },
      },
      {
        onSuccess: () =>
          setStatus("Bounded human safety review recorded. Nothing was executed."),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportGate.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-safety-gate-v1-${projectId}.json`, payload);
        setStatus("Sanitized Safety Gate export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function resetMetadata() {
    if (
      !window.confirm(
        "Remove active Safety Gate summary metadata? Immutable policy and decision history, approvals, Autopilot history, media, and outputs remain.",
      )
    ) {
      return;
    }
    resetGate.mutate(undefined, {
      onSuccess: () =>
        setStatus("Active Safety Gate summary removed; immutable history remains."),
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">BOBA Safety Gate V1</p>
          <p className="text-xs text-cyan-100">
            Safety Gate evaluates an action but does not execute it.
          </p>
          <p className="text-xs text-muted">
            An allow decision applies only to the exact displayed project state,
            plan, strategy, tool or patch. Changing the action invalidates the
            decision.
          </p>
          <p className="text-xs text-muted">
            Target modules must independently verify approval and safety again.
          </p>
          <p className="text-xs text-amber-100">
            Safety Gate V1 does not authorize workflow resume, upload,
            publication, merge or deployment. It also does not authorize pushes.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!gate && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                createPolicy.mutate(
                  {},
                  {
                    onSuccess: () =>
                      setStatus("Safety policy created. No action was executed."),
                    onError: (error) => setStatus(error.message),
                  },
                )
              }
              className="rounded border border-cyan-200/30 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
            >
              Create policy snapshot
            </button>
          )}
          <button
            type="button"
            disabled={busy || !gate}
            onClick={exportArtifact}
            className="rounded border border-cyan-200/30 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
          >
            Export safe record
          </button>
          <button
            type="button"
            disabled={busy || !gate}
            onClick={resetMetadata}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset active metadata
          </button>
        </div>
      </div>

      {gateQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Safety Gate state could not be loaded.
        </p>
      )}
      {!gate && !gateQuery.isLoading && (
        <p className="mt-3 text-xs text-muted">
          No Safety Gate policy or evaluation exists for this project.
        </p>
      )}

      {gate && (
        <>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
            <span className={`rounded border px-2 py-1 ${statusTone(evaluation?.evaluation_status)}`}>
              Evaluation: {words(evaluation?.evaluation_status)}
            </span>
            <span className={`rounded border px-2 py-1 ${statusTone(decision?.decision)}`}>
              Decision: {words(decision?.decision)}
            </span>
            <span className={`rounded border px-2 py-1 ${statusTone(risk?.overall_risk_level)}`}>
              Risk: {words(risk?.overall_risk_level)}
              {risk ? ` (${risk.overall_risk_score.toFixed(1)})` : ""}
            </span>
            <span className="rounded border border-white/10 px-2 py-1 text-muted">
              Policy: {gate.policy_snapshot.policy_version}
            </span>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                ACTION REQUEST
              </p>
              <p className="mt-2 text-white">
                {request?.action_description ?? "Not available"}
              </p>
              <p>
                Requesting module: {words(request?.requesting_module)}
              </p>
              <p>
                Target: {words(request?.target_module)} ·{" "}
                {words(request?.target_operation)}
              </p>
              <p>Class: {words(request?.action_class)}</p>
              <p>Project snapshot: {request?.project_snapshot_id || "Not available"}</p>
              <p>Request digest: {shortDigest(request?.request_digest)}</p>
              <p>Policy digest: {shortDigest(gate.policy_snapshot.policy_sha256)}</p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                RIGHTS AND PERMISSIONS
              </p>
              <p className="mt-2">Rights: {words(rights?.rights_status)}</p>
              <p>Permission: {words(rights?.permission_status)}</p>
              <p>Provenance: {words(rights?.source_provenance_status)}</p>
              <p>
                Internal action clear:{" "}
                {yesNo(rights?.rights_clear_for_requested_internal_action)}
              </p>
              <p>Upload allowed: {yesNo(rights?.upload_allowed)}</p>
              <p>Publication allowed: {yesNo(rights?.publication_allowed)}</p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                EXACT APPROVAL
              </p>
              <p className="mt-2">
                Approval: {approval?.approval_found ? "Found" : "Not found"}
              </p>
              <p>Explicit: {yesNo(approval?.explicit_confirmation)}</p>
              <p>Current: {approval?.expired ? "Expired" : "Not expired"}</p>
              <p>Scope match: {yesNo(approval?.scope_match)}</p>
              <p>Plan/settings match: {yesNo(approval?.parameters_match)}</p>
              <p>Snapshot match: {yesNo(approval?.snapshot_match)}</p>
              <p>Exact binding: {yesNo(approval?.exact_binding_valid)}</p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                CHECKPOINT AND ROLLBACK
              </p>
              <p className="mt-2">
                Checkpoint: {words(checkpoint?.checkpoint_status)}
              </p>
              <p>Validated: {yesNo(checkpoint?.checkpoint_validated)}</p>
              <p>Fresh: {yesNo(checkpoint?.checkpoint_fresh)}</p>
              <p>Rollback ready: {yesNo(checkpoint?.rollback_ready)}</p>
              <p>Source media protected: {yesNo(checkpoint?.source_media_protected)}</p>
              <p>
                Accepted outputs protected:{" "}
                {yesNo(checkpoint?.accepted_outputs_protected)}
              </p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                VALIDATION
              </p>
              <p className="mt-2">Ready: {yesNo(validation?.validation_ready)}</p>
              <p>
                Defined: {yesNo(validation?.required_checks_defined)} · Available:{" "}
                {yesNo(validation?.required_checks_available)}
              </p>
              <p>
                Validators:{" "}
                {validation?.required_validators.join(", ") || "Not available"}
              </p>
              <p>
                Unavailable:{" "}
                {validation?.unavailable_validators.join(", ") || "None"}
              </p>
              <p>
                Skipped: {validation?.skipped_required_checks.join(", ") || "None"}
              </p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                QUALITY
              </p>
              <p className="mt-2">
                Ready: {yesNo(quality?.quality_clear_for_requested_action)}
              </p>
              <p>Baseline available: {yesNo(quality?.baseline_available)}</p>
              <p>
                Requirements match:{" "}
                {yesNo(quality?.quality_requirements_match_request)}
              </p>
              <p>
                Silent reduction:{" "}
                {yesNo(quality?.silent_quality_reduction_detected)}
              </p>
              <p>
                Human review required:{" "}
                {yesNo(quality?.human_quality_review_required)}
              </p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                RISK
              </p>
              <p className="mt-2">
                Overall: {words(risk?.overall_risk_level)} ·{" "}
                {risk?.overall_risk_score.toFixed(1) ?? "Not available"} /{" "}
                {risk?.risk_threshold.toFixed(1) ?? "?"}
              </p>
              <p>Within threshold: {yesNo(risk?.risk_within_threshold)}</p>
              {risk?.risk_factors.slice(0, 6).map((factor) => (
                <p
                  key={factor.risk_factor_id}
                  className={factor.blocking ? "text-rose-100" : ""}
                >
                  {words(factor.category)}: {factor.title}
                </p>
              ))}
              <p className="mt-2">
                Checks: {passedChecks.length} passed · {failedChecks.length} failed ·{" "}
                {unavailableChecks.length} unavailable
              </p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                SAFETY DECISION
              </p>
              <p className="mt-2 text-white">
                {decision?.decision_summary ?? "Not available"}
              </p>
              <p>Decision ID: {decision?.safety_decision_id || "Not available"}</p>
              <p>Expires: {decision?.decision_expires_at || "Not available"}</p>
              <p>Valid: {yesNo(decision?.decision_valid)}</p>
              <p>
                Target revalidation required:{" "}
                {yesNo(decision?.target_module_revalidation_required)}
              </p>
              {invalidation && (
                <p className="text-rose-100">
                  Invalidated: {invalidation.invalidation_reason}
                </p>
              )}
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                HUMAN REVIEW
              </p>
              <p className="mt-2">
                Required: {yesNo(evaluation?.human_review_required)}
              </p>
              <p>
                Unmet conditions:{" "}
                {decision?.unmet_conditions.join("; ") || "None recorded"}
              </p>
              <p>
                Denial reasons:{" "}
                {decision?.denial_reasons.join("; ") || "None recorded"}
              </p>
            </div>

            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                WHAT HAPPENS NEXT
              </p>
              <p className="mt-2">
                {handoff
                  ? `${words(handoff.target_module)}: ${handoff.reason}`
                  : "No handoff is recorded."}
              </p>
              <p>
                Automatic execution: {handoff?.apply_automatically ? "Yes" : "No"}
              </p>
              <p>
                Prohibited:{" "}
                {handoff?.prohibited_actions.slice(0, 8).join(", ") ||
                  gate.policy_snapshot.prohibited_actions.slice(0, 8).join(", ")}
              </p>
            </div>
          </div>

          {request && (
            <details className="mt-4 rounded border border-cyan-300/20 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-cyan-100">
                Evaluate or revalidate this exact action
              </summary>
              <p className="mt-2 text-xs text-muted">
                Paste the exact target-module approval only when this action
                requires it. Safety Gate stores a bounded review and digest, not
                the raw approval.
              </p>
              <textarea
                value={approvalJson}
                onChange={(event) => setApprovalJson(event.target.value)}
                rows={5}
                placeholder="Optional exact approval JSON"
                className="mt-2 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-xs text-white"
              />
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={evaluateExactAction}
                  className="rounded border border-cyan-200/30 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50"
                >
                  Evaluate exact action
                </button>
                <button
                  type="button"
                  disabled={busy || !decision}
                  onClick={revalidateDecision}
                  className="rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
                >
                  Revalidate decision
                </button>
                <button
                  type="button"
                  disabled={busy || !decision}
                  onClick={invalidateDecision}
                  className="rounded border border-rose-300/30 px-3 py-2 text-xs text-rose-100 disabled:opacity-50"
                >
                  Invalidate decision
                </button>
              </div>
            </details>
          )}

          {evaluation && request && (
            <details className="mt-4 rounded border border-white/10 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-white">
                Record bounded human safety review
              </summary>
              <p className="mt-2 text-xs text-muted">
                I reviewed this exact action, project snapshot, request digest,
                risks, checkpoint, rollback plan, validation plan and quality
                requirements.
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <input
                  value={reviewerIdentity}
                  onChange={(event) => setReviewerIdentity(event.target.value)}
                  placeholder="Reviewer identity"
                  className="rounded border border-white/10 bg-black/30 px-2.5 py-2 text-xs text-white"
                />
                <input
                  value={reviewReason}
                  onChange={(event) => setReviewReason(event.target.value)}
                  placeholder="Bounded review reason"
                  className="rounded border border-white/10 bg-black/30 px-2.5 py-2 text-xs text-white"
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => recordReview("request_more_evidence")}
                  className="rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
                >
                  Request more evidence
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => recordReview("deny_action")}
                  className="rounded border border-rose-300/30 px-3 py-2 text-xs text-rose-100 disabled:opacity-50"
                >
                  Deny action
                </button>
              </div>
            </details>
          )}

          <details className="mt-4 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Passed, failed, and unavailable checks
            </summary>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              {[
                ["Passed", passedChecks],
                ["Failed", failedChecks],
                ["Unavailable", unavailableChecks],
              ].map(([label, items]) => (
                <div key={String(label)} className="rounded border border-white/10 p-2">
                  <p className="font-semibold text-white">{String(label)}</p>
                  {(items as typeof checks).slice(0, 20).map((item) => (
                    <p key={item.constraint_check_id}>
                      {item.name}: {words(item.status)}
                    </p>
                  ))}
                  {(items as typeof checks).length === 0 && <p>None</p>}
                </div>
              ))}
            </div>
          </details>
        </>
      )}

      {status && <p className="mt-3 text-xs text-cyan-100">{status}</p>}
    </section>
  );
}
