"use client";

import { ErrorBox } from "@/components/ErrorBox";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";

const PO_STATUS: Record<string, string> = {
  open: "Open",
  partially_received: "Partially received",
  received: "Received",
};

export default function PurchaseOrdersPage() {
  const orders = useLoad(api.purchaseOrders);

  return (
    <>
      <h1>Purchase orders</h1>
      <p className="muted">Quantities are in each product&apos;s catalog unit.</p>
      <ErrorBox error={orders.error} />
      {orders.data?.map((order) => (
        <section className="panel" key={order.po_number}>
          <h2>
            {order.po_number} <span className={`badge po-${order.status}`}>{PO_STATUS[order.status]}</span>
          </h2>
          <p className="muted">
            {order.vendor} · {order.vendor_name} · ordered {order.order_date} · {order.currency}
          </p>
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Name</th>
                <th>Unit</th>
                <th className="num">Ordered</th>
                <th className="num">Received</th>
                <th className="num">Open</th>
                <th className="num">Unit cost</th>
              </tr>
            </thead>
            <tbody>
              {order.lines.map((line) => (
                <tr key={line.id}>
                  <td>{line.sku}</td>
                  <td>{line.name}</td>
                  <td>{line.unit}</td>
                  <td className="num">{line.qty_ordered}</td>
                  <td className="num">{line.qty_received}</td>
                  <td className="num">{line.remaining}</td>
                  <td className="num">{line.unit_cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  );
}
