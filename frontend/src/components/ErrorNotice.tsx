import { describeError } from "../api";

/** One place that renders errors, so stale data and provider failures never look generic. */
export default function ErrorNotice({ error, onReload }: { error: unknown; onReload?: () => void }) {
  if (!error) return null;
  const { kind, message } = describeError(error);
  return (
    <div className={`error error-${kind}`} role="alert">
      <p>{message}</p>
      {kind === "stale" && onReload && (
        <button className="secondary small" onClick={onReload}>
          Tải lại
        </button>
      )}
    </div>
  );
}
