"use client";

/**
 * The Quick Actions panel.
 *
 * Implemented actions are real; unimplemented ones are clearly disabled with a
 * tooltip explaining why - never faked. Actions: Generate Shorts (queues),
 * Rename, Download Original, Duplicate (coming soon), Archive (coming soon),
 * Delete.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  ArchiveIcon,
  CopyIcon,
  DownloadIcon,
  PencilIcon,
  SparklesIcon,
  TrashIcon,
} from "@/components/icons";
import { useToast } from "@/components/notifications/ToastProvider";
import { RenameDialog } from "@/components/project/RenameDialog";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Tooltip } from "@/components/ui/Tooltip";
import { mediaUrls } from "@/lib/apiClient";
import { useDeleteProject, useStartProcessing } from "@/lib/queries";
import type { Project } from "@/lib/types";

import type { ReactNode } from "react";

function ActionRow({
  icon,
  label,
  onClick,
  href,
  disabled,
  danger,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  danger?: boolean;
}) {
  const base = `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
    disabled
      ? "cursor-not-allowed text-muted/50"
      : danger
        ? "text-red-300 hover:bg-red-500/10"
        : "text-white hover:bg-white/5"
  }`;
  if (href && !disabled) {
    return (
      <a href={href} className={base}>
        {icon}
        {label}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={base}>
      {icon}
      {label}
    </button>
  );
}

export function QuickActions({ project }: { project: Project }) {
  const router = useRouter();
  const { notify } = useToast();
  const startProcessing = useStartProcessing(project.id);
  const deleteProject = useDeleteProject();
  const [renaming, setRenaming] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const canGenerate = project.status === "uploaded" || project.status === "analyzed";
  const disabledReason =
    project.status === "analyzing"
      ? "Olympus is still understanding your video"
      : "Already queued for the editing pipeline";

  const onGenerate = async () => {
    try {
      await startProcessing.mutateAsync();
      notify({
        tone: "success",
        title: "Queued for editing",
        description: "Your video is queued. Shorts will appear once the pipeline runs.",
      });
    } catch {
      notify({ tone: "error", title: "Couldn't queue project", description: "Please try again." });
    }
  };

  const onDelete = async () => {
    try {
      await deleteProject.mutateAsync(project.id);
      notify({ tone: "success", title: "Project deleted", description: project.name });
      router.push("/projects");
    } catch {
      notify({ tone: "error", title: "Couldn't delete project", description: "Please try again." });
      setConfirmingDelete(false);
    }
  };

  return (
    <div className="rounded-xl border border-white/10 bg-surface p-2">
      <p className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        Quick actions
      </p>

      {canGenerate ? (
        <ActionRow
          icon={<SparklesIcon className="h-4 w-4 text-accent" />}
          label="Generate Shorts"
          onClick={onGenerate}
        />
      ) : (
        <Tooltip label={disabledReason}>
          <ActionRow icon={<SparklesIcon className="h-4 w-4" />} label="Generate Shorts" disabled />
        </Tooltip>
      )}

      <ActionRow
        icon={<PencilIcon className="h-4 w-4" />}
        label="Rename project"
        onClick={() => setRenaming(true)}
      />
      <ActionRow
        icon={<DownloadIcon className="h-4 w-4" />}
        label="Download original"
        href={mediaUrls.download(project.id)}
      />

      <Tooltip label="Coming soon">
        <ActionRow icon={<CopyIcon className="h-4 w-4" />} label="Duplicate" disabled />
      </Tooltip>
      <Tooltip label="Coming soon">
        <ActionRow icon={<ArchiveIcon className="h-4 w-4" />} label="Archive" disabled />
      </Tooltip>

      <div className="my-1 h-px bg-white/5" />
      <ActionRow
        icon={<TrashIcon className="h-4 w-4" />}
        label="Delete project"
        danger
        onClick={() => setConfirmingDelete(true)}
      />

      <RenameDialog
        projectId={project.id}
        currentName={project.name}
        open={renaming}
        onClose={() => setRenaming(false)}
      />
      <ConfirmDialog
        open={confirmingDelete}
        title="Delete this project?"
        description={`"${project.name}" and its uploaded video will be permanently removed. This cannot be undone.`}
        confirmLabel="Delete"
        loading={deleteProject.isPending}
        onConfirm={onDelete}
        onCancel={() => setConfirmingDelete(false)}
      />
    </div>
  );
}
