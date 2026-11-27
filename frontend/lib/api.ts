// Typed client for the Django API. Every decimal arrives as an exact string and is
// shown as-is: the frontend never does arithmetic on money or quantities.

export type InvoiceStatus =
  "pending" | "needs_review" | "received" | "duplicate" | "rejected" | "closed_no_receipt";
export type IssueKind = "terminal" | "hard" | "soft" | "info";
export type LineType = "product" | "charge" | "summary";
export type DocumentType = "INVOICE" | "MEMO" | "CREDIT_MEMO";
export type RawValues = Record<string, string | string[] | null | undefined>;

export interface IssueCounts {
  terminal: number;
  hard: number;
  soft: number;
  info: number;
}

export interface InvoiceSummary {
  id: number;
  source_filename: string;
  status: InvoiceStatus;
  document_type: DocumentType | "";
  vendor: string | null;
  vendor_name: string | null;
  invoice_number: string;
  invoice_date: string | null;
  purchase_order: string | null;
  currency: string;
  total: string | null;
  issue_counts: IssueCounts;
  created_at: string;
}

export interface POLine {
  id: number;
  purchase_order: string;
  sku: string;
  name: string;
  unit: string;
  qty_ordered: string;
  qty_received: string;
  remaining: string;
  unit_cost: string;
}

export interface InvoiceLine {
  id: number;
  line_no: number;
  line_type: LineType;
  raw: RawValues;
  parsed: RawValues;
  product: string | null;
  product_name: string | null;
  product_unit: string | null;
  serialized: boolean;
  quantity: string | null;
  amount: string | null;
  unit_cost: string | null;
  serials: string[];
  po_line: POLine | null;
  edited_fields: string[];
}

export interface Issue {
  id: number;
  code: string;
  kind: IssueKind;
  message: string;
  line: number | null;
  line_no: number | null;
}

export interface AuditEvent {
  id: number;
  action: string;
  actor: string;
  payload: Record<string, unknown>;
  at: string;
}

export interface InvoiceActions {
  edit: boolean;
  approve: boolean;
  needs_confirmation: boolean;
  reject: boolean;
  close: boolean;
}

export interface InvoiceDetail extends InvoiceSummary {
  file_sha256: string;
  parser_key: string;
  status_notes: string;
  decided_at: string | null;
  duplicate_of: { id: number; source_filename: string } | null;
  subtotal: string | null;
  tax: string | null;
  notes: string;
  edited_fields: string[];
  raw_header: RawValues;
  parsed_header: RawValues;
  raw_content: string;
  lines: InvoiceLine[];
  issues: Issue[];
  audit_events: AuditEvent[];
  actions: InvoiceActions;
  already_uploaded?: boolean;
}

export interface Vendor {
  vendor_id: string;
  name: string;
  country: string;
  currency: string;
  ships_on_memo: boolean;
}

export interface Product {
  sku: string;
  name: string;
  category: string;
  unit: string;
  serialized: boolean;
  default_cost: string;
  on_hand: string;
}

export interface PurchaseOrder {
  po_number: string;
  vendor: string;
  vendor_name: string;
  order_date: string;
  currency: string;
  status: string;
  lines: POLine[];
}

export interface StockMovement {
  id: number;
  kind: "opening" | "receipt";
  sku: string;
  quantity: string;
  total_cost: string | null;
  currency: string;
  invoice: { id: number; source_filename: string } | null;
  po_number: string | null;
  created_at: string;
}

export type Edit = Record<string, unknown> & { revert?: string[] };

/** An API error with the server's explanation (and the blocking issues, for approve). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(describe(status, body));
  }

  get issues(): Pick<Issue, "code" | "kind" | "message" | "line_no">[] {
    const body = this.body as { issues?: Issue[] } | null;
    return body?.issues ?? [];
  }
}

function describe(status: number, body: unknown): string {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const fields = Object.entries(record).map(([field, errors]) => {
      const text = Array.isArray(errors) ? errors.join(" ") : String(errors);
      return field === "non_field_errors" ? text : `${field}: ${text}`;
    });
    if (fields.length) return fields.join("; ");
  }
  return `Request failed (HTTP ${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/${path}`, { cache: "no-store", ...init });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}

function send<T>(method: "POST" | "PATCH", path: string, body: object): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const api = {
  invoices: () => request<InvoiceSummary[]>("invoices"),
  invoice: (id: string | number) => request<InvoiceDetail>(`invoices/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<InvoiceDetail>("invoices", { method: "POST", body: form });
  },
  editInvoice: (id: number, edit: Edit) => send<InvoiceDetail>("PATCH", `invoices/${id}`, edit),
  editLine: (id: number, lineId: number, edit: Edit) =>
    send<InvoiceDetail>("PATCH", `invoices/${id}/lines/${lineId}`, edit),
  approve: (id: number, acceptDiscrepancies: boolean) =>
    send<InvoiceDetail>("POST", `invoices/${id}/approve`, { accept_discrepancies: acceptDiscrepancies }),
  reject: (id: number, reason: string) => send<InvoiceDetail>("POST", `invoices/${id}/reject`, { reason }),
  close: (id: number, reason: string) => send<InvoiceDetail>("POST", `invoices/${id}/close`, { reason }),
  vendors: () => request<Vendor[]>("vendors"),
  products: () => request<Product[]>("products"),
  purchaseOrders: () => request<PurchaseOrder[]>("purchase-orders"),
  stockMovements: () => request<StockMovement[]>("stock-movements"),
};

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
