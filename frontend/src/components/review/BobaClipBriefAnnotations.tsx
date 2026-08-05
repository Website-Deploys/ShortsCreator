"use client";

/**
 * Review-session annotations.
 *
 * These notes are UI metadata held in the review session. They never become part
 * of the canonical clip brief, and the notice saying so is always shown.
 */

import { useState } from "react";

import {
  LOCAL_ANNOTATION_NOTICE,
  MAX_ANNOTATION_LENGTH,
  MAX_ANNOTATIONS,
  buildAnnotation,
  type ClipBriefAnnotation,
} from "@/lib/clipBriefReview";

export function BobaClipBriefAnnotations({
  annotations,
  fieldPaths,
  onAdd,
  onRemove,
}: {
  annotations: ClipBriefAnnotation[];
  fieldPaths: string[];
  onAdd: (annotation: ClipBriefAnnotation) => void;
  onRemove: (annotationId: string) => void;
}) {
  const [fieldPath, setFieldPath] = useState(fieldPaths[0] ?? "");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const annotation = buildAnnotation(fieldPath, text);
    if (!annotation) {
      setError("Enter note text without credentials.");
      return;
    }
    if (annotations.length >= MAX_ANNOTATIONS) {
      setError(`At most ${MAX_ANNOTATIONS} review-session notes are kept.`);
      return;
    }
    setError(null);
    setText("");
    onAdd(annotation);
  };

  return (
    <div className="space-y-2">
      <p className="text-[11px] text-white/45">{LOCAL_ANNOTATION_NOTICE}</p>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-white/60">
          Field
          <select
            value={fieldPath}
            onChange={(event) => setFieldPath(event.target.value)}
            className="mt-1 block rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-white"
          >
            {fieldPaths.map((path) => (
              <option key={path} value={path}>
                {path}
              </option>
            ))}
          </select>
        </label>
        <label className="grow text-xs text-white/60">
          Note
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={MAX_ANNOTATION_LENGTH}
            className="mt-1 block w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-white"
          />
        </label>
        <button
          type="button"
          onClick={submit}
          className="rounded border border-white/10 px-3 py-1.5 text-xs text-white/70"
        >
          Add note
        </button>
      </div>
      {error ? <p className="text-xs text-amber-200/90">{error}</p> : null}

      {annotations.length > 0 ? (
        <ul className="space-y-2">
          {annotations.map((annotation) => (
            <li
              key={annotation.annotation_id}
              className="rounded border border-white/10 bg-white/[0.02] p-3 text-xs"
            >
              <p className="text-white/70">{annotation.text}</p>
              <p className="mt-1 text-white/45">{annotation.field_path}</p>
              <p className="mt-1 text-[11px] text-white/40">{annotation.notice}</p>
              <button
                type="button"
                onClick={() => onRemove(annotation.annotation_id)}
                className="mt-1 text-[11px] text-white/50 underline"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
