"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { StatusBadge } from "@/components/Badges";
import { ErrorBox } from "@/components/ErrorBox";
import { IssuesList } from "@/components/IssuesList";
import { api, ApiError, errorText, type InvoiceDetail } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

import { AuditTrail } from "./AuditTrail";
import { DecisionPanel } from "./DecisionPanel";
import { HeaderPanel } from "./HeaderPanel";
import { LineCard } from "./LineCard";
import type { Run } from "./shared";

/** The review screen: the vendor's data next to the interpretation, issues, edits and the decision. */
export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const loadInvoice = useCallback(() => api.invoice(id), [id]);
  const invoice = useLoad(loadInvoice);
  const products = useLoad(api.products);
  const vendors = useLoad(api.vendors);
  const orders = useLoad(api.purchaseOrders);
  const [failure, setFailure] = useState<unknown>();

  const data = invoice.data;
  const poSkus = useMemo(() => {
    const order = orders.data?.find((po) => po.po_number === data?.purchase_order);
    return new Set(order?.lines.map((line) => line.sku) ?? []);
  }, [orders.data, data?.purchase_order]);

  const run: Run = async (call) => {
    setFailure(undefined);
    try {
      const updated: InvoiceDetail = await call();
      invoice.setData(updated);
      orders.reload(); // receiving changes PO progress
      return true;
    } catch (error) {
      setFailure(error);
      invoice.reload(); // show the current state, e.g. after a concurrent decision
      return false;
    }
  };

  if (invoice.error) return <ErrorBox error={invoice.error} />;
  if (!data) return <p className="muted">Loading…</p>;

  const headerIssues = data.issues.filter((issue) => issue.line === null);
  return (
    <>
      <p>
        <Link href="/">← Invoices</Link>
      </p>
      <h1>
        {data.source_filename} <StatusBadge status={data.status} />
      </h1>
      <p className="muted">
        {data.document_type || "Unknown document"} {data.invoice_number} · parser {data.parser_key || "none"}{" "}
        · loaded {dateTime(data.created_at)}
        {data.decided_at ? ` · decided ${dateTime(data.decided_at)}` : ""}
      </p>

      <ErrorBox
        error={failure === undefined ? undefined : errorText(failure)}
        issues={failure instanceof ApiError ? failure.issues : []}
      />
      <DecisionPanel invoice={data} run={run} />

      {headerIssues.length > 0 && (
        <section className="panel">
          <h2>Invoice issues</h2>
          <IssuesList issues={headerIssues} />
        </section>
      )}

      <HeaderPanel invoice={data} vendors={vendors.data ?? []} orders={orders.data ?? []} run={run} />

      <h2>Lines</h2>
      {data.lines.length === 0 && <p className="muted">No lines could be read from this file.</p>}
      {data.lines.map((line) => (
        <LineCard
          key={line.id}
          invoice={data}
          line={line}
          products={products.data ?? []}
          poSkus={poSkus}
          run={run}
        />
      ))}

      <details className="panel">
        <summary>Original file, exactly as received</summary>
        <pre className="raw-file">{data.raw_content}</pre>
      </details>

      <AuditTrail events={data.audit_events} />
    </>
  );
}
