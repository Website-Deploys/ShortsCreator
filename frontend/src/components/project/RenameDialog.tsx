"use client";

/** A small dialog to rename a project (real, backed by PATCH /projects/{id}). */
import { useEffect, useState } from "react";

import { useToast } from "@/components/notifications/ToastProvider";
import { Button } from "@/components/ui/Button";
import { useRenameProject } from "@/lib/queries";

interface RenameDialogProps {
  projectId: string;
  currentName: string;
  open: boolean;
  onClose: () => void;
}

export function RenameDialog({ projectId, currentName, open, onClose }: RenameDialogProps) {
  const { notify } = useToast();
  const rename = useRenameProject(projectId);
  const [name, setName] = useState(currentName);

  useEffect(() => {
    if (open) setName(currentName);
  }, [open, currentName]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await rename.mutateAsync(trimmed);
      notify({ tone: "success", title: "Project renamed" });
      onClose();
    } catch {
      notify({ tone: "error", title: "Couldn't rename project", description: "Please try again." });
    }
  };

  return (
    <div role="dialog" aria-modal="true" aria-label="Rename project" className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button aria-label="Close" tabIndex={-1} onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <form
        onSubmit={submit}
        className="relative w-full max-w-sm animate-fade-in rounded-2xl border border-white/10 bg-elevated p-6 shadow-2xl"
      >
        <h2 className="text-base font-semibold">Rename project</h2>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={200}
          className="mt-4 w-full rounded-lg border border-white/10 bg-surface px-4 py-2.5 text-white focus:border-accent focus:outline-none"
          aria-label="Project name"
        />
        <div className="mt-6 flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={rename.isPending}>
            Cancel
          </Button>
          <Button type="submit" loading={rename.isPending} disabled={!name.trim()}>
            Save
          </Button>
        </div>
      </form>
    </div>
  );
}
