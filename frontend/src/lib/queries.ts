/**
 * TanStack Query hooks - the app's server-state layer.
 *
 * The app is "server-state first": projects, their status, and system info are
 * fetched and cached here rather than held in a global store. Mutations
 * invalidate the relevant queries so the UI stays consistent automatically.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiClientError } from "@/lib/apiClient";
import type {
  ActivityFeedResponse,
  Analysis,
  AssetsResponse,
  ClipsResponse,
  CreateProjectInput,
  Editing,
  ExportsResponse,
  LibraryDashboard,
  Optimization,
  PackageList,
  Planning,
  PlanList,
  Project,
  QualityReport,
  RenderLogs,
  RenderManifestResponse,
  RenderRun,
  RenderValidation,
  SchedulerStatus,
  SearchResponse,
  StorageResponse,
  Story,
  TimelineList,
  Virality,
  WorkersResponse,
  Workflow,
  AdminSnapshot,
  AlertsResponse,
  AuditResponse,
  CostEstimate,
  EnginesResponse,
  FailuresResponse,
  MonitoringHealthResponse,
  QueueSnapshot,
  StorageAnalytics,
  SystemMetrics,
  UsageStats,
  WorkflowAnalytics,
} from "@/lib/types";

export const queryKeys = {
  systemInfo: ["system", "info"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  analysis: (id: string) => ["projects", id, "analysis"] as const,
  story: (id: string) => ["projects", id, "story"] as const,
  virality: (id: string) => ["projects", id, "virality"] as const,
  planning: (id: string) => ["projects", id, "planning"] as const,
  plans: (id: string) => ["projects", id, "plans"] as const,
  editing: (id: string) => ["projects", id, "editing"] as const,
  timelines: (id: string) => ["projects", id, "timelines"] as const,
  optimization: (id: string) => ["projects", id, "optimization"] as const,
  quality: (id: string) => ["projects", id, "quality"] as const,
  variants: (id: string) => ["projects", id, "variants"] as const,
  music: (id: string) => ["projects", id, "music"] as const,
  packages: (id: string) => ["projects", id, "packages"] as const,
  render: (id: string) => ["projects", id, "render"] as const,
  renderManifest: (id: string) => ["projects", id, "render", "manifest"] as const,
  renderValidation: (id: string) => ["projects", id, "render", "validation"] as const,
  renderLogs: (id: string) => ["projects", id, "render", "logs"] as const,
  workflow: (id: string) => ["projects", id, "workflow"] as const,
  workers: ["workflow", "workers"] as const,
  scheduler: ["workflow", "scheduler"] as const,
  libraryDashboard: ["library", "dashboard"] as const,
  libraryAssets: (params: Record<string, unknown>) => ["library", "assets", params] as const,
  libraryClips: (params: Record<string, unknown>) => ["library", "clips", params] as const,
  libraryExports: (params: Record<string, unknown>) => ["library", "exports", params] as const,
  librarySearch: (q: string) => ["library", "search", q] as const,
  libraryActivity: (projectId?: string) => ["library", "activity", projectId ?? "all"] as const,
  libraryStorage: (projectId?: string) => ["library", "storage", projectId ?? "all"] as const,
  monitoringHealth: ["monitoring", "health"] as const,
  monitoringEngines: ["monitoring", "engines"] as const,
  monitoringWorkflows: ["monitoring", "workflows"] as const,
  monitoringQueue: ["monitoring", "queue"] as const,
  monitoringSystem: ["monitoring", "system"] as const,
  monitoringStorage: ["monitoring", "storage"] as const,
  monitoringFailures: ["monitoring", "failures"] as const,
  monitoringUsage: ["monitoring", "usage"] as const,
  monitoringCost: ["monitoring", "cost"] as const,
  monitoringAudit: ["monitoring", "audit"] as const,
  monitoringAlerts: ["monitoring", "alerts"] as const,
  monitoringAdmin: ["monitoring", "admin"] as const,
};

const TERMINAL: ReadonlySet<string> = new Set(["analyzed", "complete", "failed"]);

/** Backend connectivity / version (powers the status indicator). */
export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.systemInfo,
    queryFn: api.getSystemInfo,
    staleTime: 30_000,
    retry: 1,
  });
}

/** All projects, newest first (project history). */
export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects, queryFn: api.listProjects });
}

/** A single project; polls while it is still in a non-terminal state. */
export function useProject(id: string) {
  return useQuery({
    queryKey: queryKeys.project(id),
    queryFn: () => api.getProject(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 5000;
    },
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateProjectInput) => api.createProject(input),
    onSuccess: (project: Project) => {
      qc.setQueryData(queryKeys.project(project.id), project);
      void qc.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}

export function useStartProcessing(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.processProject(id),
    onSuccess: (project: Project) => {
      qc.setQueryData(queryKeys.project(id), project);
      void qc.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}

export function useRenameProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.renameProject(id, name),
    onSuccess: (project: Project) => {
      qc.setQueryData(queryKeys.project(id), project);
      void qc.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  });
}

/* -------------------------------------------------------------------------- */
/* Cognitive Engine — video understanding                                     */
/* -------------------------------------------------------------------------- */

const ANALYSIS_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's video understanding. Polls while the pipeline is still running
 * (or while no analysis exists yet), then settles once it reaches a terminal
 * state. Returns `null` when no analysis has been created yet (HTTP 404), so
 * callers can show a "starting" state rather than an error.
 */
export function useAnalysis(id: string) {
  return useQuery({
    queryKey: queryKeys.analysis(id),
    queryFn: async (): Promise<Analysis | null> => {
      try {
        return await api.getAnalysis(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2500; // not created yet — keep checking
      return ANALYSIS_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/** Start (or resume) the analysis pipeline. */
export function useRunAnalysis(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runAnalysis(id),
    onSuccess: (analysis: Analysis) => {
      qc.setQueryData(queryKeys.analysis(id), analysis);
      void qc.invalidateQueries({ queryKey: queryKeys.project(id) });
    },
  });
}

/** Re-run a single analysis stage in isolation. */
export function useRerunStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunStage(id, stage),
    onSuccess: (analysis: Analysis) => {
      qc.setQueryData(queryKeys.analysis(id), analysis);
      void qc.invalidateQueries({ queryKey: queryKeys.project(id) });
    },
  });
}

/** Request cancellation of an in-flight analysis run. */
export function useCancelAnalysis(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelAnalysis(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.analysis(id) });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Story Engine — narrative understanding                                     */
/* -------------------------------------------------------------------------- */

const STORY_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's narrative understanding. Polls while the story pipeline is still
 * running (or while it hasn't started yet — it begins automatically once the
 * Cognitive Engine finishes), then settles at a terminal state. Returns `null`
 * when no story analysis exists yet (HTTP 404).
 */
export function useStory(id: string) {
  return useQuery({
    queryKey: queryKeys.story(id),
    queryFn: async (): Promise<Story | null> => {
      try {
        return await api.getStory(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 3000; // not created yet — keep checking
      return STORY_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/** Start (or resume) the story pipeline. */
export function useRunStory(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runStory(id),
    onSuccess: (story: Story) => qc.setQueryData(queryKeys.story(id), story),
  });
}

/** Re-run a single story stage in isolation. */
export function useRerunStoryStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunStoryStage(id, stage),
    onSuccess: (story: Story) => qc.setQueryData(queryKeys.story(id), story),
  });
}

/** Request cancellation of an in-flight story run. */
export function useCancelStory(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelStory(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.story(id) });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Virality Engine — viral-potential assessment                               */
/* -------------------------------------------------------------------------- */

const VIRALITY_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's virality assessment. Polls while the pipeline is still running
 * (or while it hasn't started yet — it begins automatically once the Story
 * Engine finishes), then settles at a terminal state. Returns `null` when no
 * virality analysis exists yet (HTTP 404).
 */
export function useVirality(id: string) {
  return useQuery({
    queryKey: queryKeys.virality(id),
    queryFn: async (): Promise<Virality | null> => {
      try {
        return await api.getVirality(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 3000; // not created yet — keep checking
      return VIRALITY_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/** Start (or resume) the virality pipeline. */
export function useRunVirality(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runVirality(id),
    onSuccess: (virality: Virality) => qc.setQueryData(queryKeys.virality(id), virality),
  });
}

/** Re-run a single virality stage in isolation. */
export function useRerunViralityStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunViralityStage(id, stage),
    onSuccess: (virality: Virality) => qc.setQueryData(queryKeys.virality(id), virality),
  });
}

/** Request cancellation of an in-flight virality run. */
export function useCancelVirality(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelVirality(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.virality(id) });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Clip Planner — editing blueprints                                          */
/* -------------------------------------------------------------------------- */

const PLANNING_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's clip planning. Polls while the pipeline is still running (or while
 * it hasn't started yet — it begins automatically once the Virality Engine
 * finishes), then settles at a terminal state. Returns `null` when no planning
 * exists yet (HTTP 404).
 */
export function usePlanning(id: string) {
  return useQuery({
    queryKey: queryKeys.planning(id),
    queryFn: async (): Promise<Planning | null> => {
      try {
        return await api.getPlanning(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 3000; // not created yet — keep checking
      return PLANNING_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/**
 * The full ranked editing plans. Available once the pipeline is terminal;
 * returns `null` while it is still running or absent (HTTP 404), and an empty
 * list when the planner honestly produced zero clips.
 */
export function usePlans(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.plans(id),
    enabled,
    queryFn: async (): Promise<PlanList | null> => {
      try {
        return await api.listPlans(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** Start (or resume) the clip-planning pipeline. */
export function useRunPlanning(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runPlanning(id),
    onSuccess: (planning: Planning) => qc.setQueryData(queryKeys.planning(id), planning),
  });
}

/** Re-run a single planning stage in isolation. */
export function useRerunPlanningStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunPlanningStage(id, stage),
    onSuccess: (planning: Planning) => {
      qc.setQueryData(queryKeys.planning(id), planning);
      void qc.invalidateQueries({ queryKey: queryKeys.plans(id) });
    },
  });
}

/** Request cancellation of an in-flight planning run. */
export function useCancelPlanning(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelPlanning(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.planning(id) });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* Editing Engine — non-destructive edit timelines                            */
/* -------------------------------------------------------------------------- */

const EDITING_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's editing analysis. Polls while the pipeline is still running (or
 * while it hasn't started yet — it begins automatically once the Clip Planner
 * finishes), then settles at a terminal state. Returns `null` when no editing
 * analysis exists yet (HTTP 404).
 */
export function useEditing(id: string) {
  return useQuery({
    queryKey: queryKeys.editing(id),
    queryFn: async (): Promise<Editing | null> => {
      try {
        return await api.getEditing(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 3000; // not created yet — keep checking
      return EDITING_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/**
 * The assembled edit timelines. Available once the pipeline is terminal; returns
 * `null` while still running or absent (HTTP 404), and an empty list when the
 * engine honestly produced zero timelines.
 */
export function useTimelines(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.timelines(id),
    enabled,
    queryFn: async (): Promise<TimelineList | null> => {
      try {
        return await api.listTimelines(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** Start (or resume) the editing pipeline. */
export function useRunEditing(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runEditing(id),
    onSuccess: (editing: Editing) => qc.setQueryData(queryKeys.editing(id), editing),
  });
}

/** Re-run a single editing stage in isolation. */
export function useRerunEditingStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunEditingStage(id, stage),
    onSuccess: (editing: Editing) => {
      qc.setQueryData(queryKeys.editing(id), editing);
      void qc.invalidateQueries({ queryKey: queryKeys.timelines(id) });
    },
  });
}

/** Request cancellation of an in-flight editing run. */
export function useCancelEditing(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelEditing(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.editing(id) });
    },
  });
}


/* -------------------------------------------------------------------------- */
/* Optimization Engine — post-render polish                                   */
/* -------------------------------------------------------------------------- */

const OPTIMIZATION_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's optimization analysis. Polls while the pipeline is still running
 * (or while it hasn't started yet), then settles at a terminal state. Returns
 * `null` when no optimization analysis exists yet (HTTP 404) — unlike the
 * earlier engines, optimization is started explicitly (it needs a render first),
 * so `null` is the common, honest "not started" state.
 */
export function useOptimization(id: string) {
  return useQuery({
    queryKey: queryKeys.optimization(id),
    queryFn: async (): Promise<Optimization | null> => {
      try {
        return await api.getOptimization(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false; // not started — do not poll until explicitly run
      return OPTIMIZATION_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/** The quality evaluation report (available once optimization is terminal). */
export function useQualityReport(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.quality(id),
    enabled,
    queryFn: async (): Promise<QualityReport | null> => {
      try {
        return await api.getQualityReport(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** The publish packages (available once optimization is terminal). */
export function usePackages(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.packages(id),
    enabled,
    queryFn: async (): Promise<PackageList | null> => {
      try {
        return await api.listPackages(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** Start (or resume) the optimization pipeline. */
export function useRunOptimization(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runOptimization(id),
    onSuccess: (optimization: Optimization) =>
      qc.setQueryData(queryKeys.optimization(id), optimization),
  });
}

/** Re-run a single optimization stage in isolation. */
export function useRerunOptimizationStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunOptimizationStage(id, stage),
    onSuccess: (optimization: Optimization) => {
      qc.setQueryData(queryKeys.optimization(id), optimization);
      void qc.invalidateQueries({ queryKey: queryKeys.quality(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.packages(id) });
    },
  });
}

/** Request cancellation of an in-flight optimization run. */
export function useCancelOptimization(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelOptimization(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.optimization(id) });
    },
  });
}


/* -------------------------------------------------------------------------- */
/* Rendering Engine - deterministic execution into real MP4s                  */
/* -------------------------------------------------------------------------- */

const RENDER_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's render run. Polls while rendering is in progress, then settles.
 * Returns `null` when no render run exists yet (HTTP 404) - rendering is started
 * explicitly (it is the heavy execution step), so `null` is the common "not
 * started" state.
 */
export function useRender(id: string) {
  return useQuery({
    queryKey: queryKeys.render(id),
    queryFn: async (): Promise<RenderRun | null> => {
      try {
        return await api.getRender(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return RENDER_TERMINAL.has(data.status) ? false : 2000;
    },
  });
}

/** The published render manifest (available once a render produced real files). */
export function useRenderManifest(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.renderManifest(id),
    enabled,
    queryFn: async (): Promise<RenderManifestResponse | null> => {
      try {
        return await api.getRenderManifest(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** The final render validation report. */
export function useRenderValidation(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.renderValidation(id),
    enabled,
    queryFn: async (): Promise<RenderValidation | null> => {
      try {
        return await api.getRenderValidation(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** Per-stage render logs. */
export function useRenderLogs(id: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.renderLogs(id),
    enabled,
    queryFn: async (): Promise<RenderLogs | null> => {
      try {
        return await api.getRenderLogs(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
  });
}

/** Start (or resume) the render pipeline. */
export function useRunRender(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.runRender(id),
    onSuccess: (run: RenderRun) => qc.setQueryData(queryKeys.render(id), run),
  });
}

/** Re-run a single render stage in isolation. */
export function useRerunRenderStage(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stage: string) => api.rerunRenderStage(id, stage),
    onSuccess: (run: RenderRun) => {
      qc.setQueryData(queryKeys.render(id), run);
      void qc.invalidateQueries({ queryKey: queryKeys.renderManifest(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.renderValidation(id) });
    },
  });
}

/** Request cancellation of an in-flight render run. */
export function useCancelRender(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelRender(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.render(id) });
    },
  });
}


/* -------------------------------------------------------------------------- */
/* Workflow Orchestration Engine - the central nervous system                 */
/* -------------------------------------------------------------------------- */

const WORKFLOW_TERMINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled"]);

/**
 * A project's workflow. Polls live while the workflow is active (running/paused/
 * pending) so the dashboard updates from real backend state, and settles when it
 * reaches a terminal status. Returns `null` when no workflow has been started.
 */
export function useWorkflow(id: string) {
  return useQuery({
    queryKey: queryKeys.workflow(id),
    queryFn: async (): Promise<Workflow | null> => {
      try {
        return await api.getWorkflow(id);
      } catch (err) {
        if (err instanceof ApiClientError && err.status === 404) return null;
        throw err;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return WORKFLOW_TERMINAL.has(data.status) ? false : 1500;
    },
  });
}

/** The worker pool's health (polls while a workflow view is open). */
export function useWorkers(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.workers,
    enabled,
    refetchInterval: enabled ? 2000 : false,
    queryFn: (): Promise<WorkersResponse> => api.getWorkers(),
  });
}

/** The queue/scheduler snapshot (polls while a workflow view is open). */
export function useScheduler(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.scheduler,
    enabled,
    refetchInterval: enabled ? 2000 : false,
    queryFn: (): Promise<SchedulerStatus> => api.getScheduler(),
  });
}

function workflowMutation(id: string, fn: (id: string) => Promise<Workflow>) {
  return () => fn(id);
}

/** Start (or resume) the full project workflow. */
export function useStartWorkflow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workflowMutation(id, api.startWorkflow),
    onSuccess: (wf: Workflow) => qc.setQueryData(queryKeys.workflow(id), wf),
  });
}

/** Pause / resume / cancel / retry mutations (each refreshes the workflow). */
export function usePauseWorkflow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workflowMutation(id, api.pauseWorkflow),
    onSuccess: (wf: Workflow) => qc.setQueryData(queryKeys.workflow(id), wf),
  });
}

export function useResumeWorkflow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workflowMutation(id, api.resumeWorkflow),
    onSuccess: (wf: Workflow) => qc.setQueryData(queryKeys.workflow(id), wf),
  });
}

export function useCancelWorkflow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workflowMutation(id, api.cancelWorkflow),
    onSuccess: (wf: Workflow) => qc.setQueryData(queryKeys.workflow(id), wf),
  });
}

export function useRetryWorkflow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: workflowMutation(id, api.retryWorkflow),
    onSuccess: (wf: Workflow) => qc.setQueryData(queryKeys.workflow(id), wf),
  });
}

/** Retry a single job. */
export function useRetryWorkflowJob(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => api.retryWorkflowJob(id, jobId),
    onSuccess: (wf: Workflow) => qc.setQueryData(queryKeys.workflow(id), wf),
  });
}


/* -------------------------------------------------------------------------- */
/* Project Management & Asset Library                                         */
/* -------------------------------------------------------------------------- */

export function useLibraryDashboard() {
  return useQuery({
    queryKey: queryKeys.libraryDashboard,
    queryFn: (): Promise<LibraryDashboard> => api.getLibraryDashboard(),
  });
}

export function useLibraryAssets(params: Record<string, string | boolean | undefined> = {}) {
  return useQuery({
    queryKey: queryKeys.libraryAssets(params),
    queryFn: (): Promise<AssetsResponse> => api.getLibraryAssets(params),
  });
}

export function useLibraryClips(params: Record<string, string | boolean | undefined> = {}) {
  return useQuery({
    queryKey: queryKeys.libraryClips(params),
    queryFn: (): Promise<ClipsResponse> => api.getLibraryClips(params),
  });
}

export function useLibraryExports(params: Record<string, string | boolean | undefined> = {}) {
  return useQuery({
    queryKey: queryKeys.libraryExports(params),
    queryFn: (): Promise<ExportsResponse> => api.getLibraryExports(params),
  });
}

export function useLibrarySearch(q: string) {
  return useQuery({
    queryKey: queryKeys.librarySearch(q),
    enabled: q.trim().length > 0,
    queryFn: (): Promise<SearchResponse> => api.librarySearch(q),
  });
}

export function useLibraryActivity(projectId?: string) {
  return useQuery({
    queryKey: queryKeys.libraryActivity(projectId),
    queryFn: (): Promise<ActivityFeedResponse> => api.getLibraryActivity({ project_id: projectId }),
  });
}

export function useLibraryStorage(projectId?: string) {
  return useQuery({
    queryKey: queryKeys.libraryStorage(projectId),
    queryFn: (): Promise<StorageResponse> => api.getLibraryStorage(projectId),
  });
}

function invalidateLibrary(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["library"] });
}

/** Archive / restore a project (additive metadata; engine data untouched). */
export function useArchiveProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => api.archiveProject(projectId),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useRestoreProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => api.restoreProject(projectId),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useSetProjectFavorite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, favorite }: { projectId: string; favorite: boolean }) =>
      api.setProjectFavorite(projectId, favorite),
    onSuccess: () => invalidateLibrary(qc),
  });
}

/** Run a cleanup operation (the only destructive library action). */
export function useLibraryCleanup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ operation, projectId }: { operation: string; projectId?: string }) =>
      api.libraryCleanup(operation, projectId),
    onSuccess: () => invalidateLibrary(qc),
  });
}



/* -------------------------------------------------------------------------- */
/* Production Monitoring & Analytics - observational, live-refreshing         */
/* -------------------------------------------------------------------------- */

/** Live operational dashboards refresh on a fixed interval (real backend state). */
const MONITORING_REFRESH_MS = 5000;

export function useMonitoringHealth(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringHealth,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<MonitoringHealthResponse> => api.getMonitoringHealth(),
  });
}

export function useMonitoringEngines(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringEngines,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<EnginesResponse> => api.getMonitoringEngines(),
  });
}

export function useMonitoringWorkflows(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringWorkflows,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<WorkflowAnalytics> => api.getMonitoringWorkflows(),
  });
}

export function useMonitoringQueue(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringQueue,
    enabled,
    refetchInterval: enabled ? 2500 : false,
    queryFn: (): Promise<QueueSnapshot> => api.getMonitoringQueue(),
  });
}

export function useMonitoringSystem(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringSystem,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<SystemMetrics> => api.getMonitoringSystem(),
  });
}

export function useMonitoringStorage(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringStorage,
    enabled,
    queryFn: (): Promise<StorageAnalytics> => api.getMonitoringStorage(false),
  });
}

export function useMonitoringFailures(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringFailures,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<FailuresResponse> => api.getMonitoringFailures(),
  });
}

export function useMonitoringUsage(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringUsage,
    enabled,
    queryFn: (): Promise<UsageStats> => api.getMonitoringUsage(),
  });
}

export function useMonitoringCost(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringCost,
    enabled,
    queryFn: (): Promise<CostEstimate> => api.getMonitoringCost(),
  });
}

export function useMonitoringAudit(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringAudit,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<AuditResponse> => api.getMonitoringAudit(100),
  });
}

export function useMonitoringAlerts(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringAlerts,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<AlertsResponse> => api.getMonitoringAlerts(),
  });
}

export function useMonitoringAdmin(enabled = true) {
  return useQuery({
    queryKey: queryKeys.monitoringAdmin,
    enabled,
    refetchInterval: enabled ? MONITORING_REFRESH_MS : false,
    queryFn: (): Promise<AdminSnapshot> => api.getMonitoringAdmin(),
  });
}
