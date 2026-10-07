export default function ListEditor({
  label,
  hint,
  items,
  onChange,
  ordered = false,
}: {
  label: string;
  hint?: string;
  items: string[];
  onChange: (items: string[]) => void;
  ordered?: boolean;
}) {
  const set = (i: number, v: string) => onChange(items.map((x, j) => (j === i ? v : x)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= items.length) return;
    const next = [...items];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <fieldset className="list-editor">
      <legend>{label}</legend>
      {hint && <p className="muted small">{hint}</p>}
      {items.length === 0 && <p className="muted small">None yet.</p>}
      {items.map((item, i) => (
        <div key={i} className="list-row">
          <span className="list-mark">{ordered ? `${i + 1}.` : "•"}</span>
          <textarea
            aria-label={`${label} ${i + 1}`}
            value={item}
            rows={Math.max(1, Math.ceil(item.length / 70))}
            onChange={(e) => set(i, e.target.value)}
          />
          {ordered && (
            <>
              <button className="icon" onClick={() => move(i, -1)} aria-label="Move up" disabled={i === 0}>
                ↑
              </button>
              <button
                className="icon"
                onClick={() => move(i, 1)}
                aria-label="Move down"
                disabled={i === items.length - 1}
              >
                ↓
              </button>
            </>
          )}
          <button className="icon" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="Remove">
            ×
          </button>
        </div>
      ))}
      <button className="ghost small" onClick={() => onChange([...items, ""])}>
        + Add
      </button>
    </fieldset>
  );
}
