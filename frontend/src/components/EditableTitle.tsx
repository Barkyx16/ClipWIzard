import { useEffect, useRef, useState } from "react";
import { Check, Pencil, X } from "lucide-react";

/** A page title that turns into a text field when you click the pencil. */
export default function EditableTitle({ value, onSave }: { value: string; onSave: (v: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  const save = async () => {
    const next = draft.trim();
    if (!next || next === value) return setEditing(false);
    setBusy(true);
    try {
      await onSave(next);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <input
          ref={input}
          className="input max-w-xl font-display text-3xl tracking-wide sm:text-4xl"
          value={draft}
          maxLength={200}
          disabled={busy}
          aria-label="Session name"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") setEditing(false);
          }}
        />
        <button type="button" className="btn-icon" aria-label="Save name" onClick={save} disabled={busy}>
          <Check className="h-4 w-4" />
        </button>
        <button type="button" className="btn-icon" aria-label="Cancel" onClick={() => setEditing(false)}>
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }
  return (
    <div className="group flex min-w-0 items-center gap-2">
      <h1 className="truncate font-display text-4xl tracking-wide sm:text-5xl" title={value}>
        {value}
      </h1>
      <button
        type="button"
        className="btn-icon h-8 w-8 shrink-0 opacity-60 group-hover:opacity-100"
        aria-label="Rename session"
        onClick={() => {
          setDraft(value);
          setEditing(true);
        }}
      >
        <Pencil className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
