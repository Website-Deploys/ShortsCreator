/**
 * TanStack Query hooks.
 *
 * Server state (system info, projects, clips) is fetched and cached here.
 * Per the Frontend Technology decision, the app is "server-state first": most
 * UI state is really server state, managed by TanStack Query rather than a
 * heavy global store.
 *
 * Query keys are centralised so cache invalidation is consistent.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/apiClient";

export const queryKeys = {
  systemInfo: ["system", "info"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
};

/** Fetch backend runtime info (used to show backend connectivity). */
export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.systemInfo,
    queryFn: api.getSystemInfo,
    staleTime: 30_000,
    retry: 1,
  });
}

/** Fetch the current user's projects (Milestone 2 endpoint). */
export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projects,
    queryFn: api.listProjects,
    retry: 0,
  });
}

/**
 * Fetch a single project and poll while it is still processing.
 *
 * The poll interval is the engine behind the honest, state-derived progress on
 * the Processing screen; polling stops once the project reaches a terminal
 * state.
 */
export function useProject(id: string) {
  return useQuery({
    queryKey: queryKeys.project(id),
    queryFn: () => api.getProject(id),
    retry: 0,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      const terminal = state === "complete" || state === "failed" || state === "cancelled";
      return terminal ? false : 3000;
    },
  });
}
