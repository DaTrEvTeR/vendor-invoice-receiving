import type { InvoiceDetail } from "@/lib/api";

/** Runs an API call that returns the updated invoice; resolves to true on success. */
export type Run = (call: () => Promise<InvoiceDetail>) => Promise<boolean>;

/** Marks a value a person changed, with a way back to the system's value. */
export function EditedMark({ onRevert, disabled }: { onRevert: () => void; disabled: boolean }) {
  return (
    <span className="edited-mark">
      edited
      {!disabled && (
        <button type="button" className="link" onClick={onRevert} title="Go back to the system's value">
          revert
        </button>
      )}
    </span>
  );
}

/** The vendor's text exactly as it was in the file. */
export function RawText({ value }: { value: string | string[] | null | undefined }) {
  if (value === undefined) return <span className="muted">not in this format</span>;
  if (value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
    return <span className="muted">(empty)</span>;
  }
  return <span className="raw">{Array.isArray(value) ? value.join(", ") : value}</span>;
}
