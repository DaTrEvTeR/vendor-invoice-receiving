"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { StatusBadge } from "@/components/Badges";
import { ErrorBox } from "@/components/ErrorBox";
import { api, errorText, type InvoiceDetail, type IssueCounts } from "@/lib/api";
import { dateTime, text } from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

function openIssues(counts: IssueCounts): string {
  const parts = [];
  const blocking = counts.terminal + counts.hard;
  if (blocking) parts.push(`${blocking} blocking`);
  if (counts.soft) parts.push(`${counts.soft} discrepanc${counts.soft === 1 ? "y" : "ies"}`);
  return parts.join(", ") || "none";
}

export default function InvoicesPage() {
  const invoices = useLoad(api.invoices);
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InvoiceDetail>();
  const [error, setError] = useState<string>();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(undefined);
    setResult(undefined);
    try {
      setResult(await api.upload(file));
      setFile(null);
      setInputKey((key) => key + 1);
      invoices.reload();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Invoices</h1>
      <section className="panel">
        <h2>Load a vendor invoice</h2>
        <form className="upload" onSubmit={submit}>
          <input
            key={inputKey}
            type="file"
            accept=".json,.csv"
            aria-label="Invoice file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button type="submit" className="primary" disabled={!file || busy}>
            {busy ? "Loading…" : "Load"}
          </button>
        </form>
        <p className="muted">
          JSON or CSV, up to 1 MB. An invoice that matches its purchase order exactly is received
          automatically; anything uncertain waits for review.
        </p>
        <ErrorBox error={error} />
        {result && (
          <p className="notice">
            {result.already_uploaded ? "This exact file was loaded before: " : "Loaded "}
            <Link href={`/invoices/${result.id}`}>{result.source_filename}</Link>{" "}
            <StatusBadge status={result.status} /> {result.status_notes}
          </p>
        )}
      </section>

      <ErrorBox error={invoices.error} />
      {invoices.data && invoices.data.length === 0 && <p className="muted">No invoices loaded yet.</p>}
      {invoices.data && invoices.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Vendor</th>
              <th>Invoice no.</th>
              <th>Type</th>
              <th>PO</th>
              <th className="num">Total</th>
              <th>Status</th>
              <th>Open issues</th>
              <th>Loaded</th>
            </tr>
          </thead>
          <tbody>
            {invoices.data.map((invoice) => (
              <tr key={invoice.id}>
                <td>
                  <Link href={`/invoices/${invoice.id}`}>{invoice.source_filename}</Link>
                </td>
                <td>{text(invoice.vendor_name)}</td>
                <td className="nowrap">{text(invoice.invoice_number)}</td>
                <td>{text(invoice.document_type)}</td>
                <td className="nowrap">{text(invoice.purchase_order)}</td>
                <td className="num">
                  {text(invoice.total)} {invoice.total ? invoice.currency : ""}
                </td>
                <td>
                  <StatusBadge status={invoice.status} />
                </td>
                <td>{invoice.status === "needs_review" ? openIssues(invoice.issue_counts) : ""}</td>
                <td>{dateTime(invoice.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
