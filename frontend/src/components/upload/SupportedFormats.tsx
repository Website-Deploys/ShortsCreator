/**
 * The supported-formats strip shown beneath the upload card.
 *
 * Communicates accepted formats and that there is no file-size limit (large
 * uploads are first-class).
 */
const FORMATS = ["MP4", "MOV", "AVI", "MKV", "WEBM"] as const;

export function SupportedFormats() {
  return (
    <div className="mt-8 text-center">
      <ul className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
        {FORMATS.map((format) => (
          <li key={format} className="flex items-center gap-1.5 text-sm text-muted">
            <span aria-hidden className="text-green-400">
              ✓
            </span>
            {format}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm text-muted">
        Supports videos of any size. Large uploads are welcome.
      </p>
    </div>
  );
}
