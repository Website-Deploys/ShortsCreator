"use client";

/** A project card for the history list: thumbnail, name, date, status, actions. */
import Link from "next/link";
import { useState } from "react";

import { TrashIcon } from "@/components/icons";
import { useToast } from "@/components/notifications/ToastProvider";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Thumbnail } from "@/components/ui/Thumbnail";
import { formatRelative } from "@/lib/format";
import { useDeleteProject } from "@/lib/queries";
import type { Project } from "@/lib/types";

export function ProjectCard({ project }: { project: Project }) {
  const { notify } = useToast();
  const deleteProject = useDeleteProject();
  const [confirming, setConfirming] = useState(false);

  const onDelete = async () => {
    try {
      await deleteProject.mutateAsync(project.id);
      notify({ tone: "success", title: "Project deleted", description: project.name });
    } catch {
      notify({ tone: "error", title: "Could not delete project", description: "Please try again." });
    } finally {
      setConfirming(false);
    }
  };

  return (
    <>
      <div className="group flex items-center gap-4 rounded-xl border border-white/10 bg-surface p-4 transition-colors hover:border-white/20">
        <Link
          href={`/projects/${project.id}`}
          className="flex min-w-0 flex-1 items-center gap-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-lg"
        >
          <Thumbnail
            projectId={project.id}
            hasThumbnail={project.has_thumbnail}
            className="h-16 w-28 shrink-0 rounded-lg"
            iconClassName="h-6 w-6"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-white">{project.name}</p>
            <p className="truncate text-sm text-muted">
              {project.source_filename} · {formatRelative(project.created_at)}
            </p>
          </div>
        </Link>
        <StatusBadge status={project.status} />
        <button
          type="button"
          aria-label={`Delete ${project.name}`}
          onClick={() => setConfirming(true)}
          className="rounded-lg p-2 text-muted opacity-0 transition-all hover:bg-red-500/10 hover:text-red-300 focus:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent group-hover:opacity-100"
        >
          <TrashIcon className="h-5 w-5" />
        </button>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Delete this project?"
        description={`"${project.name}" and its uploaded video will be permanently removed. This cannot be undone.`}
        confirmLabel="Delete"
        loading={deleteProject.isPending}
        onConfirm={onDelete}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
