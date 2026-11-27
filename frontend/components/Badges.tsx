import type { InvoiceStatus, IssueKind } from "@/lib/api";

const STATUS_LABELS: Record<InvoiceStatus, string> = {
  pending: "Pending",
  needs_review: "Needs review",
  received: "Received",
  duplicate: "Duplicate",
  rejected: "Rejected",
  closed_no_receipt: "Closed, no receipt",
};

const KIND_LABELS: Record<IssueKind, string> = {
  terminal: "Cannot be received",
  hard: "Must fix",
  soft: "Discrepancy",
  info: "Info",
};

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  return <span className={`badge status-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function KindBadge({ kind }: { kind: IssueKind }) {
  return <span className={`badge kind-${kind}`}>{KIND_LABELS[kind]}</span>;
}
