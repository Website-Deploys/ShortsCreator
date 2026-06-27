/**
 * TanStack Query hooks - the app's server-state layer.
 *
 * The app is "server-state first": projects, their status, and system info are
 * fetched and cached here rather than held in a global store. Mutations
 * invalidate the relevant queries so the UI stays consistent automatically.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiClientError } from "@/lib/apiClient";
import type { Analysis, CreateProjectInput, Project } from "@/lib/types";

export const queryKeys = {
  systemInfo: ["system", "info"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  analysis: (id: string) => ["projects", id, "analysis"] as const,
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
