"use client";

import { type FormEvent, Fragment, type ReactNode, useState } from "react";

import { IssuesList } from "@/components/IssuesList";
import { api, type Edit, type InvoiceDetail, type InvoiceLine, type Product } from "@/lib/api";
import { text } from "@/lib/format";

import { EditedMark, RawText, type Run } from "./shared";

// The vendor's fields, in display order; a field the file's format does not have is not shown.
const RAW_ROWS: [label: string, keys: string[]][] = [
  ["Item code", ["item_code"]],
  ["Description", ["description"]],
  ["Quantity", ["quantity", "uom"]],
  ["Unit price", ["unit_price"]],
  ["Amount", ["amount"]],
  ["Backordered", ["qty_backordered"]],
  ["Certificates", ["serials"]],
];

interface Draft {
  line_type: string;
  product: string;
  quantity: string;
  amount: string;
  serials: string;
}

function draftOf(line: InvoiceLine): Draft {
  return {
    line_type: line.line_type,
    product: line.product ?? "",
    quantity: line.quantity ?? "",
    amount: line.amount ?? "",
    serials: line.serials.join("\n"),
  };
}

/** Only what changed, in the API's shape; empty text clears a value. */
function changes(before: Draft, after: Draft): Edit {
  const edit: Edit = {};
  if (after.line_type !== before.line_type) edit.line_type = after.line_type;
  for (const name of ["product", "quantity", "amount"] as const) {
    const value = after[name].trim();
    if (value !== before[name]) edit[name] = value === "" ? null : value;
  }
  const serials = after.serials
    .split(/[\n,]/)
    .map((serial) => serial.trim())
    .filter(Boolean);
  if (serials.join("\n") !== before.serials) edit.serials = serials;
  return edit;
}

interface Props {
  invoice: InvoiceDetail;
  line: InvoiceLine;
  products: Product[];
  poSkus: Set<string>;
  run: Run;
}

/** One line: the vendor's values next to the system's interpretation, with the line's issues. */
export function LineCard({ invoice, line, products, poSkus, run }: Props) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const canEdit = invoice.actions.edit;
  const issues = invoice.issues.filter((issue) => issue.line === line.id);
  const raw = line.raw;

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const edit = changes(draftOf(line), draft);
    if (Object.keys(edit).length === 0 || (await run(() => api.editLine(invoice.id, line.id, edit)))) {
      setDraft(null);
    }
  }

  function value(name: string, content: ReactNode) {
    const edited = line.edited_fields.includes(name);
    return (
      <span className={edited ? "edited" : undefined}>
        {content}
        {edited && (
          <EditedMark
            disabled={!canEdit}
            onRevert={() => void run(() => api.editLine(invoice.id, line.id, { revert: [name] }))}
          />
        )}
      </span>
    );
  }

  const unitOfDraft = products.find((product) => product.sku === draft?.product)?.unit;
  const onPo = products.filter((product) => poSkus.has(product.sku));
  const others = products.filter((product) => !poSkus.has(product.sku));
  const option = (product: Product) => (
    <option key={product.sku} value={product.sku}>
      {product.sku} · {product.name} ({product.unit})
    </option>
  );

  return (
    <article className={`line line-${line.line_type}`}>
      <form onSubmit={save}>
        <div className="panel-title">
          <h3>
            Line {line.line_no}
            {raw.vendor_line_no ? <span className="muted"> (vendor line {raw.vendor_line_no})</span> : null}
          </h3>
          {canEdit && !draft && (
            <button type="button" onClick={() => setDraft(draftOf(line))}>
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
        <div className="compare">
          <div>
            <h4>In the file</h4>
            <dl>
              {RAW_ROWS.filter(([, keys]) => keys.some((key) => raw[key] !== undefined)).map(
                ([label, keys]) => (
                  <Fragment key={label}>
                    <dt>{label}</dt>
                    <dd>
                      {keys
                        .filter((key) => raw[key] !== undefined)
                        .map((key) => (
                          <Fragment key={key}>
                            <RawText value={raw[key]} />{" "}
                          </Fragment>
                        ))}
                    </dd>
                  </Fragment>
                ),
              )}
            </dl>
          </div>
          <div>
            <h4>Interpretation</h4>
            {draft ? (
              <dl className="form">
                <dt>Line type</dt>
                <dd>
                  <select
                    aria-label="Line type"
                    value={draft.line_type}
                    onChange={(event) => setDraft({ ...draft, line_type: event.target.value })}
                  >
                    <option value="product">product (received into stock)</option>
                    <option value="charge">charge (freight, insurance)</option>
                    <option value="summary">summary (not received)</option>
                  </select>
                </dd>
                {draft.line_type === "product" && (
                  <>
                    <dt>SKU</dt>
                    <dd>
                      <select
                        aria-label="SKU"
                        value={draft.product}
                        onChange={(event) => setDraft({ ...draft, product: event.target.value })}
                      >
                        <option value="">(not mapped)</option>
                        {onPo.length > 0 && (
                          <optgroup label={`On ${invoice.purchase_order}`}>{onPo.map(option)}</optgroup>
                        )}
                        <optgroup label="Catalog">{others.map(option)}</optgroup>
                      </select>
                    </dd>
                    <dt>Quantity</dt>
                    <dd>
                      <input
                        type="text"
                        inputMode="decimal"
                        aria-label="Quantity in the SKU's unit"
                        value={draft.quantity}
                        onChange={(event) => setDraft({ ...draft, quantity: event.target.value })}
                      />{" "}
                      {unitOfDraft ?? ""}
                    </dd>
                  </>
                )}
                <dt>Amount</dt>
                <dd>
                  <input
                    type="text"
                    inputMode="decimal"
                    aria-label="Amount"
                    value={draft.amount}
                    onChange={(event) => setDraft({ ...draft, amount: event.target.value })}
                  />{" "}
                  {invoice.currency}
                </dd>
                {draft.line_type === "product" && (
                  <>
                    <dt>Certificates</dt>
                    <dd>
                      <textarea
                        aria-label="Certificate numbers, one per line"
                        rows={3}
                        value={draft.serials}
                        onChange={(event) => setDraft({ ...draft, serials: event.target.value })}
                      />
                    </dd>
                  </>
                )}
              </dl>
            ) : (
              <dl>
                <dt>Line type</dt>
                <dd>{value("line_type", line.line_type)}</dd>
                {line.line_type === "product" && (
                  <>
                    <dt>SKU</dt>
                    <dd>
                      {value(
                        "product",
                        line.product ? `${line.product} · ${line.product_name}` : "not mapped",
                      )}
                    </dd>
                    <dt>Quantity</dt>
                    <dd>
                      {value("quantity", `${text(line.quantity)} ${line.quantity ? line.product_unit : ""}`)}
                    </dd>
                  </>
                )}
                <dt>Amount</dt>
                <dd>{value("amount", `${text(line.amount)} ${line.amount ? invoice.currency : ""}`)}</dd>
                {line.unit_cost && (
                  <>
                    <dt>Cost per {line.product_unit}</dt>
                    <dd>
                      {line.unit_cost} <span className="muted">(shown only; the exact amount is kept)</span>
                    </dd>
                  </>
                )}
                {line.serialized && (
                  <>
                    <dt>Certificates</dt>
                    <dd>{value("serials", line.serials.length ? line.serials.join(", ") : "none")}</dd>
                  </>
                )}
                {line.line_type === "product" && (
                  <>
                    <dt>PO line</dt>
                    <dd>
                      {line.po_line
                        ? `${line.po_line.purchase_order}: ordered ${line.po_line.qty_ordered}, received ` +
                          `${line.po_line.qty_received}, open ${line.po_line.remaining} at ${line.po_line.unit_cost}`
                        : "none"}
                    </dd>
                  </>
                )}
              </dl>
            )}
          </div>
        </div>
      </form>
      <IssuesList issues={issues} />
    </article>
  );
}
