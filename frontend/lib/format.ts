/** Shown for a value that is absent. */
export const DASH = "—";

export function text(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? DASH : String(value);
}

export function dateTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : DASH;
}
