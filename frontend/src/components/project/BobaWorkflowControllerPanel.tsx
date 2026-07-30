"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  useAdvanceBobaWorkflowSafe,
  useBobaWorkflowController,
  useCancelBobaWorkflow,
  useContinueBobaWorkflowController,
  useCoordinateBobaWorkflowApproved,
  useCreateBobaWorkflowRecoveryHold,
  useCreateBobaWorkflowRun,
  useCreateBobaWorkflowTransition,
  useEvaluateBobaWorkflowResumeEligibility,
  useEvaluateBobaWorkflowTransition,
  useExportBobaWorkflowController,
  usePauseBobaWorkflow,
  usePlanBobaWorkflowNext,
  useRecordBobaWorkflowHumanDecision,
  useResetBobaWorkflowController,
} from "@/lib/queries";
import type {
  BobaWorkflowNextStagePlanV1,
  BobaWorkflowStageInstanceV1,
} from "@/lib/types";

function words(value: string | null | undefined): string {
  return value ? value.replace(/_/g, " ") : "Not available";
}

function short(value: string | null | undefined): string {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "Not available";
}

function statusTone(value: string | null | undefined): string {
  const status = (value ?? "").toLowerCase();
  if (
    status.includes("complete") ||
    status.includes("allowed") ||
    status === "ready" ||
    status === "active" ||
    status === "released"
  ) {
    return "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-100";
  }
  if (
    status.includes("fail") ||
    status.includes("blocked") ||
    status.includes("denied") ||
    status.includes("cancel") ||
    status.includes("stale")
  ) {
    return "border-rose-300/30 bg-rose-300/[0.06] text-rose-100";
  }
  if (
    status.includes("pause") ||
    status.includes("await") ||
    status.includes("recovery") ||
    status.includes("review")
  ) {
    return "border-amber-300/30 bg-amber-300/[0.06] text-amber-100";
  }
  return "border-white/10 bg-white/[0.03] text-muted";
}

function parseObject(
  label: string,
  value: string,
): Record<string, unknown> | undefined {
  if (!value.trim()) return undefined;
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be one JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function stringField(
  value: Record<string, unknown> | undefined,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const item = value?.[key];
    if (typeof item === "string" && item) return item;
  }
  return undefined;
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

function Section({
  title,
  children,
  open = false,
}: {
  title: string;
  children: ReactNode;
  open?: boolean;
}) {
  return (
    <details
      className="rounded-xl border border-white/10 bg-black/10 p-3"
      open={open}
    >
      <summary className="cursor-pointer text-xs font-semibold tracking-[0.16em] text-white">
        {title}
      </summary>
      <div className="mt-3 space-y-2 text-xs text-muted">{children}</div>
    </details>
  );
}

function StatusBadge({ value }: { value: string | null | undefined }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-1 text-[10px] ${statusTone(value)}`}
    >
      {words(value)}
    </span>
  );
}

function KeyValue({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/5 py-1 last:border-0">
      <span>{label}</span>
      <span className="max-w-[65%] break-words text-right text-white">
        {value ?? "Not available"}
      </span>
    </div>
  );
}

function StageList({
  stages,
  empty,
}: {
  stages: BobaWorkflowStageInstanceV1[];
  empty: string;
}) {
  if (!stages.length) return <p>{empty}</p>;
  return (
    <div className="space-y-2">
      {stages.map((stage) => (
        <div
          className="rounded-lg border border-white/10 bg-white/[0.02] p-2"
          key={stage.stage_instance_id}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium text-white">{words(stage.stage_id)}</span>
            <StatusBadge value={stage.status} />
          </div>
          <p className="mt-1">
            {stage.clip_id ? `Clip ${stage.clip_id}` : "Project stage"}
            {stage.output_id ? ` · Output ${stage.output_id}` : ""}
          </p>
          {stage.failure_summary && (
            <p className="mt-1 text-rose-100">{stage.failure_summary}</p>
          )}
        </div>
      ))}
    </div>
  );
}

export function BobaWorkflowControllerPanel({
  projectId,
  clipIds = [],
  outputIdsByClip = {},
}: {
  projectId: string;
  clipIds?: string[];
  outputIdsByClip?: Record<string, string>;
}) {
  const controllerQuery = useBobaWorkflowController(projectId);
  const controller = controllerQuery.data;
  const currentRun =
    controller?.workflow_runs.find(
      (item) =>
        item.workflow_run_id ===
        controller.controller_summary.current_workflow_run_id,
    ) ?? controller?.workflow_runs.at(-1);
  const runId = currentRun?.workflow_run_id ?? "";
  const runStages = useMemo(
    () =>
      controller?.stage_instances.filter(
        (stage) => stage.workflow_run_id === runId,
      ) ?? [],
    [controller?.stage_instances, runId],
  );
  const currentStage =
    runStages.find((stage) =>
      currentRun?.current_stage_instance_ids.includes(stage.stage_instance_id),
    ) ?? runStages.find((stage) => stage.status === "ready");
  const currentRequest =
    controller?.transition_requests.find(
      (item) =>
        item.transition_request_id === currentRun?.active_transition_request_id,
    ) ?? controller?.transition_requests.at(-1);
  const currentDecision =
    controller?.transition_decisions.find(
      (item) =>
        item.transition_decision_id === currentRun?.active_transition_decision_id,
    ) ?? controller?.transition_decisions.at(-1);
  const currentPause =
    controller?.pause_records
      .filter((item) => item.workflow_run_id === runId)
      .at(-1);
  const currentHold =
    controller?.recovery_holds
      .filter((item) => item.workflow_run_id === runId)
      .at(-1);
  const currentEligibility =
    controller?.resume_eligibility_reviews
      .filter((item) => item.workflow_run_id === runId)
      .at(-1);
  const currentLease =
    controller?.execution_leases
      .filter((item) => item.workflow_run_id === runId)
      .at(-1);
  const currentDependency =
    controller?.dependency_checks
      .filter((item) => item.stage_instance_id === currentStage?.stage_instance_id)
      .at(-1);
  const currentDefinition = controller?.workflow_definition_snapshots.at(-1);
  const currentStageDefinition = controller?.stage_definitions.find(
    (item) => item.stage_definition_id === currentStage?.stage_definition_id,
  );

  const createRun = useCreateBobaWorkflowRun(projectId);
  const planNext = usePlanBobaWorkflowNext(projectId, runId);
  const createTransition = useCreateBobaWorkflowTransition(projectId, runId);
  const evaluateTransition = useEvaluateBobaWorkflowTransition(projectId, runId);
  const advanceSafe = useAdvanceBobaWorkflowSafe(projectId, runId);
  const coordinateApproved = useCoordinateBobaWorkflowApproved(projectId, runId);
  const pauseWorkflow = usePauseBobaWorkflow(projectId, runId);
  const continueController = useContinueBobaWorkflowController(projectId, runId);
  const cancelWorkflow = useCancelBobaWorkflow(projectId, runId);
  const createRecoveryHold = useCreateBobaWorkflowRecoveryHold(projectId, runId);
  const evaluateResume = useEvaluateBobaWorkflowResumeEligibility(projectId, runId);
  const recordHumanDecision = useRecordBobaWorkflowHumanDecision(projectId, runId);
  const exportController = useExportBobaWorkflowController(projectId);
  const resetController = useResetBobaWorkflowController(projectId);

  const [nextPlan, setNextPlan] =
    useState<BobaWorkflowNextStagePlanV1 | null>(null);
  const [notice, setNotice] = useState("");
  const [approvalRecordJson, setApprovalRecordJson] = useState("");
  const [safetyDecisionJson, setSafetyDecisionJson] = useState("");
  const [approvalBindingJson, setApprovalBindingJson] = useState("");
  const [safetyBindingJson, setSafetyBindingJson] = useState("");
  const [resumeEvidenceJson, setResumeEvidenceJson] = useState("");
  const [reviewer, setReviewer] = useState("local_operator");
  const [humanReason, setHumanReason] = useState("");
  const [humanDecision, setHumanDecision] = useState("request_more_evidence");

  const projectStages = useMemo(
    () =>
      runStages.filter((stage) => {
        const definition = controller?.stage_definitions.find(
          (item) => item.stage_definition_id === stage.stage_definition_id,
        );
        return definition?.stage_scope === "project";
      }),
    [controller?.stage_definitions, runStages],
  );
  const clipStages = useMemo(
    () => runStages.filter((stage) => Boolean(stage.clip_id)),
    [runStages],
  );
  const relevantArtifacts =
    controller?.artifact_bindings.filter(
      (item) => item.workflow_run_id === runId,
    ) ?? [];
  const missingOrUnsafeArtifacts = relevantArtifacts.filter(
    (item) => !item.available || item.stale || item.malformed,
  );
  const recentEvents =
    controller?.workflow_events
      .filter((item) => item.workflow_run_id === runId)
      .slice(-8)
      .reverse() ?? [];
  const recentIncidents =
    controller?.incidents
      .filter((item) => item.workflow_run_id === runId)
      .slice(-4)
      .reverse() ?? [];
  const failedStage = runStages.find((stage) =>
    ["failed", "timed_out", "recovery_required"].includes(stage.status),
  );
  const busy = [
    createRun,
    planNext,
    createTransition,
    evaluateTransition,
    advanceSafe,
    coordinateApproved,
    pauseWorkflow,
    continueController,
    cancelWorkflow,
    createRecoveryHold,
    evaluateResume,
    recordHumanDecision,
    exportController,
    resetController,
  ].some((mutation) => mutation.isPending);

  function createWorkflowRun() {
    setNotice("");
    createRun.mutate(
      {
        source_id: projectId,
        clip_ids: clipIds,
        output_ids_by_clip: outputIdsByClip,
        rights_status: "unknown",
      },
      {
        onSuccess: () =>
          setNotice(
            "Workflow run created. No rendering, upload, or publication started.",
          ),
        onError: (error) => setNotice(error.message),
      },
    );
  }

  function planNextStage() {
    if (!runId) return;
    setNotice("");
    planNext.mutate(undefined, {
      onSuccess: (plan) => {
        setNextPlan(plan);
        setNotice(
          plan.available
            ? `Next exact stage: ${words(plan.stage_definition?.stage_id)}. Nothing ran.`
            : plan.reason,
        );
      },
      onError: (error) => setNotice(error.message),
    });
  }

  async function reviewTransition() {
    if (
      !currentRun ||
      !nextPlan?.available ||
      !nextPlan.stage_instance ||
      !nextPlan.stage_definition
    ) {
      setNotice("Plan the next exact stage before reviewing its transition.");
      return;
    }
    const sourceStageId = nextPlan.stage_instance.predecessor_stage_instance_ids[0];
    if (!sourceStageId) {
      setNotice("The planned target has no exact predecessor stage.");
      return;
    }
    try {
      const approvalRecord = parseObject(
        "Approval record",
        approvalRecordJson,
      );
      const safetyDecision = parseObject(
        "Safety decision",
        safetyDecisionJson,
      );
      const request = await createTransition.mutateAsync({
        source_stage_instance_id: sourceStageId,
        target_stage_id: nextPlan.stage_definition.stage_id,
        expected_revision: currentRun.revision,
        transition_type: nextPlan.transition_type ?? "unknown",
        reason: "Human requested an exact transition review from the BOBA UI.",
        clip_id: nextPlan.stage_instance.clip_id ?? undefined,
        output_id: nextPlan.stage_instance.output_id ?? undefined,
        approval_record_id: stringField(
          approvalRecord,
          "approval_record_id",
          "record_id",
        ),
        safety_decision_id: stringField(
          safetyDecision,
          "safety_decision_id",
        ),
      });
      const decision = await evaluateTransition.mutateAsync({
        transitionId: request.transition_request_id,
        input: {
          expected_revision: request.current_revision,
          current_project_snapshot_digest: request.project_snapshot_digest,
          approval_record: approvalRecord,
          safety_decision: safetyDecision,
        },
      });
      setNotice(
        `Transition review: ${words(decision.decision)}. No target operation ran.`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Transition review failed.");
    }
  }

  function advanceSafeStage() {
    if (
      !currentRun ||
      !currentDecision ||
      currentDecision.decision !== "allowed_read_only_transition"
    ) {
      setNotice("No allowed read-only transition is ready.");
      return;
    }
    advanceSafe.mutate(
      {
        transition_decision_id: currentDecision.transition_decision_id,
        expected_revision: currentRun.revision,
      },
      {
        onSuccess: (result) =>
          setNotice(
            `One safe stage returned ${words(result.status)}. No later stage was started.`,
          ),
        onError: (error) => setNotice(error.message),
      },
    );
  }

  function coordinateExactStage() {
    if (
      !currentRun ||
      !currentDecision ||
      currentDecision.decision !== "allowed_exact_internal_transition"
    ) {
      setNotice("No allowed exact internal transition is ready.");
      return;
    }
    try {
      const approvalBinding = parseObject(
        "Integration approval binding",
        approvalBindingJson,
      );
      const safetyBinding = parseObject(
        "Integration Safety binding",
        safetyBindingJson,
      );
      if (!approvalBinding || !safetyBinding) {
        setNotice(
          "Exact Integration approval and Safety bindings are required.",
        );
        return;
      }
      coordinateApproved.mutate(
        {
          transition_decision_id: currentDecision.transition_decision_id,
          expected_revision: currentRun.revision,
          approval_binding: approvalBinding,
          safety_binding: safetyBinding,
        },
        {
          onSuccess: (result) =>
            setNotice(
              `Exact one-stage coordination returned ${words(result.status)}.`,
            ),
          onError: (error) => setNotice(error.message),
        },
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Binding JSON is invalid.");
    }
  }

  function reviewResumeEligibility() {
    if (!currentRun || !currentHold) {
      setNotice("No exact Recovery Hold is available for review.");
      return;
    }
    try {
      const evidence = parseObject("Resume evidence", resumeEvidenceJson) ?? {};
      evaluateResume.mutate(
        {
          expected_revision: currentRun.revision,
          recovery_hold_id: currentHold.recovery_hold_id,
          current_project_snapshot_digest: currentRun.project_snapshot_digest,
          rights_clear: evidence.rights_clear === true,
          approval_record:
            typeof evidence.approval_record === "object"
              ? (evidence.approval_record as Record<string, unknown>)
              : undefined,
          safety_decision:
            typeof evidence.safety_decision === "object"
              ? (evidence.safety_decision as Record<string, unknown>)
              : undefined,
          checkpoint_valid: evidence.checkpoint_valid === true,
          rollback_state_clear: evidence.rollback_state_clear === true,
          technical_validation:
            typeof evidence.technical_validation === "object"
              ? (evidence.technical_validation as Record<string, unknown>)
              : undefined,
          quality_decision:
            typeof evidence.quality_decision === "object"
              ? (evidence.quality_decision as Record<string, unknown>)
              : undefined,
          human_decision:
            typeof evidence.human_decision === "object"
              ? (evidence.human_decision as Record<string, unknown>)
              : undefined,
        },
        {
          onSuccess: (review) =>
            setNotice(
              review.resume_eligible
                ? "Resume eligibility passed. A separate exact transition is still required."
                : "Resume eligibility remains blocked. Nothing was continued.",
            ),
          onError: (error) => setNotice(error.message),
        },
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Resume evidence is invalid.");
    }
  }

  if (controllerQuery.isLoading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-panel/70 p-5 text-sm text-muted">
        Loading BOBA Workflow Controller…
      </section>
    );
  }

  if (controllerQuery.error) {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-300/[0.05] p-5">
        <h3 className="font-semibold text-white">BOBA Workflow Controller</h3>
        <p className="mt-2 text-sm text-rose-100">
          {controllerQuery.error.message}
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-violet-300/20 bg-panel/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.18em] text-violet-200">
            BOBA WORKFLOW CONTROLLER V1
          </p>
          <h3 className="mt-1 text-lg font-semibold text-white">
            Exact internal stage control
          </h3>
          <p className="mt-2 max-w-3xl text-xs text-muted">
            Workflow Controller advances Olympus one registered internal stage at
            a time.
          </p>
          <p className="mt-1 max-w-3xl text-xs text-muted">
            It does not diagnose repairs. Failed stages are handed to Autopilot
            while the normal workflow remains paused.
          </p>
          <p className="mt-1 max-w-3xl text-xs text-muted">
            Internal completion does not upload or publish content.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!currentRun && (
            <button
              className="rounded-lg border border-violet-300/30 px-3 py-2 text-xs text-violet-100 hover:bg-violet-300/[0.06]"
              disabled={busy}
              onClick={createWorkflowRun}
              type="button"
            >
              Create workflow run
            </button>
          )}
          <button
            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white hover:bg-white/5"
            disabled={!controller || exportController.isPending}
            onClick={() =>
              exportController.mutate(undefined, {
                onSuccess: (payload) => {
                  downloadJson(`boba-workflow-${projectId}.json`, payload);
                  setNotice("Sanitized Workflow Controller export downloaded.");
                },
                onError: (error) => setNotice(error.message),
              })
            }
            type="button"
          >
            Export
          </button>
          <button
            className="rounded-lg border border-rose-300/20 px-3 py-2 text-xs text-rose-100 hover:bg-rose-300/[0.06]"
            disabled={!controller || resetController.isPending}
            onClick={() => {
              if (
                !window.confirm(
                  "Reset active controller metadata only? Immutable history, source media, outputs, Recovery Holds, approvals, Safety decisions and Integration transactions remain.",
                )
              ) {
                return;
              }
              resetController.mutate(undefined, {
                onSuccess: () =>
                  setNotice("Active controller metadata reset safely."),
                onError: (error) => setNotice(error.message),
              });
            }}
            type="button"
          >
            Reset metadata
          </button>
        </div>
      </div>

      {notice && <p className="mt-3 text-xs text-violet-100">{notice}</p>}

      {!controller || !currentRun ? (
        <div className="mt-4 rounded-xl border border-white/10 bg-black/10 p-4 text-xs text-muted">
          No Workflow Controller run exists. Creating one records the immutable
          graph and source binding only; it does not execute the pipeline.
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              className="rounded-lg bg-violet-300 px-3 py-2 text-xs font-semibold text-slate-950 disabled:opacity-50"
              disabled={busy || currentRun.run_status !== "active"}
              onClick={planNextStage}
              type="button"
            >
              Plan next stage
            </button>
            <button
              className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
              disabled={busy || !nextPlan?.available}
              onClick={() => void reviewTransition()}
              type="button"
            >
              Review transition
            </button>
            <button
              className="rounded-lg border border-emerald-300/30 px-3 py-2 text-xs text-emerald-100 disabled:opacity-50"
              disabled={
                busy ||
                currentDecision?.decision !== "allowed_read_only_transition"
              }
              onClick={advanceSafeStage}
              type="button"
            >
              Advance safe read-only stage
            </button>
            <button
              className="rounded-lg border border-amber-300/30 px-3 py-2 text-xs text-amber-100 disabled:opacity-50"
              disabled={
                busy ||
                currentDecision?.decision !==
                  "allowed_exact_internal_transition"
              }
              onClick={coordinateExactStage}
              type="button"
            >
              Coordinate exact approved transition
            </button>
            <button
              className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
              disabled={busy || currentRun.run_status !== "active"}
              onClick={() =>
                pauseWorkflow.mutate(
                  {
                    expected_revision: currentRun.revision,
                    reason: "Human requested a Workflow Controller pause.",
                    category: "manual",
                    stage_instance_id: currentStage?.stage_instance_id,
                  },
                  {
                    onSuccess: () =>
                      setNotice("Workflow paused. Active target work was not killed."),
                    onError: (error) => setNotice(error.message),
                  },
                )
              }
              type="button"
            >
              Pause workflow
            </button>
            <button
              className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
              disabled={busy || currentRun.run_status !== "paused"}
              onClick={() =>
                continueController.mutate(currentRun.revision, {
                  onSuccess: () =>
                    setNotice(
                      "Controller pause released. No workflow stage was run automatically.",
                    ),
                  onError: (error) => setNotice(error.message),
                })
              }
              type="button"
            >
              Continue controller
            </button>
            <button
              className="rounded-lg border border-rose-300/30 px-3 py-2 text-xs text-rose-100 disabled:opacity-50"
              disabled={busy || ["completed", "cancelled"].includes(currentRun.run_status)}
              onClick={() => {
                if (!window.confirm("Cancel future workflow transitions?")) return;
                cancelWorkflow.mutate(
                  {
                    expectedRevision: currentRun.revision,
                    reason: "Human cancelled future Workflow Controller transitions.",
                  },
                  {
                    onSuccess: () =>
                      setNotice(
                        "Future transitions cancelled. Source media and outputs remain.",
                      ),
                    onError: (error) => setNotice(error.message),
                  },
                );
              }}
              type="button"
            >
              Cancel workflow
            </button>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <Section title="WORKFLOW" open>
              <StatusBadge value={currentRun.run_status} />
              <KeyValue
                label="Definition"
                value={currentDefinition?.workflow_name}
              />
              <KeyValue
                label="Version"
                value={currentDefinition?.workflow_version}
              />
              <KeyValue label="Run ID" value={currentRun.workflow_run_id} />
              <KeyValue label="Revision" value={currentRun.revision} />
              <KeyValue
                label="Project snapshot"
                value={short(currentRun.project_snapshot_digest)}
              />
              <KeyValue
                label="Internal output complete"
                value={currentRun.internal_output_complete ? "Yes" : "No"}
              />
              <p>
                An allowed transition applies only to the exact displayed
                workflow revision and project snapshot.
              </p>
            </Section>

            <Section title="CURRENT STAGE" open>
              <StatusBadge value={currentStage?.status} />
              <KeyValue label="Stage" value={words(currentStage?.stage_id)} />
              <KeyValue
                label="Scope"
                value={words(currentStageDefinition?.stage_scope)}
              />
              <KeyValue
                label="Registered operation"
                value={currentStageDefinition?.operation_id}
              />
              <KeyValue
                label="Clip"
                value={currentStage?.clip_id ?? "Project-wide"}
              />
              <KeyValue
                label="Output"
                value={currentStage?.output_id ?? "Not applicable"}
              />
              <KeyValue
                label="Attempt"
                value={currentStage?.attempt_number ?? "Not available"}
              />
            </Section>

            <Section title="PROJECT STAGES">
              <StageList
                stages={projectStages}
                empty="No project-level stages are recorded."
              />
            </Section>

            <Section title="CLIP STAGES">
              <StageList
                stages={clipStages}
                empty="No clip branch exists in this workflow run."
              />
            </Section>

            <Section title="DEPENDENCIES">
              <StatusBadge value={currentDependency?.dependency_status} />
              <KeyValue
                label="Required predecessors"
                value={
                  currentStageDefinition?.required_predecessor_stage_ids
                    .map(words)
                    .join(", ") || "None"
                }
              />
              <KeyValue
                label="Missing predecessors"
                value={
                  currentDependency?.required_predecessor_stage_ids
                    .filter(
                      (item) =>
                        !currentDependency.completed_predecessor_stage_ids.includes(
                          item,
                        ),
                    )
                    .map(words)
                    .join(", ") || "None"
                }
              />
              <KeyValue
                label="Blocks transition"
                value={
                  currentDependency
                    ? currentDependency.blocks_transition
                      ? "Yes"
                      : "No"
                    : "Not evaluated"
                }
              />
              {currentDependency?.failure_reasons.map((reason) => (
                <p className="text-rose-100" key={reason}>
                  {reason}
                </p>
              ))}
            </Section>

            <Section title="ARTIFACTS">
              <KeyValue
                label="Bound artifacts"
                value={relevantArtifacts.length}
              />
              <KeyValue
                label="Required types"
                value={
                  currentStageDefinition?.required_artifact_types.join(", ") ||
                  "None"
                }
              />
              <KeyValue
                label="Missing / stale / malformed"
                value={missingOrUnsafeArtifacts.length}
              />
              {missingOrUnsafeArtifacts.map((artifact) => (
                <p className="text-rose-100" key={artifact.artifact_binding_id}>
                  {words(artifact.artifact_type)} ·{" "}
                  {!artifact.available
                    ? "missing"
                    : artifact.stale
                      ? "stale"
                      : "malformed"}
                </p>
              ))}
              <p>Source media remains read-only. Accepted outputs are protected.</p>
            </Section>

            <Section title="PAUSE AND RECOVERY" open={Boolean(currentHold)}>
              <StatusBadge
                value={currentHold?.hold_status ?? currentRun.run_status}
              />
              <KeyValue
                label="Pause reason"
                value={currentPause?.pause_reason || currentRun.stop_reason}
              />
              <KeyValue
                label="Recovery Hold"
                value={currentHold?.recovery_hold_id}
              />
              <KeyValue
                label="Autopilot recovery"
                value={currentHold?.autopilot_run_id}
              />
              <KeyValue
                label="Hold released"
                value={currentHold ? (currentHold.released ? "Yes" : "No") : "No hold"}
              />
              {failedStage && !currentHold && (
                <button
                  className="rounded-lg border border-amber-300/30 px-3 py-2 text-xs text-amber-100"
                  disabled={busy}
                  onClick={() =>
                    createRecoveryHold.mutate(
                      {
                        expected_revision: currentRun.revision,
                        failed_stage_instance_id: failedStage.stage_instance_id,
                        reason:
                          failedStage.failure_summary ||
                          "Failed stage requires bounded recovery coordination.",
                      },
                      {
                        onSuccess: () =>
                          setNotice(
                            "Recovery Hold created and exact Autopilot handoff recorded.",
                          ),
                        onError: (error) => setNotice(error.message),
                      },
                    )
                  }
                  type="button"
                >
                  Create Recovery Hold
                </button>
              )}
              <p>
                A recovered output must pass validation, quality review and
                Safety Gate before Workflow Controller can consider the next
                stage.
              </p>
            </Section>

            <Section title="VALIDATION AND QUALITY">
              <KeyValue
                label="Technical validation"
                value={
                  currentDecision
                    ? currentDecision.validation_ready
                      ? "Ready"
                      : "Not ready"
                    : "Not evaluated"
                }
              />
              <KeyValue
                label="Output Quality"
                value={
                  currentDecision
                    ? currentDecision.quality_ready
                      ? "Accepted"
                      : "Not accepted"
                    : "Not evaluated"
                }
              />
              <KeyValue
                label="Resume eligible"
                value={
                  currentEligibility
                    ? currentEligibility.resume_eligible
                      ? "Yes"
                      : "No"
                    : "Not reviewed"
                }
              />
              <KeyValue
                label="Missing resume conditions"
                value={
                  currentEligibility?.missing_conditions.join(", ") || "None"
                }
              />
              {currentHold && (
                <>
                  <textarea
                    aria-label="Resume eligibility evidence JSON"
                    className="min-h-24 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                    onChange={(event) => setResumeEvidenceJson(event.target.value)}
                    placeholder='{"rights_clear":true,"checkpoint_valid":true,"rollback_state_clear":true,"technical_validation":{},"quality_decision":{}}'
                    value={resumeEvidenceJson}
                  />
                  <button
                    className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
                    disabled={busy}
                    onClick={reviewResumeEligibility}
                    type="button"
                  >
                    Review resume eligibility
                  </button>
                </>
              )}
            </Section>

            <Section title="SAFETY AND APPROVAL">
              <KeyValue
                label="Transition decision"
                value={words(currentDecision?.decision)}
              />
              <KeyValue
                label="Approval current"
                value={
                  currentDecision
                    ? currentDecision.target_approval_valid
                      ? "Yes"
                      : "No"
                    : "Not evaluated"
                }
              />
              <KeyValue
                label="Safety current"
                value={
                  currentDecision
                    ? currentDecision.safety_decision_valid
                      ? "Yes"
                      : "No"
                    : "Not evaluated"
                }
              />
              <KeyValue
                label="Execution lease"
                value={words(currentLease?.lease_status)}
              />
              <KeyValue
                label="Integration transaction"
                value={currentRun.active_integration_transaction_id}
              />
              <textarea
                aria-label="Exact approval record JSON"
                className="min-h-20 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                onChange={(event) => setApprovalRecordJson(event.target.value)}
                placeholder="Exact approval record JSON for transition review"
                value={approvalRecordJson}
              />
              <textarea
                aria-label="Exact Safety decision JSON"
                className="min-h-20 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                onChange={(event) => setSafetyDecisionJson(event.target.value)}
                placeholder="Exact current Safety decision JSON for transition review"
                value={safetyDecisionJson}
              />
              <textarea
                aria-label="Integration approval binding JSON"
                className="min-h-20 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                onChange={(event) => setApprovalBindingJson(event.target.value)}
                placeholder="Integration approval binding JSON for exact coordination"
                value={approvalBindingJson}
              />
              <textarea
                aria-label="Integration Safety binding JSON"
                className="min-h-20 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                onChange={(event) => setSafetyBindingJson(event.target.value)}
                placeholder="Integration Safety binding JSON for exact coordination"
                value={safetyBindingJson}
              />
              <p>
                Workflow Controller cannot create approvals or change Safety
                Gate decisions.
              </p>
            </Section>

            <Section title="NEXT INTERNAL TRANSITION" open>
              <StatusBadge value={currentDecision?.decision} />
              <KeyValue
                label="Planned next stage"
                value={words(
                  nextPlan?.stage_definition?.stage_id ??
                    controller.controller_summary.next_valid_stage,
                )}
              />
              <KeyValue
                label="Active request"
                value={currentRequest?.transition_request_id}
              />
              <KeyValue
                label="Request digest"
                value={short(currentRequest?.request_digest)}
              />
              <KeyValue
                label="Decision"
                value={currentDecision?.decision_summary}
              />
              {currentDecision?.blocking_reasons.map((reason) => (
                <p className="text-rose-100" key={reason}>
                  {reason}
                </p>
              ))}
              <p>{controller.controller_summary.safest_next_action}</p>
            </Section>

            <Section title="HUMAN DECISION">
              <label className="block">
                Reviewer
                <input
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                  onChange={(event) => setReviewer(event.target.value)}
                  value={reviewer}
                />
              </label>
              <label className="block">
                Decision
                <select
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                  onChange={(event) => setHumanDecision(event.target.value)}
                  value={humanDecision}
                >
                  <option value="request_more_evidence">
                    Request more evidence
                  </option>
                  <option value="keep_workflow_paused">
                    Keep workflow paused
                  </option>
                  <option value="acknowledge_disclosed_limitation">
                    Acknowledge disclosed limitation
                  </option>
                  <option value="reject_internal_transition">
                    Reject internal transition
                  </option>
                </select>
              </label>
              <label className="block">
                Reason
                <textarea
                  className="mt-1 min-h-20 w-full rounded-lg border border-white/10 bg-black/20 p-2 text-xs text-white"
                  onChange={(event) => setHumanReason(event.target.value)}
                  value={humanReason}
                />
              </label>
              <button
                className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
                disabled={
                  busy || !reviewer.trim() || !humanReason.trim()
                }
                onClick={() =>
                  recordHumanDecision.mutate(
                    {
                      expected_revision: currentRun.revision,
                      decision_type: "workflow_review",
                      decision: humanDecision,
                      reason: humanReason.trim(),
                      reviewer_reference: reviewer.trim(),
                      explicit_confirmation: true,
                      stage_instance_id: currentStage?.stage_instance_id,
                      transition_request_id:
                        currentRequest?.transition_request_id,
                    },
                    {
                      onSuccess: () =>
                        setNotice(
                          "Human workflow decision recorded. It did not override rights or Safety.",
                        ),
                      onError: (error) => setNotice(error.message),
                    },
                  )
                }
                type="button"
              >
                Record human decision
              </button>
            </Section>

            <Section title="LIVE WORKFLOW FEED" open>
              {recentEvents.length ? (
                recentEvents.map((event) => (
                  <div
                    className="rounded-lg border border-white/10 bg-white/[0.02] p-2"
                    key={event.event_id}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-white">
                        {words(event.event_type)}
                      </span>
                      <StatusBadge value={event.severity} />
                    </div>
                    <p className="mt-1">{event.easy_message}</p>
                    {event.confirmed_fact && (
                      <p className="mt-1 text-white">
                        Fact: {event.confirmed_fact}
                      </p>
                    )}
                    {event.assessment && (
                      <p className="mt-1">Assessment: {event.assessment}</p>
                    )}
                  </div>
                ))
              ) : (
                <p>No workflow events are recorded.</p>
              )}
              {recentIncidents.map((incident) => (
                <div
                  className="rounded-lg border border-rose-300/20 bg-rose-300/[0.04] p-2"
                  key={incident.incident_id}
                >
                  <p className="text-rose-100">{incident.title}</p>
                  <p>{incident.bounded_summary}</p>
                </div>
              ))}
            </Section>
          </div>
        </>
      )}
    </section>
  );
}
