"use client";

import Link from "next/link";
import { useState } from "react";

import { api, type InvoiceDetail } from "@/lib/api";

import type { Run } from "./shared";

/** Approve, with an explicit acceptance when discrepancies remain (R5a). */
function ApproveControl({ invoice, run }: { invoice: InvoiceDetail; run: Run }) {
  // Remounted (so unticked) whenever the set of discrepancies changes: accepting covers
  // only the discrepancies the person saw when ticking the box.
  const [accept, setAccept] = useState(false);
  const actions = invoice.actions;
  const accepting = accept && actions.needs_confirmation;

  return (
    <div className="approve">
      {actions.approve && actions.needs_confirmation && (
        <label>
          <input type="checkbox" checked={accept} onChange={(event) => setAccept(event.target.checked)} /> I
          accept the discrepancies listed below
        </label>
      )}
      <button
        type="button"
        className="primary"
        disabled={!actions.approve || (actions.needs_confirmation && !accept)}
        onClick={() => void run(() => api.approve(invoice.id, accepting))}
      >
        Approve and receive
      </button>
      {!actions.approve && <span className="muted">Available once the blocking issues below are fixed.</span>}
    </div>
  );
}

/** Status, the system's reasoning, and the person's decision for the whole invoice (R1). */
export function DecisionPanel({ invoice, run }: { invoice: InvoiceDetail; run: Run }) {
  const [reason, setReason] = useState("");
  const actions = invoice.actions;
  // Issues are recreated on every validation, so any change gives a new key.
  const discrepancies = invoice.issues
    .filter((issue) => issue.kind === "soft")
    .map((issue) => issue.id)
    .join(",");

  function reject() {
    if (window.confirm("Reject this invoice? Nothing will be received.")) {
      void run(() => api.reject(invoice.id, reason));
    }
  }

  function close() {
    if (window.confirm("Close this document without receiving anything?")) {
      void run(() => api.close(invoice.id, reason));
    }
  }

  return (
    <section className="panel decision">
      <p className="status-notes">{invoice.status_notes}</p>
      {invoice.duplicate_of && (
        <p>
          Original:{" "}
          <Link href={`/invoices/${invoice.duplicate_of.id}`}>{invoice.duplicate_of.source_filename}</Link>
        </p>
      )}
      {invoice.status === "needs_review" && (
        <div className="decide">
          <ApproveControl key={discrepancies} invoice={invoice} run={run} />
          <div className="refuse">
            <input
              type="text"
              placeholder="Reason (optional)"
              aria-label="Reason"
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
            />
            <button type="button" className="danger" disabled={!actions.reject} onClick={reject}>
              Reject
            </button>
            {actions.close && (
              <button type="button" onClick={close}>
                Close without receipt
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
