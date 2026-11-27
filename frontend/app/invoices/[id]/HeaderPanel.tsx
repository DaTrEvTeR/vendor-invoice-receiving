"use client";

import { type FormEvent, useState } from "react";

import { api, type Edit, type InvoiceDetail, type PurchaseOrder, type Vendor } from "@/lib/api";
import { text } from "@/lib/format";

import { EditedMark, RawText, type Run } from "./shared";

type Input = "text" | "date" | "decimal" | "vendor" | "po" | "doctype";

interface Field {
  name: "document_type" | "invoice_number" | "invoice_date" | "vendor" | "purchase_order" | "currency";
  label: string;
  raw: string; // key in raw_header
  input: Input;
  nullable: boolean;
}

interface MoneyField extends Omit<Field, "name"> {
  name: "subtotal" | "tax" | "total";
}

const FIELDS: (Field | MoneyField)[] = [
  { name: "document_type", label: "Document type", raw: "document_type", input: "doctype", nullable: false },
  { name: "invoice_number", label: "Invoice number", raw: "invoice_number", input: "text", nullable: false },
  { name: "invoice_date", label: "Invoice date", raw: "invoice_date", input: "date", nullable: true },
  { name: "vendor", label: "Vendor", raw: "vendor_name", input: "vendor", nullable: true },
  { name: "purchase_order", label: "Purchase order", raw: "po_reference", input: "po", nullable: true },
  { name: "currency", label: "Currency", raw: "currency", input: "text", nullable: false },
  { name: "subtotal", label: "Subtotal", raw: "subtotal", input: "decimal", nullable: true },
  { name: "tax", label: "Tax", raw: "tax", input: "decimal", nullable: true },
  { name: "total", label: "Total", raw: "total", input: "decimal", nullable: true },
];

function current(invoice: InvoiceDetail, field: Field | MoneyField): string {
  return invoice[field.name] ?? "";
}

function shown(invoice: InvoiceDetail, field: Field | MoneyField): string {
  if (field.name === "vendor" && invoice.vendor) return `${invoice.vendor} · ${invoice.vendor_name}`;
  return text(invoice[field.name]);
}

interface Props {
  invoice: InvoiceDetail;
  vendors: Vendor[];
  orders: PurchaseOrder[];
  run: Run;
}

/** The invoice header: the vendor's text next to the system's interpretation (R5). */
export function HeaderPanel({ invoice, vendors, orders, run }: Props) {
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const canEdit = invoice.actions.edit;

  function startEditing() {
    setDraft(Object.fromEntries(FIELDS.map((field) => [field.name, current(invoice, field)])));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const edit: Edit = {};
    for (const field of FIELDS) {
      const value = draft[field.name].trim();
      if (value === current(invoice, field)) continue;
      edit[field.name] = value === "" && field.nullable ? null : value;
    }
    if (Object.keys(edit).length === 0 || (await run(() => api.editInvoice(invoice.id, edit)))) {
      setDraft(null);
    }
  }

  function input(field: Field | MoneyField) {
    if (!draft) return null;
    const value = draft[field.name];
    const set = (next: string) => setDraft({ ...draft, [field.name]: next });
    const common = { "aria-label": field.label, value };
    switch (field.input) {
      case "doctype":
        return (
          <select {...common} onChange={(event) => set(event.target.value)}>
            <option value="" disabled>
              (choose)
            </option>
            {["INVOICE", "MEMO", "CREDIT_MEMO"].map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
        );
      case "vendor":
        return (
          <select {...common} onChange={(event) => set(event.target.value)}>
            <option value="">(none)</option>
            {vendors.map((vendor) => (
              <option key={vendor.vendor_id} value={vendor.vendor_id}>
                {vendor.vendor_id} · {vendor.name}
              </option>
            ))}
          </select>
        );
      case "po":
        return (
          <select {...common} onChange={(event) => set(event.target.value)}>
            <option value="">(none)</option>
            {orders.map((order) => (
              <option key={order.po_number} value={order.po_number}>
                {order.po_number} · {order.vendor} {order.vendor_name} · {order.status}
              </option>
            ))}
          </select>
        );
      case "date":
        return <input type="date" {...common} onChange={(event) => set(event.target.value)} />;
      default:
        return (
          <input
            type="text"
            inputMode={field.input === "decimal" ? "decimal" : undefined}
            placeholder={field.input === "decimal" ? "1234.56" : undefined}
            {...common}
            onChange={(event) => set(event.target.value)}
          />
        );
    }
  }

  return (
    <section className="panel">
      <form onSubmit={save}>
        <div className="panel-title">
          <h2>Header</h2>
          {canEdit && !draft && (
            <button type="button" onClick={startEditing}>
              Edit
            </button>
          )}
          {draft && (
            <span className="buttons">
              <button type="submit" className="primary">
                Save
              </button>
              <button type="button" onClick={() => setDraft(null)}>
                Cancel
              </button>
            </span>
          )}
        </div>
        <table className="compare-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>In the file</th>
              <th>Interpretation</th>
            </tr>
          </thead>
          <tbody>
            {FIELDS.map((field) => {
              const edited = invoice.edited_fields.includes(field.name);
              return (
                <tr key={field.name} className={edited ? "edited" : undefined}>
                  <th scope="row">{field.label}</th>
                  <td>
                    <RawText value={invoice.raw_header[field.raw]} />
                  </td>
                  <td>
                    {draft ? input(field) : shown(invoice, field)}
                    {!draft && edited && (
                      <EditedMark
                        disabled={!canEdit}
                        onRevert={() => void run(() => api.editInvoice(invoice.id, { revert: [field.name] }))}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
            {invoice.notes && (
              <tr>
                <th scope="row">Vendor notes</th>
                <td colSpan={2}>
                  <span className="raw">{invoice.notes}</span>{" "}
                  <span className="muted">(shown only; never acted on)</span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </form>
    </section>
  );
}
